#!/usr/bin/env python

import datetime
import logging
import os
import re
import subprocess

import yaml


logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)
_ISO_8601_DELAY_REGEXP = re.compile('^PT(?P<hours>\d+)H$')
_GIT_BLAME_COMMIT_REGEXP = re.compile('^(?P<hash>[0-9a-f]{40}) .*')
_GIT_BLAME_HEADER_REGEXP = re.compile('^(?P<key>[^ \t]+) (?P<value>.*)$')
_GIT_BLAME_LINE_REGEXP = re.compile('^\t(?P<value>.*)$')


def parse_iso8601_delay(delay):
    # https://tools.ietf.org/html/rfc3339#page-13
    match = _ISO_8601_DELAY_REGEXP.match(delay)
    if not match:
        raise ValueError('invalid or unsupported ISO 8601 duration {!r}.  Tooling currently only supports PT<number>H for hour offsets')
    hours = int(match.group('hours'))
    return datetime.timedelta(hours=hours)


def stabilization_changes(directory):
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
    for name, channel in sorted(channels.items()):
        if not channel.get('feeder'):
            continue
        feeder = channel['feeder']['name']
        delay_string = channel['feeder']['delay']
        delay = parse_iso8601_delay(delay=delay_string)
        version_filter = re.compile('^{}$'.format(channel['feeder'].get('filter', '.*')))
        feeder_data = channels[feeder]
        unpromoted = set(feeder_data['versions']) - set(channel['versions'])
        candidates = set(v for v in unpromoted if version_filter.match(v))
        if not candidates:
            continue
        promotions = get_promotions(paths[feeder])
        now = datetime.datetime.now()
        _LOGGER.info('considering promotions from {} to {} after {}'.format(feeder, name, delay_string))
        for version in sorted(candidates):
            promotion = promotions[version]
            version_delay = now - promotion['committer-time']
            if version_delay > delay:
                _LOGGER.info('  recommended: {} ({})'.format(version, version_delay))
                _LOGGER.debug('    {}: Promote {} to {}'.format(paths[name].rsplit('.', 1)[0], version, name))
                _LOGGER.debug('    It was promoted the feeder {} by {} ({}, {}).'.format(feeder, promotion['hash'][:10], promotion['summary'], promotion['committer-time'].date().isoformat()))
            else:
                _LOGGER.info('  waiting: {} ({})'.format(version, version_delay))


def get_promotions(path):
    # https://git-scm.com/docs/git-blame#_the_porcelain_format
    output = subprocess.check_output(['git', 'blame', '--first-parent', '--porcelain', path]).decode('utf-8')
    commits = {}
    lines = {}
    for line in output.strip().split('\n'):
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


if __name__ == '__main__':
    stabilization_changes(directory='channels')
