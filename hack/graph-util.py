#!/usr/bin/env python

import argparse
import codecs
import functools
import io
import json
import logging
import multiprocessing
import os
import re
import tarfile

import yaml

try:
    from builtins import FileExistsError  # Python 3
except ImportError:
    FileExistsError = OSError  # sloppy hack for Python 2

try:
    from urllib.request import Request, urlopen  # Python 3
except ImportError:
    from urllib2 import Request, urlopen  # Python 2


_VERSION_REGEXP = re.compile('^(?P<major>[0-9]*)\.(?P<minor>[0-9]*)(?P<suffix>[^0-9].*)$')
logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)


def load_nodes(directory, registry, repository):
    try:
        os.mkdir(directory)  # os.makedirs' exist_ok is new in Python 3.2
    except FileExistsError:
        pass

    nodes = {}

    repository_uri = 'https://{}/api/v1/repository/{}'.format(registry, repository)
    page = 1
    while True:
        f = urlopen('{}/tag/?page={}'.format(repository_uri, page))
        data = json.load(codecs.getreader('utf-8')(f))
        f.close()  # no context manager with-statement because in Python 2: AttributeError: addinfourl instance has no attribute '__exit__'

        for entry in data['tags']:
            if 'expiration' in entry:
                continue

            algo, hash = entry['manifest_digest'].split(':', 1)
            pullspec = 'quay.io/{}@{}:{}'.format(repository, algo, hash)
            node = {'payload': pullspec}
            path = os.path.join(directory, algo, hash)
            try:
                with open(path) as f:
                    try:
                        meta = yaml.load(f, Loader=yaml.SafeLoader)
                    except ValueError as error:
                        raise ValueError('failed to load YAML from {}: {}'.format(path, error))
                    if not meta:
                        continue
                _LOGGER.debug('loaded from cache: {} {}'.format(meta['version'], node['payload']))
            except IOError:
                try:
                    meta = get_release_metadata(node=node)
                except KeyError as error:
                    _LOGGER.warning('unable to get release metadata for {} {} : {}'.format(pullspec, entry, error))
                    meta = {}
                try:
                    os.mkdir(os.path.join(directory, algo))  # os.makedirs' exist_ok is new in Python 3.2
                except FileExistsError:
                    pass
                try:
                    with open(path, 'w') as f:
                        yaml.safe_dump(meta, f, default_flow_style=False)
                except:
                    os.remove(path)
                    raise
                if not meta:
                    _LOGGER.debug('caching empty metadata for {} {}'.format(entry['name'], node['payload']))
                    continue
                _LOGGER.debug('caching metadata for {} {}'.format(meta['version'], node['payload']))
            node['version'] = meta['version']
            if meta.get('previous'):
                node['previous'] = set(meta['previous'])
            if meta.get('next'):
                node['next'] = set(meta['next'])
            node = normalize_node(node=node)
            nodes[node['version']] = node

        if data['has_additional']:
            page += 1
            continue

        break

    return nodes


def load_channels(directory, nodes):
    for node in nodes.values():
        node['channels'] = set()

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
                for version in data['versions']:
                    try:
                        node = nodes[version]
                    except KeyError:
                        raise ValueError('{} claims version {}, but no nodes found with that version'.format(path, version))
                    node['channels'].add(channel)

    for node in nodes.values():
        if 'metadata' not in node:
            node['metadata'] = {}
        # sort first by prerelease/stable/fast/candidate
        channels = sorted(node['channels'])
        # then sort by version, 4.1, 4.2, etc
        channels = sorted(channels, key=lambda x: x.split('-', 1)[-1])
        node['metadata']['io.openshift.upgrades.graph.release.channels'] = ','.join(channels)
    return nodes


def block_edges(directory, nodes):
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
                try:
                    to_node = nodes[data['to']]
                except KeyError:
                    raise ValueError('{} claims version {}, but no nodes found with that version'.format(path, data['to']))
                try:
                    from_regexp = re.compile(data['from'])
                except ValueError as error:
                    raise ValueError('{} invalid from regexp: {}'.format(path, data['from']))
                if to_node.get('previous'):
                    to_node['previous'] = {version for version in to_node['previous'] if not from_regexp.match(version)}
    return nodes


