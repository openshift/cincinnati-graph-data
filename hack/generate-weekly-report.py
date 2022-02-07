#!/usr/bin/env python3

import codecs
import datetime
import re
import ssl
import subprocess
import urllib.request

import util


ORG_REPO = 'openshift/cincinnati-graph-data'

# https://semver.org/spec/v2.0.0.html#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
SEMVER_REGEXP = re.compile('^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')

TABLE_DATA_REGEXP = re.compile('.*<td [^>]*>(<a [^>]*>)?(?P<data>[^<]*)(</a>)?</td>.*')


def write_report(initial_commit, final_commit=None, stats_uri=None):
    print('Title: Over The Air Update Report - {}'.format(datetime.date.today().strftime('%B %d, %Y')))
    print()
    write_graph_data_changes(initial_commit=initial_commit, final_commit=final_commit)
    if stats_uri:
        print()
        write_update_statistics(uri=stats_uri)
    print()
    write_update_blockers()


def write_graph_data_changes(initial_commit, final_commit=None):
    initial_commit = get_commit(reference=initial_commit)
    final_commit = get_commit(reference=final_commit)
    print('<h1><a href="https://github.com/{org_repo}/compare/{initial_commit}...{final_commit}">Graph-data changes</a> (through <a href="https:///github.com/{org_repo}/commit/{final_commit}">{final_commit_prefix}</a>)</h1>'.format(org_repo=ORG_REPO, initial_commit=initial_commit, final_commit=final_commit, final_commit_prefix=final_commit[:10]))
    print()
    print('<ul>')
    already_mentioned = set()
    for channel_name, data in sorted(get_version_agnostic_changes(initial_commit=initial_commit, final_commit=final_commit).items(), key=lambda name_and_data: -name_and_data[1]['rank']):
        additions = data['additions'] - already_mentioned
        if additions:
            print('  <li>{} additions: {}'.format(channel_name, ', '.join(sorted(additions, key=semver_sort_key))))
        else:
            print('  <li>no releases specific to {}</li>'.format(channel_name))
        already_mentioned.update(data['additions'])
    print('</ul>')
    # TODO: probably worth reporting on any blocked-edges/ changes as well.


def write_update_statistics(uri, total_updates_threshold=20):
    print('<h1><a href="{}">Update status</a> of recent releases (for last week)</h1>'.format(uri))

    print('<dl>')
    for column_name, definition in [
            ('slow', 'The cluster update took 8 or more hours.  It may have subsequently completed, or it may still be stuck, or the cluster may have stopped reporting.'),
            ('gone', 'The cluster stopped reporting Telemetry before completing the update (while it was <code>Progressing=True</code>) or being classified as <em>slow</em>.'),
            ('progress', 'The cluster update is still progressing, and it has not yet been long enough to count as <em>slow</em>.'),
            ('success', 'The cluster update completed quickly enough to avoid being classified as <em>slow</em>.'),
            ]:
        print('  <dt>{}</dt>'.format(column_name))
        print('  <dd>{}</dd>'.format(definition))
    print('</dl>')

    # avoid: certificate verify failed: self signed certificate in certificate chain
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(uri, context=context) as f:
        # pull out the first table from the stats report, selecting rows where the final column (total updates) meets the configured threshold
        in_table = False
        in_body = False
        in_body_row = False
        body_row_data = []
        excluded_rows = False
        for line in codecs.getreader('utf-8')(f):
            if in_table:
                if '<tbody>' in line:
                    in_body = True
                if in_body and '<tr>' in line:
                    in_body_row = True
                    continue
                if in_body_row and '<td ' in line:
                    match = TABLE_DATA_REGEXP.match(line)
                    if not match:
                        raise ValueError('unable to match {!r} to table data regular expression'.format(line))
                    body_row_data.append(match.group('data'))
                    continue
                if in_body_row and '</tr>' in line:
                    if int(body_row_data[-1]) >= total_updates_threshold:
                        print('<tr>')
                        for data in body_row_data:
                            print('  <td>{}</td>'.format(data))
                        print('</tr>')
                        body_row_data = []
                    else:
                        excluded_rows = True
                    in_body_row = False
                    continue
                if '</tbody>' in line:
                    print('<tr><td>More targets with &lt;{} total attempts.</td></tr>'.format(total_updates_threshold))
                print(line.replace('failed', 'slow').replace('gone[progress]', 'gone').rstrip())
                if '</table>' in line:
                    return
            elif '<table' in line:
                in_table = True
                print(line.rstrip())


def write_update_blockers():
    print('<h1><a href="https://github.com/openshift/enhancements/tree/master/enhancements/update/update-blocker-lifecycle#summary">Upgrade-blocker Bugs</a></h1>')
    print()
    print('<p>FIXME: discuss any bugs in the queues linked from the enhancement summary.</p>')


def get_commit(reference=None):
    if not reference:
        reference = 'HEAD'
    process = subprocess.run(['git', 'rev-parse', reference], capture_output=True, text=True, check=True)
    return process.stdout.strip()


def get_version_agnostic_changes(initial_commit, final_commit):
    initial_channels, _ = util.load_channels(revision=initial_commit)
    final_channels, _ = util.load_channels(revision=final_commit)
    version_agnostic_channels = {}
    for channel_name, final_channel_data in final_channels.items():
        if '-4.' in channel_name:
            continue
        initial_set = set(initial_channels.get(channel_name, {}).get('versions', []))
        final_set = set(final_channel_data.get('versions', []))
        version_agnostic_channels[channel_name] = {
            'additions': final_set - initial_set,
        }
        if 'feeder' in final_channel_data:
            version_agnostic_channels[channel_name]['feeder'] = final_channel_data['feeder']
        else:
            version_agnostic_channels[channel_name]['rank'] = 1

    for i in range(10):
        unranked_remain = False
        for channel_name, data in version_agnostic_channels.items():
            if not data.get('rank'):
                feeder = data['feeder']['name']
                if feeder not in version_agnostic_channels:
                    raise ValueError('{} declares feeder channel {!r}, but that is not a recognized version-agnostic channel.'.format(channel_name, feeder))
                feeder_rank = version_agnostic_channels[feeder].get('rank')
                if feeder_rank:
                    data['rank'] = feeder_rank + 1
                else:
                    unranked_remain = True
        if i == 9 and unranked_remain:
            raise ValueError('unable to rank some channels: {}'.format(', '.join(channel_name for channel_name, data in sorted(version_agnostic_channels.items()) if not data.get('rank'))))

    return version_agnostic_channels


def semver_sort_key(version):
    match = SEMVER_REGEXP.match(version)
    if not match:
        raise ValueError('unable to match {!r} to the SemVer regular expression'.format(version))
    data = match.groupdict()
    return (int(data['major']), int(data['minor']), int(data['patch']), version)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Display edges for a particular channel and commit.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        'initial_commit',
        metavar='INITIAL_COMMIT',
        help='Commit hash used for the previous report, for calculating the change through the current HEAD commit.',
    )
    parser.add_argument(
        '--final-commit',
        metavar='REF',
        default='HEAD',
        help='Git reference for the final commit.',
    )
    parser.add_argument(
        '--stats',
        dest='stats_uri',
        metavar='URI',
        help='URI for the update statistics report.',
    )

    args = parser.parse_args()

    write_report(initial_commit=args.initial_commit, final_commit=args.final_commit, stats_uri=args.stats_uri)
