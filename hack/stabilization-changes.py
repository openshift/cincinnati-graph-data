#!/usr/bin/env python

import codecs
import datetime
import http
import json
import logging
import os
import re
import subprocess
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

import github
import yaml


logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)
_ADVISORY_TYPE_REGEXP = re.compile(r'RH[BS]A')
_ISO_8601_DELAY_REGEXP = re.compile(r'^P((?P<weeks>\d+)W)?(T(?P<hours>\d+)H)?$')
_GIT_BLAME_COMMIT_REGEXP = re.compile(r'^(?P<hash>[0-9a-f]{40}) .*')
_GIT_BLAME_HEADER_REGEXP = re.compile(r'^(?P<key>[^ \t]+) (?P<value>.*)$')
_GIT_BLAME_LINE_REGEXP = re.compile(r'^\t(?P<value>.*)$')
_SEMANTIC_VERSION_DELIMITERS = re.compile('[.+-]')


def parse_iso8601_delay(delay):
    # https://tools.ietf.org/html/rfc3339#page-13
    match = _ISO_8601_DELAY_REGEXP.match(delay)
    if not match:
        raise ValueError('invalid or unsupported ISO 8601 duration {!r}.  Tooling currently only supports P<number>WT<number>H for week and/or hour offsets')
    weeks = int(match.group('weeks') or 0)
    hours = int(match.group('hours') or 0)
    return datetime.timedelta(days=7*weeks, hours=hours)


def stabilization_changes(directory, webhook=None, **kwargs):
    channels, channel_paths = load_channels(directory=directory)
    cache = {}
    notifications = []
    for name, channel in sorted(channels.items()):
        notifications.extend(stabilize_channel(name=name, channel=channel, channels=channels, channel_paths=channel_paths, cache=cache, **kwargs))
    if notifications:
        notify(message='* ' + ('\n* '.join(notifications)), webhook=webhook)


def stabilize_channel(name, channel, channels, channel_paths, **kwargs):
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
    unpromoted = set(feeder_data['versions']) - set(channel['versions']) - set(feeder_data.get('tombstones', {}))
    candidates = set(v for v in unpromoted if version_filter.match(v))
    if not candidates:
        return
    feeder_promotions = get_promotions(channel_paths[feeder])
    _LOGGER.info('considering promotions from {} to {} after {}'.format(feeder, name, ' or '.join(conditions)))
    for version in sorted(candidates):
        feeder_promotion = feeder_promotions[version]
        yield from stabilize_release(
            version=version,
            channel_name=name,
            channel_path=channel_paths[name],
            delay=delay,
            errata=errata,
            feeder_name=feeder,
            feeder_promotion=feeder_promotion,
            **kwargs)


def stabilize_release(version, channel_name, channel_path, delay, errata, feeder_name, feeder_promotion, cache, waiting_notifications=True, **kwargs):
    now = datetime.datetime.now()
    version_delay = now - feeder_promotion['committer-time']
    errata_public = False
    public_errata_message = ''
    if errata:
        errata_uri, errata_public = public_errata_uri(version=version, channel=feeder_name, cache=cache)
        if errata_uri:
            public_errata_message = ' {} is{} public.'.format(errata_uri, '' if errata_public else ' not')
    if (delay is not None and version_delay > delay) or errata_public:
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
                channel_name=channel_name,
                channel_path=channel_path,
                subject=subject,
                body=body,
                **kwargs)
        except Exception as error:
            _LOGGER.error('  failed to promote {} to {}: {}'.format(version, channel_name, error))
            yield 'FAILED {}. {} {}'.format(subject, body, error)
        else:
            yield '{}. {} {}'.format(subject, body, pull.html_url)
    else:
        _LOGGER.info('  waiting: {} ({}){}'.format(version, version_delay, public_errata_message))
        if waiting_notifications:
            yield 'Recommend waiting to promote {} to {}; it was promoted the feeder {} by {} ({}, {}, {}){}'.format(
                version,
                channel_name,
                feeder_name,
                feeder_promotion['hash'][:10],
                feeder_promotion['summary'],
                feeder_promotion['committer-time'].date().isoformat(),
                version_delay,
                public_errata_message)