def normalize_node(node):
    match = _VERSION_REGEXP.match(node['version'])
    if not match:
        raise ValueError('invalid node version: {!r}'.format(node['version']))
    return node


def push(directory, token, push_versions):
    nodes = load_nodes(directory=os.path.join(directory, '.nodes'), registry='quay.io', repository='openshift-release-dev/ocp-release')
    nodes = load_channels(directory=os.path.join(directory, 'channels'), nodes=nodes)
    nodes = block_edges(directory=os.path.join(directory, 'blocked-edges'), nodes=nodes)

    sync_nodes = [
        node for version, node in sorted(nodes.items())
        if not push_versions or version in push_versions.split(',')
    ]

    sync = functools.partial(sync_node, token=token)
    pool = multiprocessing.Pool(processes=16)
    pool.map(sync, sync_nodes)
    pool.close()  # no context manager with-statement because in Python 2: AttributeError: '__exit__'


def update_channels(node, token):
    labels = get_labels(node=node)
    channel_label = labels.get('io.openshift.upgrades.graph.release.channels', {})
    channels = channel_label.get('value', '')

    _LOGGER.debug('syncing node={} channels={}'.format(node['version'], channels))

    if channels and channels != node['metadata']['io.openshift.upgrades.graph.release.channels']:
        if set(channels.split(',')) == node['channels']:
            _LOGGER.info('label sort for {}: {} -> {}'.format(node['version'], channels, node['metadata']['io.openshift.upgrades.graph.release.channels']))
            return
        else:
            _LOGGER.info('label mismatch for {}: {} != {}'.format(node['version'], channels, node['metadata']['io.openshift.upgrades.graph.release.channels']))
        delete_label(
            node=node,
            label=channel_label['id'],
            key=channel_label['key'],
            token=token)
    if node['metadata']['io.openshift.upgrades.graph.release.channels'] and channels != node['metadata']['io.openshift.upgrades.graph.release.channels']:
        if not channels:
            _LOGGER.info('adding {} to channels: {}'.format(node['version'], node['metadata']['io.openshift.upgrades.graph.release.channels']))
        post_label(
            node=node,
            label={
                'media_type': 'text/plain',
                'key': 'io.openshift.upgrades.graph.release.channels',
                'value': node['metadata']['io.openshift.upgrades.graph.release.channels'],
            },
            token=token)

def update_previous(node, token):
    labels = get_labels(node=node)
    if node.get('previous', set()):
        meta = get_release_metadata(node=node)
        previous = set(meta.get('previous', set()))
        want_removed = previous - node['previous']
        removed_label = labels.get('io.openshift.upgrades.graph.previous.remove', {})
        current_removed = set(version for version in removed_label.get('value', '').split(',') if version)
        if current_removed != want_removed:
            _LOGGER.info('changing {} previous.remove from {} to {}'.format(node['version'], sorted(current_removed), sorted(want_removed)))
            if 'io.openshift.upgrades.graph.previous.remove' in labels:
                delete_label(node=node, label=removed_label['id'], key=removed_label['key'], token=token)
            if want_removed:
                post_label(
                    node=node,
                    label={
                        'media_type': 'text/plain',
                        'key': 'io.openshift.upgrades.graph.previous.remove',
                        'value': ','.join(sorted(want_removed)),
                    },
                    token=token)
    else:
        removed_label = labels.get('io.openshift.upgrades.graph.previous.remove', {})
        previous_remove = removed_label.get('value', '')
        if previous_remove != '*':
            meta = get_release_metadata(node=node)
            if meta.get('previous', set()):
                _LOGGER.info('replacing {} previous remove {!r} with *'.format(node['version'], previous_remove))
                if 'id' in removed_label:
                    delete_label(node=node, label=removed_label['id'], key=removed_label['key'], token=token)
                post_label(
                    node=node,
                    label={
                        'media_type': 'text/plain',
                        'key': 'io.openshift.upgrades.graph.previous.remove',
                        'value': '*',
                    },
                    token=token)

