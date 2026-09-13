#!/usr/bin/env python3
"""Check whether an OpenShift upgrade path exists and report associated risks.

Channel is optional. By default the script uses --stream (stable) and discovers
which stream-X.Y channels are needed. Intermediate versions come from Cincinnati
graph search with backtracking so a dead-end landing can fall back to an older
z-stream that still reaches the target.

Prefer modes:
- shortest: fewest hops; try farthest channel jumps; earliest tie-break
- latest: one minor at a time; try newest reachable landings first
"""

import codecs
import collections
import json
import re
import sys
import urllib.parse
import urllib.request


DEFAULT_CINCINNATI = 'https://api.openshift.com/api/upgrades_info/graph'
DEFAULT_STREAM = 'stable'
PREFER_SHORTEST = 'shortest'
PREFER_LATEST = 'latest'
_CHANNEL_REGEXP = re.compile(
    r'^(?P<stream>.+)-(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)$'
)
_VERSION_REGEXP = re.compile(
    r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)'
    r'(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$'
)


def parse_channel(channel):
    match = _CHANNEL_REGEXP.match(channel)
    if not match:
        raise ValueError(
            'invalid channel {!r}; expected stream-X.Y (for example stable-4.21)'.format(channel)
        )
    groups = match.groupdict()
    return groups['stream'], int(groups['major']), int(groups['minor'])


def parse_version(version):
    match = _VERSION_REGEXP.match(version)
    if not match:
        raise ValueError('invalid version {!r}'.format(version))
    groups = match.groupdict()
    prerelease = groups.get('prerelease') or ''
    # GA releases sort after prereleases with the same X.Y.Z.
    return (
        int(groups['major']),
        int(groups['minor']),
        int(groups['patch']),
        prerelease == '',
        prerelease,
    )


def version_sort_key(version):
    return parse_version(version)


def version_major_minor(version):
    major, minor, _, _, _ = parse_version(version)
    return major, minor


def load_cincinnati_graph(cincinnati, channel):
    split_uri = urllib.parse.urlsplit(cincinnati)
    query = urllib.parse.parse_qs(split_uri.query)
    query['channel'] = channel
    uri = urllib.parse.urlunsplit((
        split_uri.scheme,
        split_uri.netloc,
        split_uri.path,
        urllib.parse.urlencode(query, doseq=True),
        split_uri.fragment,
    ))
    with urllib.request.urlopen(uri) as f:
        data = json.load(codecs.getreader('utf-8')(f))

    versions = {node['version'] for node in data.get('nodes', [])}
    adjacency = collections.defaultdict(set)
    edge_risks = collections.defaultdict(list)

    for from_index, to_index in data.get('edges', []):
        from_version = data['nodes'][from_index]['version']
        to_version = data['nodes'][to_index]['version']
        adjacency[from_version].add(to_version)

    for conditional_edge in data.get('conditionalEdges', []):
        risks = conditional_edge.get('risks', [])
        for edge in conditional_edge.get('edges', []):
            from_version = edge['from']
            to_version = edge['to']
            adjacency[from_version].add(to_version)
            key = (from_version, to_version)
            for risk in risks:
                if risk not in edge_risks[key]:
                    edge_risks[key].append(risk)

    return versions, adjacency, edge_risks, uri


class GraphCache:
    def __init__(self, cincinnati):
        self.cincinnati = cincinnati
        self._cache = {}

    def get(self, channel):
        if channel not in self._cache:
            self._cache[channel] = load_cincinnati_graph(self.cincinnati, channel)
        return self._cache[channel]


def _neighbors(adjacency, current, skip_edges):
    skip_edges = skip_edges or set()
    return sorted(
        (
            neighbor for neighbor in adjacency.get(current, ())
            if (current, neighbor) not in skip_edges
        ),
        key=version_sort_key,
    )


def find_shortest_path(adjacency, start, goal, skip_edges=None):
    """Return one shortest path from start to goal, or None."""
    if start == goal:
        return [start]
    queue = collections.deque([start])
    parent = {start: None}
    while queue:
        current = queue.popleft()
        for neighbor in _neighbors(adjacency, current, skip_edges):
            if neighbor in parent:
                continue
            parent[neighbor] = current
            if neighbor == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(neighbor)
    return None


