#!/usr/bin/env python3

import codecs
import collections
import datetime
import http
import json
import logging
import os
import re
import socket
import subprocess
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import github
except ModuleNotFoundError as error:
    github_import_error = error
    github = None

import yaml

import util


logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)
_ADVISORY_TYPE_REGEXP = re.compile(r'RH[BS]A')
_ISO_8601_DELAY_REGEXP = re.compile(r'^P((?P<weeks>\d+)W|((?P<days>\d+)D)?(T(?P<hours>\d+)H)?)$')
_GIT_BLAME_COMMIT_REGEXP = re.compile(r'^(?P<hash>[0-9a-f]{40}) .*')
_GIT_BLAME_HEADER_REGEXP = re.compile(r'^(?P<key>[^ \t]+) (?P<value>.*)$')
_GIT_BLAME_LINE_REGEXP = re.compile(r'^\t(?P<value>.*)$')
_GIT_REMOTE_LINE_REGEXP = re.compile(r'^(?P<remote>[^ ]*)\t(?P<uri>(?P<scheme>[^:]*)://(?P<host>[^/]*)/(?P<org>[^/]*)/(?P<repo>[^/.]*)(.git)?) [(](?P<role>.*)[)]$')
_SEM_VER_REGEXP = re.compile(r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')
_REMOTE_CACHE = {}
_SEMANTIC_VERSION_DELIMITERS = re.compile('[.+-]')

socket.setdefaulttimeout(60)


class PullRequest(object):
    """Drop-in stub for github.PullRequest when we fail to import 'github'."""
    def __init__(self, html_url):
        self.html_url = html_url


def parse_iso8601_delay(delay):
    # https://tools.ietf.org/html/rfc3339#page-13
    match = _ISO_8601_DELAY_REGEXP.match(delay)
    if not match:
        raise ValueError('invalid or unsupported ISO 8601 duration {!r}.  Tooling currently only supports P<number>W for weeks, or P<number>DT<number>H for day/hour offsets'.format(delay))
    weeks = int(match.group('weeks') or 0)
    days = int(match.group('days') or 0)
    hours = int(match.group('hours') or 0)
    return datetime.timedelta(weeks=weeks, days=days, hours=hours)


def sem_ver_less_than(a, b):
    """Returns true if a is less than b, per https://semver.org/spec/v2.0.0.html#spec-item-11"""
    a_match = _SEM_VER_REGEXP.match(a)
    if not a_match:
        raise ValueError('invalid semantic version {!r}'.format(a_match))
    b_match = _SEM_VER_REGEXP.match(b)
    if not b_match:
        raise ValueError('invalid semantic version {!r}'.format(b_match))
    a_groups = a_match.groupdict()
    b_groups = b_match.groupdict()

    if int(a_groups['major']) < int(b_groups['major']):
        return True
    if int(a_groups['major']) > int(b_groups['major']):
        return False

    if int(a_groups['minor']) < int(b_groups['minor']):
        return True
    if int(a_groups['minor']) > int(b_groups['minor']):
        return False

    if int(a_groups['patch']) < int(b_groups['patch']):
        return True
    if int(a_groups['patch']) > int(b_groups['patch']):
        return False

    if a_groups['prerelease'] and not b_groups['prerelease']:
        return True
    if b_groups['prerelease'] and not a_groups['prerelease']:
        return False

    # Reaching here means releases are equal unless both sides
    # have a prerelease segment
    if not (a_groups['prerelease'] or b_groups['prerelease']):
        return False

    # cheating vs. the SemVer spec.
    return a_groups['prerelease'] < b_groups['prerelease']


def stabilization_changes(directories, webhook=None, **kwargs):
    channels, channel_paths = util.load_channels(directories=directories)

    update_risks = {}
    for path, data in util.walk_yaml(directory='blocked-edges'):
        update_risks[path] = data

    cache = {}
    notifications = []
    for name, channel in sorted(channels.items()):
        notifications.extend(stabilize_channel(name=name, channel=channel, channels=channels, channel_paths=channel_paths, update_risks=update_risks, cache=cache, **kwargs))
    if notifications:
        deduped_notifications = []
        for notification in notifications:
            if notification not in deduped_notifications:
                deduped_notifications.append(notification)
        notify(message='* ' + ('\n* '.join(deduped_notifications)), webhook=webhook)


def stabilize_channel(name, channel, channels, channel_paths, cache=None, **kwargs):
    if not channel.get('feeder'):
        return
    feeder = channel['feeder']['name']
    conditions = []

    delay_string = channel['feeder'].get('delay')
    if delay_string is not None:
        delay = parse_iso8601_delay(delay=delay_string)
        conditions.append('{}'.format(delay_string))
    else:
        delay = None

    errata = channel['feeder'].get('errata')
    if errata is not None and errata != 'public':
        raise ValueError('invalid errata value for {}: {}', channel, errata)
    if errata:
        conditions.append('the errata is published')

    version_filter = re.compile('^{}$'.format(channel['feeder'].get('filter', '.*')))
    feeder_data = channels[feeder]
    tombstones = set(feeder_data.get('tombstones', {}))
    zombies = set(channel['versions']).intersection(tombstones)
    if zombies:
        _LOGGER.warning('some versions in {} despite tombstones in {}: {}'.format(name, feeder, ', '.join(sorted(zombies))))
    unpromoted = set(feeder_data['versions']) - set(channel['versions']) - tombstones
    candidates = set(v for v in unpromoted if version_filter.match(v))
    if candidates:
        feeder_promotions = get_promotions(channel_paths[feeder])
        _LOGGER.info('considering promotions from {} to {} after {}'.format(feeder, name, ' or '.join(conditions)))
        for version in sorted(candidates):
            feeder_promotion = feeder_promotions[version]
            yield from stabilize_release(
                version=version,
                channel=channel,
                channel_path=channel_paths[name],
                delay=delay,
                errata=errata,
                feeder_name=feeder,
                feeder_promotion=feeder_promotion,
                candidates=candidates,
                cache=cache,
                **kwargs)
    yield from get_concerns_about_patch_updates(
        channel=channel,
        cache=cache)


def stabilize_release(version, channel, channel_path, delay, errata, feeder_name, feeder_promotion, candidates, cache, update_risks=None, waiting_notifications=True, github_token=None, **kwargs):
    now = datetime.datetime.now()
    version_delay = now - feeder_promotion['committer-time']
    errata_public = False
    public_errata_message = ''
    if errata:
        errata_uri, errata_public = public_errata_uri(version=version, channel=feeder_name, cache=cache)
        if errata_uri:
            public_errata_message = ' {} is{} public.'.format(errata_uri, '' if errata_public else ' not')

    concerns = []
    concerns_about_risk_extensions = get_concerns_about_risk_extensions(version=version, channel=channel, candidates=candidates, update_risks=update_risks)
    if concerns_about_risk_extensions:
        _LOGGER.error('  failed to promote {} to {}: {}'.format(version, channel['name'], concerns_about_risk_extensions))
        yield 'FAILED {}'.format(concerns_about_risk_extensions)
        return
    concerns_about_updating_out = get_concerns_about_updating_out(version=version, channel=channel, cache=cache)
    if concerns_about_updating_out:
        concerns.append(concerns_about_updating_out)

    if not concerns and ((delay is not None and version_delay > delay) or errata_public):
        path_without_extension, _ = os.path.splitext(channel_path)
        subject = '{}: Promote {}'.format(path_without_extension, version)
        body = 'It was promoted to the feeder {} by {} ({}, {}) {} ago.{}'.format(
                feeder_name,
                feeder_promotion['hash'][:10],
                feeder_promotion['summary'],
                feeder_promotion['committer-time'].date().isoformat(),
                version_delay,
                public_errata_message,
            )
        try:
            pull = promote(
                version=version,
                channel_name=channel['name'],
                channel_path=channel_path,
                subject=subject,
                body=body,
                github_token=github_token,
                **kwargs)
        except Exception as exc:
            _LOGGER.error('  failed to promote {} to {}: {}'.format(version, channel['name'], sanitize(exc, github_token=github_token)))
            yield 'FAILED {}. {} {}'.format(subject, body, sanitize(exc, github_token=github_token))
        else:
            yield '{}. {} {}'.format(subject, body, pull.html_url)
    else:
        if concerns:
            concerns.insert(0, '')  # when joined with the whitespace delimiter, this will add leading space to offset from the rest of the message
        _LOGGER.info('  waiting: {} ({}){}{}'.format(version, version_delay, public_errata_message, '  '.join(concerns)))
        if waiting_notifications:
            yield 'Recommend waiting to promote {} to {}; it was promoted the feeder {} by {} ({}, {}, {}){}{}'.format(
                version,
                channel['name'],
                feeder_name,
                feeder_promotion['hash'][:10],
                feeder_promotion['summary'],
                feeder_promotion['committer-time'].date().isoformat(),
                version_delay,
                public_errata_message,
                '  '.join(concerns))


def get_promotions(path):
    # https://git-scm.com/docs/git-blame#_the_porcelain_format
    process = subprocess.run(['git', 'blame', '--first-parent', '--porcelain', path], check=True, capture_output=True, text=True)
    commits = {}
    lines = {}
    for i, line in enumerate(process.stdout.strip().split('\n')):
        match = _GIT_BLAME_COMMIT_REGEXP.match(line)
        if match:
            commit = match.group('hash')
            if commit not in commits:
                commits[commit] = {'hash': commit}
            continue
        match = _GIT_BLAME_HEADER_REGEXP.match(line)
        if match:
            key = match.group('key')
            value = match.group('value')
            if key == 'committer-time':
                commits[commit]['committer-time'] = datetime.datetime.fromtimestamp(int(value))
            else:
                commits[commit][key] = value
            continue
        match = _GIT_BLAME_LINE_REGEXP.match(line)
        if not match:
            raise ValueError('unrecognized blame output for {} (blame line {}): {}'.format(path, i+1, line))
        lines[match.group('value')] = commit
    promotions = {}
    for line, commit in lines.items():
        if line.startswith('- '):
            version = line[2:]
            promotions[version] = commits[commit]
    return promotions


def public_errata_uri(version, cache=None, **kwargs):
    if cache and cache.get('versions', {}).get(version, -1) != -1:
        cached = cache['versions'][version]
        if not cached:
            return None, None
        return cached['uri'], cached['public']
    if kwargs.get('channel') == 'candidate':
        major_minor = '.'.join(version.split('.', 2)[:2])
        kwargs['channel'] = 'candidate-{}'.format(major_minor)
    cincinnati_uri, cincinnati_data = get_cincinnati_channel(cache=cache, **kwargs)
    canonical_errata_uri = errata_uri_from_cincinnati(version=version, cincinnati_data=cincinnati_data, cincinnati_uri=cincinnati_uri)
    if not canonical_errata_uri:
        if cache is not None:
            if 'versions' not in cache:
                cache['versions'] = {}
            cache['versions'][version] = None
        return None, None
    errata_uri, public = _public_errata_uri(uri=canonical_errata_uri)
    if cache is not None:
        if 'versions' not in cache:
            cache['versions'] = {}
        cache['versions'][version] = {
            'uri': errata_uri,
            'public': public,
        }
    return errata_uri, public


def get_concerns_about_risk_extensions(version, channel, candidates, update_risks=None):
    if update_risks is None:
        return

    release_major_minor = '.'.join(version.split('.', 2)[:2])
    previous_version = None
    candidate_previous_versions = set(channel.get('versions', [])).union(candidates)
    for target in candidate_previous_versions:
        target_major_minor = '.'.join(target.split('.', 2)[:2])
        if target_major_minor != release_major_minor:
            continue  # we're only looking at earlier patch releases in the same 4.y
        if sem_ver_less_than(target, version) and (previous_version is None or sem_ver_less_than(previous_version, target)):
            previous_version = target
    if previous_version is None:
        return

    risks = set()
    previous_risks = {}
    for path, risk in sorted(update_risks.items()):
        key = risk.get('name', path)
        if risk['to'] == version:
            risks.add(key)
        if risk['to'] == previous_version:
            fixed_in = risk.get('fixedIn', None)
            if fixed_in is None or (version != fixed_in and sem_ver_less_than(version, fixed_in)):
                previous_risks[key] = fixed_in

    unfixed = []
    for key, fixed_in in sorted(previous_risks.items()):
        if key in risks:
            continue
        if fixed_in:
            unfixed.append('{} affects {} and is not fixed until {}.  Extend the risk to {}.'.format(key, previous_version, fixed_in, version))
        else:
            unfixed.append('{} affects {}.  Either declare a fix version or extend the risk to {}.'.format(key, previous_version, version))

    if unfixed:
        return ' '.join(unfixed)
    return


def get_concerns_about_updating_out(version, channel, cache=None):
    release_major_minor = '.'.join(version.split('.', 2)[:2])
    try:
        phase, channel_major_minor = channel['name'].rsplit('-', 1)
    except ValueError:
        return  # 'fast' and similar version-agnostic channels do not need updating-out concerns
    if phase == 'candidate':
        return  # we need ungated candidate-4.y admission to bootstrap using candidate-4.y update recommendations for gating later phases.
    if release_major_minor == channel_major_minor:
        return  # we are concerned about getting from 4.(y-1) and earlier into 4.y, not about movement within 4.y.
    updates = {}
    channel_versions = set(channel.get('versions', set()))
    cincinnati_uris = []

    # work around 4.(y-1) limit for today's candidate-4.y channels by iterating over multiple candidate channels
    release_major, release_minor = (int(x) for x in release_major_minor.split('.'))
    channel_major, channel_minor = (int(x) for x in channel_major_minor.split('.'))
    if release_major != channel_major:
        raise ValueError('unclear which candidate channels to pull for update information between {} and {}'.format(release_major_minor, channel_major_minor))
    candidate_minor = channel_minor
    while candidate_minor > release_minor:
        cincinnati_uri, cincinnati_data = get_cincinnati_channel(cache=cache, channel='candidate-{}.{}'.format(channel_major, candidate_minor))
        nodes = cincinnati_data.get('nodes', [])
        for edge in cincinnati_data.get('edges', []):
            source = nodes[edge[0]]['version']
            target = nodes[edge[1]]['version']
            if target not in channel_versions or (source != version and source not in channel_versions):
                continue  # even if we promote version, this edge will not be in the target channel
            if source not in updates:
                updates[source] = set()
            updates[source].add(target)
        for conditional in cincinnati_data.get('conditionalEdges', []):
            for edge in conditional.get('edges', []):
                if edge['to'] not in channel_versions or (edge['from'] != version and edge['from'] not in channel_versions):
                    continue  # even if we promote version, this edge will not be in the target channel
                if edge['from'] not in updates:
                    updates[edge['from']] = set()
                updates[edge['from']].add(edge['to'])
        cincinnati_uris.append(cincinnati_uri)
        candidate_minor -= 1

    reachable = {version}
    while reachable:
        source = reachable.pop()
        targets = updates.get(source, set())
        for target in targets:
            target_major_minor = '.'.join(target.split('.', 2)[:2])
            if target_major_minor == channel_major_minor:
                return  # we have update path to the target major.minor.
        reachable.update(targets)  # maybe additional hops will get us to the target major.minor.

    return 'No paths from {} to {} in {}'.format(version, channel_major_minor, ' '.join(cincinnati_uris))


def get_concerns_about_patch_updates(channel, cache=None):
    if len(channel['versions']) > 1:
        patch_updates = collections.defaultdict(lambda: collections.defaultdict(set))
        largest_version = list(sorted(channel['versions'], key=semver_sort_key))[-1]
        release_major, release_minor = (int(x) for x in largest_version.split('.')[:2])
        major_minor_prefix = '{}.{}.'.format(release_major, release_minor)
        early_channel = 'candidate-{}.{}'.format(release_major, release_minor)
        if major_minor_prefix == '4.1.':
            early_channel = 'prerelease-{}.{}'.format(release_major, release_minor)
        cincinnati_uri, cincinnati_data = get_cincinnati_channel(cache=cache, channel=early_channel)
        nodes = cincinnati_data.get('nodes', [])
        for edge in cincinnati_data.get('edges', []):
            source = nodes[edge[0]]['version']
            target = nodes[edge[1]]['version']
            if target in channel['versions']:
                patch_updates[source][None].add(target)
        for conditional in cincinnati_data.get('conditionalEdges', []):
            for edge in conditional.get('edges', []):
                if edge['to'] in patch_updates[edge['from']].get(None, {}):  # work around https://issues.redhat.com/browse/OCPBUGS-25833
                    patch_updates[edge['from']][None].remove(edge['to'])
                    if len(patch_updates[edge['from']][None]) == 0:
                        del patch_updates[edge['from']][None]
                    if len(patch_updates[edge['from']]) == 0:
                        del patch_updates[edge['from']]
                for risk in conditional.get('risks', []):
                    patch_updates[edge['from']][risk['name']].add(edge['to'])
        warnings = {}
        for version in sorted(channel['versions'], key=semver_sort_key):
            if not version.startswith(major_minor_prefix):
                continue  # older major.minor will have patch updates checked in channels capped at that major.minor
            if version == largest_version:
                continue  # there can be no updates from the largest release in the channel, that will need future releases
            if None in patch_updates.get(version, {}):
                continue  # unconditional patch update exists
            if version in patch_updates:
                risks = sorted(set(patch_updates[version].keys()))
                warnings[version] = '{} has patch updates in {}, but they are exposed to risks: {}'.format(version, channel['name'], ', '.join(risks))
                continue
            warnings[version] = '{} has no patch updates in {}'.format(version, channel['name'])
        for version, warning in sorted(warnings.items()):
            will_complain_about_later_release = False
            for risk, targets in patch_updates[version].items():
                for target in targets:
                    if target in warnings:
                        will_complain_about_later_release = True
                        _LOGGER.debug('ignore {} ({}), because it can update to {}, and we will complain about {} ({})'.format(version, warning, target, target, warnings[target]))
                        break
                if will_complain_about_later_release:
                    break
            if not will_complain_about_later_release:
                sem_ver = _SEM_VER_REGEXP.match(version)
                if sem_ver and sem_ver.group('prerelease'):
                    _LOGGER.debug('ignore patch connectivity for prerelease {}'.format(warning))
                    continue  # do not worry about connectivity among prereleases
                if version in {
                        '4.1.38',  # has no patch updates in stable-4.1, but nothing we can do about that now
                        '4.2.14+amd64',  # has no patch updates in fast-4.2, because this function doesn't understand graph-data's arch suffixes
                    }:
                    continue
                yield warning


def get_cincinnati_channel(arch='amd64', channel='', update_service='https://api.openshift.com/api/upgrades_info/v1/graph', cache=None):
    params = {
        'channel': channel,
        'arch': arch,
    }

    headers = {
        'Accept': 'application/json',
    }

    uri = '{}?{}'.format(update_service, urllib.parse.urlencode(params))

    if cache and cache.get('channels', {}).get(channel, {}).get(arch):
        return uri, cache['channels'][channel][arch]

    request = urllib.request.Request(uri, headers=headers)
    _LOGGER.debug('retrieve Cincinnati data from {}'.format(uri))
    while True:
        try:
            with urllib.request.urlopen(request) as f:
                data = json.load(codecs.getreader('utf-8')(f))  # hack: should actually respect Content-Type
        except Exception as exc:
            _LOGGER.error('{}: {}'.format(uri, exc))
            time.sleep(10)
            continue
        break
    if cache is not None:
        if 'channels' not in cache:
            cache['channels'] = {}
        if channel not in cache['channels']:
            cache['channels'][channel] = {}
        cache['channels'][channel][arch] = data
    return uri, data


def errata_uri_from_cincinnati(version, cincinnati_data, cincinnati_uri='Cincinnati'):
    versions = set()
    errata_uri = None
    for node in cincinnati_data['nodes']:
        if node['version'] == version:
            errata_uri = node.get('metadata', {}).get('url')
            if not errata_uri:
                _LOGGER.debug('{} found in {}, but does not declare metadata.url'.format(version, cincinnati_uri))
                return None
            break
        versions.add(node['version'])
    if not errata_uri:
        _LOGGER.debug('{} not found in {} ({})'.format(version, cincinnati_uri, ', '.join(sorted(versions))))
    return errata_uri


def _public_errata_uri(uri):
    for potential_errata_uri in advisory_phrasings(advisory=uri):
        headers = {
            'User-Agent': 'cincinnati-graph-data/0.1',  # for some reason, https://access.redhat.com/ 403s urllib/{version}
        }
        request = urllib.request.Request(potential_errata_uri, headers=headers)
        while True:
            try:
                with urllib.request.urlopen(request):
                    pass
            except urllib.error.HTTPError as exc:
                if exc.code == http.HTTPStatus.FORBIDDEN or exc.code == http.HTTPStatus.NOT_FOUND:
                    _LOGGER.debug('{}: {}'.format(potential_errata_uri, exc))
                    break
                _LOGGER.error('{}: {}'.format(potential_errata_uri, exc))
                time.sleep(10)
                continue
            except Exception as exc:
                _LOGGER.error('{}: {}'.format(potential_errata_uri, exc))
                time.sleep(10)
                continue
            return potential_errata_uri, True
    return uri, False


def advisory_phrasings(advisory):
    match = _ADVISORY_TYPE_REGEXP.search(advisory)
    if not match:
        _LOGGER.warning('advisory did not match the advisory type regular expression: {}'.format(advisory))
        return
    for phrasing in ['RHBA', 'RHSA']:
        yield '{}{}{}'.format(advisory[:match.start()], phrasing, advisory[match.end():])


def notify(message, webhook=None):
    if not webhook:
        print(message)
        return

    msg_text = '<!subteam^STE7S7ZU2>: Cincinnati stabilization:\n{}'.format(message)

    urllib.request.urlopen(webhook, data=urllib.parse.urlencode({
        'payload': {
            'text': msg_text,
        },
    }).encode('utf-8'))


def promote(version, channel_name, channel_path, subject, body, upstream_github_repo, push_github_repo, github_token, upstream_branch, labels=None):
    if github_token:
        upstream_remote = get_remote(repo=upstream_github_repo)
        subprocess.run(['git', 'fetch', upstream_remote], check=True)
        branch = 'promote-{}-to-{}'.format(version, channel_name)
        try:
            subprocess.run(['git', 'show', branch], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            if 'unknown revision or path not in the working tree' not in exc.stderr:
                raise
        else:
            raise ValueError('branch {} already exists; possibly waiting for an open pull request to merge'.format(branch))
        subprocess.run(['git', 'checkout', '-b', branch, '{}/{}'.format(upstream_remote, upstream_branch)], check=True)

    with open(channel_path) as f:
        try:
            data = yaml.load(f, Loader=yaml.SafeLoader)
        except ValueError as exc:
            raise ValueError('failed to load YAML from {}: {}'.format(channel_path, exc))
    versions = set(data['versions'])
    if version in versions:
        raise ValueError('version {} has already been promoted to {} in upstream branch {}'.format(version, channel_name, upstream_branch))
    versions.add(version)
    data['versions'] = list(sorted(versions, key=semver_sort_key))
    with open(channel_path, 'w') as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    message = '{}\n\n{}\n'.format(subject, textwrap.fill(body, width=76))

    if not github_token:
        pull = PullRequest(html_url='data://no-token-so-no-pull')
        return pull

    if github is None:
        raise github_import_error

    subprocess.run(['git', 'commit', '--file', '-', channel_path], check=True, encoding='utf-8', input=message)
    push_uri_with_token = 'https://{}@github.com/{}.git'.format(github_token, push_github_repo)
    subprocess.run(['git', 'push', '-u', push_uri_with_token, branch], check=True)

    owner = push_github_repo.split('/')[0]

    github_object = github.Github(github_token)
    repo = github_object.get_repo(upstream_github_repo)
    pull = repo.create_pull(title=subject, body=body, head='{}:{}'.format(owner, branch), base=upstream_branch)
    if labels:
        pull.add_to_labels(*labels)
    return pull


def sanitize(err, github_token=None):
    if github_token is None:
        return err
    return str(err).replace(github_token, 'REDACTED')


def semver_sort_key(version):
    # Precedence is defined in https://semver.org/spec/v2.0.0.html#spec-item-11
    identifiers = _SEMANTIC_VERSION_DELIMITERS.sub(' ', version)
    ids = []
    for indx, identifier in enumerate(identifiers.split()):
        if indx < 3:
            try:
                identifier = int(identifier)
            except ValueError:
                pass
        ids.append(identifier)
    return tuple(ids)


def get_remote(repo):
    remote = _REMOTE_CACHE.get(repo)
    if remote is not None:
        return remote

    process = subprocess.run(['git', 'remote', '--verbose'], check=True, capture_output=True, text=True)
    for line in process.stdout.strip().split('\n'):
        match = _GIT_REMOTE_LINE_REGEXP.match(line)
        if not match:
            _LOGGER.info('ignoring unrecognized remote line syntax: {}'.format(line))
            continue
        data = match.groupdict()
        if data['host'] != 'github.com':
            _LOGGER.info('ignoring non-GitHub remote host {}: {}'.format(data['host'], line))
            continue
        line_repo = '{org}/{repo}'.format(**data)
        if line_repo not in _REMOTE_CACHE:
            _REMOTE_CACHE[line_repo] = data['remote']
            _LOGGER.info('caching remote {} for {}'.format(data['remote'], line_repo))

    return _REMOTE_CACHE[repo]


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Check for stabilization changes as versions are promoted from feeder channels.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--poll',
        metavar='SECONDS',
        type=int,
        help='Seconds to wait between stabilization checks.  By default runs a single round of stabilization changes.',
        default=None,
    )
    parser.add_argument(
        '--upstream-github-repo',
        dest='upstream_github_repo',
        metavar='REPO',
        help='Automatically create promotion pull requests in the GitHub repository (requires --github-token).',
        default="openshift/cincinnati-graph-data",
    )
    parser.add_argument(
        '--push-github-repo',
        dest='push_github_repo',
        metavar='REPO',
        help='Automatically create promotion branches in the GitHub repository (requires --github-token and --upstream-github-repo).  Defaults to --upstream-github-repo.',
    )
    parser.add_argument(
        '--github-token',
        dest='github_token',
        metavar='TOKEN',
        help='GitHub token for pull request creation ( https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token ). Defaults to the value of the GITHUB_TOKEN environment variable.',
        default=os.environ.get('GITHUB_TOKEN', ''),
    )
    parser.add_argument(
        '--labels',
        nargs='*',
        help='Set these labels on newly created pull request.  For example: "--labels lgtm approved".',
    )
    parser.add_argument(
        '--webhook',
        metavar='URI',
        help='Set this to actually push notifications to Slack.  Defaults to the value of the WEBHOOK environment variable.',
        default=os.environ.get('WEBHOOK', ''),
    )

    args = parser.parse_args()

    next_notification = datetime.datetime.now()
    while True:
        waiting_notifications = False
        if datetime.datetime.now() > next_notification:
            waiting_notifications = True
            next_notification += datetime.timedelta(hours=24)  # don't flood notifications

        upstream_branch = 'master'
        upstream_github_repo = args.upstream_github_repo.strip()

        if args.poll:
            upstream_remote = get_remote(repo=upstream_github_repo)
            subprocess.run(['git', 'fetch', upstream_remote], check=True)
            subprocess.run(['git', 'checkout', '{}/{}'.format(upstream_remote, upstream_branch)], check=True)
        stabilization_changes(
            directories={'channels', 'internal-channels'},
            upstream_github_repo=upstream_github_repo,
            push_github_repo=(args.push_github_repo or upstream_github_repo).strip(),
            github_token=args.github_token.strip() or None,
            labels=args.labels,
            webhook=args.webhook.strip(),
            waiting_notifications=waiting_notifications,
            upstream_branch=upstream_branch,
        )
        if args.poll:
            _LOGGER.info('sleeping {} seconds before reconsidering promotions'.format(args.poll))
            time.sleep(args.poll)
        else:
            break


if __name__ == '__main__':
    main()