def sync_node(node, token):
    update_channels(node, token)
    update_previous(node, token)

    labels = get_labels(node=node)
    for key in ['next.add', 'next.remove']:
        label = 'io.openshift.upgrades.graph.{}'.format(key)
        if label in labels:
            _LOGGER.warning('the {} label is deprecated for {}.  Use the previous label on the other release(s) instead (was: {})'.format(label, node['version'], labels[label].get('value', '')))
            #delete_label(node=node, label=labels[label]['id'], key=label, token=token)

def repository_uri(name, pullspec=None):
    if not pullspec:
        pullspec = name
    prefix = 'quay.io/'
    if not name.startswith(prefix):
        raise ValueError('non-Quay pullspec: {}'.format(pullspec))
    name = name[len(prefix):]
    return 'https://quay.io/api/v1/repository/{}'.format(name)


def manifest_uri(node):
    pullspec = node['payload']
    name, digest = pullspec.split('@', 1)
    return '{}/manifest/{}'.format(repository_uri(name=name, pullspec=pullspec), digest)


def get_labels(node):
    f = urlopen('{}/labels'.format(manifest_uri(node=node)))
    data = json.load(codecs.getreader('utf-8')(f))
    f.close()  # no context manager with-statement because in Python 2: AttributeError: addinfourl instance has no attribute '__exit__'
    return {label['key']: label for label in data['labels']}


def delete_label(node, label, token, key=None):
    uri = '{}/labels/{}'.format(manifest_uri(node=node), label)
    suffix = ''
    if key:
        suffix = ' (key: {})'.format(key)
    _LOGGER.info('{} {} {}{}'.format(node['version'], 'delete', uri, suffix))
    if not token:
        return  # dry run
    request = Request(uri)
    request.add_header('Authorization', 'Bearer {}'.format(token))
    request.get_method = lambda: 'DELETE'
    return urlopen(request)


def post_label(node, label, token):
    uri = '{}/labels'.format(manifest_uri(node=node))
    _LOGGER.info('{} {} {}'.format(node['version'], 'post', uri))
    if not token:
        return  # dry run
    request = Request(uri, json.dumps(label).encode('utf-8'))
    request.add_header('Authorization', 'Bearer {}'.format(token))
    request.add_header('Content-Type', 'application/json')
    return urlopen(request)


def get_release_metadata(node):
    f = urlopen(manifest_uri(node=node))
    data = json.load(codecs.getreader('utf-8')(f))
    f.close()  # no with-statement because in Python 2: AttributeError: addinfourl instance has no attribute '__exit__'
    for layer in reversed(data['layers']):
        digest = layer['blob_digest']
        pullspec = node['payload']
        name = pullspec.split('@', 1)[0]
        prefix = 'quay.io/'
        if not name.startswith(prefix):
            raise ValueError('non-Quay pullspec: {}'.format(pullspec))
        name = name[len(prefix):]
        uri = 'https://quay.io/v2/{}/blobs/{}'.format(name, digest)
        f = urlopen(uri)
        layer_bytes = f.read()
        f.close()

        with tarfile.open(fileobj=io.BytesIO(layer_bytes), mode='r:gz') as tar:
            f = tar.extractfile('release-manifests/release-metadata')
            return json.load(codecs.getreader('utf-8')(f))
            # TODO: assert meta.get('kind') == 'cincinnati-metadata-v0'
    raise ValueError('no release-metadata in {} layers'.format(node['version']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Utilities for managing graph data.')
    subparsers = parser.add_subparsers()

    push_to_quay_parser = subparsers.add_parser(
        'push-to-quay',
        help='Push graph metadata to Quay.io labels.',
    )
    push_to_quay_parser.add_argument(
        '-t', '--token',
        help='Quay token ( https://docs.quay.io/api/#applications-and-tokens )',
    )
    push_to_quay_parser.add_argument(
        '--versions',
        help='Comma Seperated Versions to sync',
    )
    push_to_quay_parser.set_defaults(action='push-to-quay')

    args = parser.parse_args()

    if args.action == 'push-to-quay':
        push(directory='.', token=args.token, push_versions=args.versions)