def find_shortest_path_to_minor(adjacency, start, target_major, target_minor, skip_edges=None):
    """Return one shortest path from start to any version in target major.minor."""
    start_major, start_minor = version_major_minor(start)
    if (start_major, start_minor) == (target_major, target_minor):
        return [start]

    queue = collections.deque([start])
    parent = {start: None}
    while queue:
        current = queue.popleft()
        for neighbor in _neighbors(adjacency, current, skip_edges):
            if neighbor in parent:
                continue
            parent[neighbor] = current
            major, minor = version_major_minor(neighbor)
            if (major, minor) == (target_major, target_minor):
                path = [neighbor]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(neighbor)
    return None


def find_reachable_in_minor(adjacency, start, target_major, target_minor, skip_edges=None):
    """Return all versions in target major.minor reachable from start."""
    start_major, start_minor = version_major_minor(start)
    if (start_major, start_minor) == (target_major, target_minor):
        return {start}

    reachable = set()
    queue = collections.deque([start])
    seen = {start}
    while queue:
        current = queue.popleft()
        for neighbor in _neighbors(adjacency, current, skip_edges):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            major, minor = version_major_minor(neighbor)
            if (major, minor) == (target_major, target_minor):
                reachable.add(neighbor)
            queue.append(neighbor)
    return reachable


def prefer_unconditional_path(find_path, adjacency, edge_risks, *args):
    """Try an unconditional path first, then any path. Returns (path, unconditional)."""
    unconditional = find_path(adjacency, *args, skip_edges=set(edge_risks))
    if unconditional:
        return unconditional, True
    any_path = find_path(adjacency, *args, skip_edges=None)
    if any_path:
        return any_path, False
    return None, False


def path_to_version(adjacency, edge_risks, start, goal):
    return prefer_unconditional_path(find_shortest_path, adjacency, edge_risks, start, goal)


def risks_on_path(path, edge_risks):
    risks_by_name = {}
    edges_with_risks = []
    for from_version, to_version in zip(path, path[1:]):
        risks = edge_risks.get((from_version, to_version), [])
        if risks:
            edges_with_risks.append((from_version, to_version, risks))
        for risk in risks:
            name = risk.get('name') or '(unnamed)'
            if name not in risks_by_name:
                risks_by_name[name] = risk
    return edges_with_risks, risks_by_name


def format_path(path):
    return ' -> '.join(path)


def merge_risks(*risk_maps):
    merged = {}
    for risk_map in risk_maps:
        for name, risk in risk_map.items():
            if name not in merged:
                merged[name] = risk
    return merged


def print_risks(risks_by_name, edges_with_risks):
    if not risks_by_name:
        print('Associated risks: none on the reported path')
        return
    print('Associated risks: {}'.format(len(risks_by_name)))
    print()
    for name in sorted(risks_by_name):
        risk = risks_by_name[name]
        print('- {}'.format(name))
        print('  url: {}'.format(risk.get('url') or '(none)'))
        message = risk.get('message')
        if message:
            print('  message: {}'.format(message))
    if edges_with_risks:
        print()
        print('Risky edges on reported path:')
        for from_version, to_version, risks in edges_with_risks:
            names = ', '.join(sorted(r.get('name') or '(unnamed)' for r in risks))
            print('  {} -(risks: {})-> {}'.format(from_version, names, to_version))


def report_single_channel_path(from_version, to_version, channel, versions, adjacency, edge_risks, uri, prefer):
    print('Mode: single-channel')
    print('Prefer: {}'.format(prefer))
    print('Channels used: {}'.format(channel))
    print('Cincinnati: {}'.format(uri))
    print('From: {}'.format(from_version))
    print('To: {}'.format(to_version))
    print()

    if from_version not in versions or to_version not in versions:
        missing = [v for v in (from_version, to_version) if v not in versions]
        print('Path exists: no')
        print('Reason: version(s) not present in channel: {}'.format(', '.join(missing)))
        return 1

    if from_version == to_version:
        print('Path exists: yes')
        print('Reason: already on the target version')
        return 0

    path, unconditional = path_to_version(adjacency, edge_risks, from_version, to_version)
    if not path:
        print('Path exists: no')
        print('Reason: no update edges connect {} to {} in {}'.format(
            from_version, to_version, channel))
        return 1

    print('Path exists: yes')
    print('Unconditional path: {}'.format('yes' if unconditional else 'no'))
    label = 'Shortest unconditional path' if unconditional else 'Shortest path (includes conditional/risky edges)'
    print('{}: {}'.format(label, format_path(path)))
    edges_with_risks, risks_by_name = risks_on_path(path, edge_risks)
    print_risks(risks_by_name, edges_with_risks)
    return 0