def load_channels(directory):
    channels = {}
    paths = {}
    for root, _, files in os.walk(directory):
        for filename in files:
            if not filename.endswith('.yaml'):
                continue
            path = os.path.join(root, filename)
            with open(path) as f:
                try:
                    data = yaml.load(f, Loader=yaml.SafeLoader)
                except ValueError as error:
                    raise ValueError('failed to load YAML from {}: {}'.format(path, error))
            channel = data['name']
            if channel in channels:
                raise ValueError('multiple definitions for {}: {} and {}'.format(channel, paths[channel], path))
            paths[channel] = path
            channels[channel] = data
    return channels, paths


def get_promotions(path):
    # https://git-scm.com/docs/git-blame#_the_porcelain_format
    process = subprocess.run(['git', 'blame', '--first-parent', '--porcelain', path], check=True, capture_output=True)
    commits = {}
    lines = {}
    for line in process.stdout.decode('utf-8').strip().split('\n'):
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
            raise ValueError('unrecognized blame output for {} (blame line {}): {}'.format(path, i, line))
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
        except Exception as error:
            _LOGGER.error('{}: {}'.format(uri, error))
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
            except urllib.error.HTTPError as error:
                if error.code == http.HTTPStatus.FORBIDDEN or error.code == http.HTTPStatus.NOT_FOUND:
                    _LOGGER.debug('{}: {}'.format(potential_errata_uri, error))
                    break
                _LOGGER.error('{}: {}'.format(potential_errata_uri, error))
                time.sleep(10)
                continue
            except Exception as error:
                _LOGGER.error('{}: {}'.format(potential_errata_uri, error))
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


def promote(version, channel_name, channel_path, subject, body, github_repo, github_token, upstream_remote='origin', upstream_branch='master'):
    if not github_token:
        raise ValueError('cannot promote without a configured GitHub token')
    subprocess.run(['git', 'fetch', upstream_remote], check=True)
    branch = 'promote-{}-to-{}'.format(version, channel_name)
    subprocess.run(['git', 'checkout', '-b', branch, '{}/{}'.format(upstream_remote, upstream_branch)], check=True)
    with open(channel_path) as f:
        try:
            data = yaml.load(f, Loader=yaml.SafeLoader)
        except ValueError as error:
            raise ValueError('failed to load YAML from {}: {}'.format(channel_path, error))
    versions = set(data['versions'])
    if version in versions:
        raise ValueError('version {} has already been promoted to {} in {}/{}'.format(version, channel_name, upstream_remote, upstream_branch))
    versions.add(version)
    data['versions'] = list(sorted(versions, key=semver_sort_key))
    with open(channel_path, 'w') as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    message = '{}\n\n{}\n'.format(subject, textwrap.fill(body, width=76))
    subprocess.run(['git', 'commit', '--file', '-', channel_path], check=True, encoding='utf-8', input=message)
    subprocess.run(['git', 'push', '-u', upstream_remote, branch], check=True)

    github_object = github.Github(github_token)
    repo = github_object.get_repo(github_repo)
    pull = repo.create_pull(title=subject, body=body, head=branch, base=upstream_branch)
    pull.add_to_labels('lgtm', 'approved')
    return pull


def semver_sort_key(version):
    # Precedence is defined in https://semver.org/spec/v2.0.0.html#spec-item-11
    identifiers = _SEMANTIC_VERSION_DELIMITERS.sub(' ', version)
    ids = []
    for identifier in identifiers.split():
        try:
            i = int(identifier)
        except ValueError:
            ids.append(identifier)
        else:
            ids.append(i)
    return tuple(ids)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Check for stabilization changes as versions are promoted from feeder channels.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--github-repo',
        dest='github_repo',
        metavar='REPO',
        help='Automatically create promotion pull requests in the GitHub repository (requires --github-token).',
        default="openshift/cincinnati-graph-data",
    )
    parser.add_argument(
        '--github-token',
        dest='github_token',
        metavar='TOKEN',
        help='GitHub token for pull request creation ( https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token ). Defaults to the value of the GITHUB_TOKEN environment variable.',
        default=os.environ.get('GITHUB_TOKEN', ''),
    )
    parser.add_argument(
        '--webhook',
        metavar='URI',
        help='Set this to actually push notifications to Slack.  Defaults to the value of the WEBHOOK environment variable.',
        default=os.environ.get('WEBHOOK', ''),
    )

    args = parser.parse_args()

    stabilization_changes(
        directory='channels',
        github_repo=args.github_repo.strip(),
        github_token=args.github_token.strip(),
        webhook=args.webhook.strip(),
        waiting_notifications=True,
    )