def _landing_candidates(adjacency, edge_risks, start, target_major, target_minor, prefer):
    """Ordered landing versions in target minor to try (best first)."""
    uncond = find_reachable_in_minor(
        adjacency, start, target_major, target_minor, skip_edges=set(edge_risks),
    )
    any_reachable = find_reachable_in_minor(
        adjacency, start, target_major, target_minor, skip_edges=None,
    )
    reverse = prefer == PREFER_LATEST
    ordered = []
    for version in sorted(uncond, key=version_sort_key, reverse=reverse):
        ordered.append(version)
    for version in sorted(any_reachable - uncond, key=version_sort_key, reverse=reverse):
        ordered.append(version)
    return ordered


def _can_reach(adjacency, edge_risks, start, goal):
    path, _ = path_to_version(adjacency, edge_risks, start, goal)
    return path is not None


def stitch_cross_minor_path(from_version, to_version, stream, cincinnati, prefer=PREFER_SHORTEST):
    """
    Build a path across minors using stream-X.Y channels discovered automatically.

    Uses backtracking: if the newest/farthest landing cannot continue to the
    target, older landings in that minor are tried.
    """
    from_major, from_minor, _, _, _ = parse_version(from_version)
    to_major, to_minor, _, _, _ = parse_version(to_version)
    if from_major != to_major:
        raise ValueError(
            'cross-major upgrades are not supported ({} -> {})'.format(from_version, to_version)
        )
    if (from_major, from_minor) > (to_major, to_minor):
        raise ValueError(
            'from version {} is newer than to version {}'.format(from_version, to_version)
        )

    cache = GraphCache(cincinnati)

    def solve(current, next_minor):
        if current == to_version:
            return []

        cur_major, cur_minor = version_major_minor(current)
        if next_minor > to_minor:
            return None
        if cur_minor > next_minor:
            # Already past this minor; continue forward.
            return solve(current, cur_minor + 1 if cur_minor < to_minor else to_minor)

        channel = '{}-{}.{}'.format(stream, cur_major, next_minor)
        try:
            versions, adjacency, edge_risks, uri = cache.get(channel)
        except Exception as exc:  # noqa: BLE001
            raise ValueError('{}: failed to load ({})'.format(channel, exc)) from exc

        if current not in versions:
            return None

        if next_minor == to_minor:
            path, unconditional = path_to_version(adjacency, edge_risks, current, to_version)
            if not path:
                return None
            return [{
                'channel': channel,
                'uri': uri,
                'path': path,
                'unconditional': unconditional,
            }]

        candidates = _landing_candidates(
            adjacency, edge_risks, current, cur_major, next_minor, prefer,
        )
        if not candidates:
            return None

        # Before the final minor, drop landings that cannot reach the target.
        if next_minor == to_minor - 1:
            final_channel = '{}-{}.{}'.format(stream, cur_major, to_minor)
            try:
                final_versions, final_adj, final_risks, _ = cache.get(final_channel)
            except Exception:
                final_versions, final_adj, final_risks = set(), {}, {}
            filtered = [
                version for version in candidates
                if version in final_versions and _can_reach(final_adj, final_risks, version, to_version)
            ]
            if filtered:
                candidates = filtered

        # shortest: also try max-jump landings before stepping +1 minor only.
        # For backtracking simplicity, both modes walk minor-by-minor here;
        # shortest just prefers earlier z-streams first.
        for landing in candidates:
            path, unconditional = path_to_version(adjacency, edge_risks, current, landing)
            if not path:
                continue
            rest = solve(landing, next_minor + 1)
            if rest is None:
                continue
            segment = {
                'channel': channel,
                'uri': uri,
                'path': path,
                'unconditional': unconditional,
            }
            return [segment] + rest
        return None

    # shortest: try farthest first by attempting larger first jumps via recursion
    # that starts at from_minor+1. Optional max-jump: try starting solve with
    # farther first using a wrapper.
    if prefer == PREFER_SHORTEST:
        segments = _solve_shortest_with_jumps(
            from_version, to_version, stream, cache, from_major, from_minor, to_minor,
        )
    else:
        segments = solve(from_version, from_minor + 1)

    if not segments:
        raise ValueError(
            'no upgrade path from {} to {} using {}-X.Y channels'.format(
                from_version, to_version, stream,
            )
        )

    full_path = [from_version]
    all_edges_with_risks = []
    all_risks = {}
    all_unconditional = True
    for segment in segments:
        full_path.extend(segment['path'][1:])
        versions, adjacency, edge_risks, _ = cache.get(segment['channel'])
        edges_with_risks, risks_by_name = risks_on_path(segment['path'], edge_risks)
        all_edges_with_risks.extend(edges_with_risks)
        all_risks = merge_risks(all_risks, risks_by_name)
        all_unconditional = all_unconditional and segment['unconditional']

    return {
        'path': full_path,
        'segments': segments,
        'unconditional': all_unconditional,
        'edges_with_risks': all_edges_with_risks,
        'risks_by_name': all_risks,
        'prefer': prefer,
        'channels': [segment['channel'] for segment in segments],
    }


def _solve_shortest_with_jumps(from_version, to_version, stream, cache, major, from_minor, to_minor):
    """Fewest channel/minor hops with backtracking on dead-end landings."""

    def solve(current, next_minor):
        if current == to_version:
            return []
        cur_major, cur_minor = version_major_minor(current)
        if next_minor > to_minor:
            return None

        # Try farthest destination minor first.
        for dest_minor in range(to_minor, max(next_minor, cur_minor + 1) - 1, -1):
            if dest_minor <= cur_minor and current != to_version:
                continue
            channel = '{}-{}.{}'.format(stream, major, dest_minor)
            try:
                versions, adjacency, edge_risks, uri = cache.get(channel)
            except Exception:
                continue
            if current not in versions:
                continue

            if dest_minor == to_minor:
                path, unconditional = path_to_version(adjacency, edge_risks, current, to_version)
                if not path:
                    continue
                return [{
                    'channel': channel,
                    'uri': uri,
                    'path': path,
                    'unconditional': unconditional,
                }]

            candidates = _landing_candidates(
                adjacency, edge_risks, current, major, dest_minor, PREFER_SHORTEST,
            )
            if dest_minor == to_minor - 1:
                final_channel = '{}-{}.{}'.format(stream, major, to_minor)
                try:
                    final_versions, final_adj, final_risks, _ = cache.get(final_channel)
                except Exception:
                    final_versions, final_adj, final_risks = set(), {}, {}
                filtered = [
                    version for version in candidates
                    if version in final_versions and _can_reach(final_adj, final_risks, version, to_version)
                ]
                if filtered:
                    candidates = filtered

            for landing in candidates:
                path, unconditional = path_to_version(adjacency, edge_risks, current, landing)
                if not path:
                    continue
                rest = solve(landing, dest_minor + 1)
                if rest is None:
                    continue
                return [{
                    'channel': channel,
                    'uri': uri,
                    'path': path,
                    'unconditional': unconditional,
                }] + rest
        return None

    return solve(from_version, from_minor + 1)


def report_stitched_path(from_version, to_version, stream, result):
    print('Mode: cross-minor (auto-stitch)')
    print('Prefer: {}'.format(result['prefer']))
    print('Stream: {}'.format(stream))
    print('Channels used: {}'.format(', '.join(result['channels'])))
    print('From: {}'.format(from_version))
    print('To: {}'.format(to_version))
    print()
    print('Path exists: yes')
    print('Unconditional path: {}'.format('yes' if result['unconditional'] else 'no'))
    print('Joined path: {}'.format(format_path(result['path'])))
    print()
    print('Segments:')
    for segment in result['segments']:
        kind = 'unconditional' if segment['unconditional'] else 'conditional/risky'
        print('  [{}] ({}) {}'.format(segment['channel'], kind, format_path(segment['path'])))
        print('    {}'.format(segment['uri']))
    print()
    print_risks(result['risks_by_name'], result['edges_with_risks'])
    return 0


def check_upgrade_path(
    from_version,
    to_version,
    stream=DEFAULT_STREAM,
    channel=None,
    cincinnati=DEFAULT_CINCINNATI,
    prefer=PREFER_SHORTEST,
):
    if prefer not in (PREFER_SHORTEST, PREFER_LATEST):
        raise ValueError('invalid prefer mode {!r}'.format(prefer))

    parse_version(from_version)
    parse_version(to_version)
    from_major, from_minor = version_major_minor(from_version)
    to_major, to_minor = version_major_minor(to_version)

    if channel:
        channel_stream, _, _ = parse_channel(channel)
        if stream == DEFAULT_STREAM:
            stream = channel_stream
        versions, adjacency, edge_risks, uri = load_cincinnati_graph(cincinnati, channel)
        if from_version in versions and to_version in versions:
            return report_single_channel_path(
                from_version, to_version, channel, versions, adjacency, edge_risks, uri, prefer,
            )

    if from_major != to_major:
        print('Mode: unsupported')
        print('From: {}'.format(from_version))
        print('To: {}'.format(to_version))
        print()
        print('Path exists: no')
        print('Reason: cross-major upgrades are not supported')
        return 1

    if (from_major, from_minor) == (to_major, to_minor):
        auto_channel = '{}-{}.{}'.format(stream, to_major, to_minor)
        versions, adjacency, edge_risks, uri = load_cincinnati_graph(cincinnati, auto_channel)
        return report_single_channel_path(
            from_version, to_version, auto_channel, versions, adjacency, edge_risks, uri, prefer,
        )

    try:
        result = stitch_cross_minor_path(
            from_version=from_version,
            to_version=to_version,
            stream=stream,
            cincinnati=cincinnati,
            prefer=prefer,
        )
    except ValueError as exc:
        print('Mode: cross-minor (auto-stitch)')
        print('Prefer: {}'.format(prefer))
        print('Stream: {}'.format(stream))
        print('From: {}'.format(from_version))
        print('To: {}'.format(to_version))
        print()
        print('Path exists: no')
        print('Reason: {}'.format(exc))
        return 1

    return report_stitched_path(from_version, to_version, stream, result)


if __name__ == '__main__':
    import argparse

    class HelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
        """Do not line-wrap description or epilog. Also include option defaults."""

    parser = argparse.ArgumentParser(
        description='''Check whether an upgrade path exists between two versions and report risks.

Channel is optional. The script uses --stream (default: stable) and discovers
which stream-X.Y channels are needed. Those channels are printed in the output.

Prefer modes:
  shortest  fewest hops; may land on an earlier z-stream in each minor
  latest    one minor at a time; newest reachable z-stream first, with
            backtracking if that landing cannot reach the target

Examples:
# Cross-minor, no channel required (discovers channels)
%(prog)s --prefer latest --from 4.17.52 --to 4.21.22

# Same check with explicit stream
%(prog)s --prefer latest --stream stable --from 4.17.52 --to 4.21.22

# Optional channel only forces single-channel mode when both versions are in it
%(prog)s --from 4.18.20 --to 4.19.20 --channel stable-4.19
''',
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        '--from',
        dest='from_version',
        metavar='VERSION',
        required=True,
        help='Current cluster version.',
    )
    parser.add_argument(
        '--to',
        dest='to_version',
        metavar='VERSION',
        required=True,
        help='Target cluster version.',
    )
    parser.add_argument(
        '--stream',
        default=DEFAULT_STREAM,
        help='Channel stream used to discover stream-X.Y graphs.',
    )
    parser.add_argument(
        '--prefer',
        choices=(PREFER_SHORTEST, PREFER_LATEST),
        default=PREFER_SHORTEST,
        help='Path selection policy for cross-minor intermediates.',
    )
    parser.add_argument(
        '--channel',
        metavar='CHANNEL',
        help='Optional. If both versions are in this channel, evaluate only there.',
    )
    parser.add_argument(
        '--cincinnati',
        metavar='URI',
        default=DEFAULT_CINCINNATI,
        help='Cincinnati graph endpoint.',
    )
    # Backwards-compatible optional positional channel.
    parser.add_argument(
        'positional_channel',
        nargs='?',
        metavar='CHANNEL',
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()
    channel = args.channel or args.positional_channel
    stream = args.stream
    if channel and args.stream == DEFAULT_STREAM:
        try:
            stream = parse_channel(channel)[0]
        except ValueError:
            pass

    try:
        sys.exit(check_upgrade_path(
            from_version=args.from_version,
            to_version=args.to_version,
            stream=stream,
            channel=channel,
            cincinnati=args.cincinnati,
            prefer=args.prefer,
        ))
    except ValueError as exc:
        print('Error: {}'.format(exc), file=sys.stderr)
        sys.exit(2)
