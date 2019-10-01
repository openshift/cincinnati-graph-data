#!/usr/bin/env python

import argparse
import codecs
import collections
import io
import json
import os
import re
import tarfile


try:
    from builtins import FileExistsError  # Python 3
except ImportError:
    FileExistsError = OSError  # sloppy hack for Python 2

try:
    from urllib.request import Request, urlopen  # Python 3
except ImportError:
    from urllib2 import Request, urlopen  # Python 2


_VERSION_REGEXP = re.compile('^(?P<major>[0-9]*)\.(?P<minor>[0-9]*)(?P<suffix>[^0-9].*)$')

def load_edges(directory, nodes):
    edges = {}
    for root, _, files in os.walk(directory):
        for filename in files:
            if not filename.endswith('.json'):
                continue
            path = os.path.join(root, filename)
            with open(path) as f:
                try:
                    edge = json.load(f)
                except ValueError as e:
                    raise ValueError('failed to load JSON from {}: {}'.format(path, e))
            edge_key = (edge['from'], edge['to'])
            if edge_key in edges:
                raise ValueError('duplicate edges for {} (Quay labels do not support channel granularity)')
            edges[edge_key] = edge
            from_node = nodes[edge['from']]
            to_node = nodes[edge['to']]
            node_channels = set(from_node['channels']).intersection(to_node['channels'])
            if set(edge['channels']) != node_channels:
                raise ValueError('edge channels {} differ from node channels {} (Quay labels do not support channel granularity)'.format(sorted(edge['channels']), sorted(node_channels)))
            if 'previous' in to_node:
                to_node['previous'].add(edge['from'])
            else:
                to_node['previous'] = {edge['from']}
    return nodes


def load_nodes(directory):
    nodes = {}
    for root, _, files in os.walk(directory):
        channel = os.path.basename(root)
        for filename in files:
            if not filename.endswith('.json'):
                continue
            path = os.path.join(root, filename)
            with open(path) as f:
                try:
                    node = json.load(f)
                except ValueError as e:
                    raise ValueError('failed to load JSON from {}: {}'.format(path, e))
            previous_node = nodes.get(node['version'])
            if previous_node:
               previous_node['channels'].add(channel)
               continue
            node = normalize_node(node=node)
            node['channels'] = {channel}
            nodes[node['version']] = node
    for node in nodes.values():
        if 'metadata' not in node:
            node['metadata'] = {}
        node['metadata']['io.openshift.upgrades.graph.release.channels'] = ','.join(sorted(node['channels']))
    return nodes


def normalize_node(node):
    match = _VERSION_REGEXP.match(node['version'])
    if not match:
        raise ValueError('invalid node version: {!r}'.format(node['version']))
    return node


def push(directory, token):
    nodes = load_nodes(directory=os.path.join(directory, 'channels'))
    nodes = load_edges(directory=os.path.join(directory, 'edges'), nodes=nodes)
    for node in nodes.values():
        sync_node(node=node, token=token)


def sync_node(node, token):
    labels = get_labels(node=node)

    channels = labels.get('io.openshift.upgrades.graph.release.channels', {}).get('value', '')
    if channels and channels != node['metadata']['io.openshift.upgrades.graph.release.channels']:
        print('label mismatch for {}: {} != {}'.format(node['version'], channels, node['metadata']['io.openshift.upgrades.graph.release.channels']))
        delete_label(
            node=node,
            label='io.openshift.upgrades.graph.release.channels',
            token=token)
        channels = None
    if not channels:
        post_label(
            node=node,
            label={
                'media_type': 'text/plain',
                'key': 'io.openshift.upgrades.graph.release.channels',
                'value': node['metadata']['io.openshift.upgrades.graph.release.channels'],
            },
            token=token)

    for key in ['next.add', 'next.remove']:
        label = 'io.openshift.upgrades.graph.{}'.format(key)
        if label in labels:
            delete_label(node=node, label=label, token=token)

    if node.get('previous', set()):
        meta = get_release_metadata(node=node)
        previous = set(meta.get('previous', set()))
        want_removed = previous - node['previous']
        current_removed = set(version for version in labels.get('io.openshift.upgrades.graph.previous.remove', {}).get('value', '').split(',') if version)
        if current_removed != want_removed:
            print('changing {} previous.remove from {} to {}'.format(node['version'], sorted(current_removed), sorted(want_removed)))
            if 'io.openshift.upgrades.graph.previous.remove' in labels:
                delete_label(node=node, label='io.openshift.upgrades.graph.previous.remove', token=token)
            if want_removed:
                post_label(
                    node=node,
                    label={
                        'media_type': 'text/plain',
                        'key': 'io.openshift.upgrades.graph.previous.remove',
                        'value': ','.join(sorted(want_removed)),
                    },
                    token=token)
        want_added = node['previous'] - previous
        current_added = set(version for version in labels.get('io.openshift.upgrades.graph.previous.add', {}).get('value', '').split(',') if version)
        if current_added != want_added:
            print('changing {} previous.add from {} to {}'.format(node['version'], sorted(current_added), sorted(want_added)))
            if 'io.openshift.upgrades.graph.previous.add' in labels:
                delete_label(node=node, label='io.openshift.upgrades.graph.previous.add', token=token)
            if want_added:
                post_label(
                    node=node,
                    label={
                        'media_type': 'text/plain',
                        'key': 'io.openshift.upgrades.graph.previous.add',
                        'value': ','.join(sorted(want_added)),
                    },
                    token=token)
    else:
        if 'io.openshift.upgrades.graph.previous.add' in labels:
            print('{} had previous additions, but we want no incoming edges'.format(node['version']))
            delete_label(node=node, label='io.openshift.upgrades.graph.previous.add', token=token)
        previous_remove = labels.get('io.openshift.upgrades.graph.previous.remove', {}).get('value', '')
        if previous_remove != '*':
            meta = get_release_metadata(node=node)
            if meta.get('previous', set()):
                print('replacing {} previous remove {!r} with *'.format(node['version'], previous_remove))
                if 'io.openshift.upgrades.graph.previous.remove' in labels:
                    delete_label(node=node, label='io.openshift.upgrades.graph.previous.remove', token=token)
                post_label(
                    node=node,
                    label={
                        'media_type': 'text/plain',
                        'key': 'io.openshift.upgrades.graph.previous.remove',
                        'value': '*',
                    },
                    token=token)


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


def delete_label(node, label, token):
    uri = '{}/labels/{}'.format(manifest_uri(node=node), label)
    print('{} {} {}'.format(node['version'], 'delete', uri))
    if not token:
        return  # dry run
    request = Request(uri)
    request.add_header('Authorization', 'Bearer {}'.format(token))
    request.get_method = lambda: 'DELETE'
    return urlopen(request)


def post_label(node, label, token):
    uri = '{}/labels'.format(manifest_uri(node=node))
    print('{} {} {}'.format(node['version'], 'post', uri))
    if not token:
        return  # dry run
    request = Request(uri, json.dumps(label).encode('utf-8'))
    request.add_header('Authorization', 'Bearer {}'.format(token))
    request.add_header('Content-Type', 'application/json')
    return urlopen(request)


def get_by_digest_pullspec(pullspec):
    if '@' in pullspec:
        return pullspec, None
    name, tag = pullspec.split(':', 1)
    repo_uri = repository_uri(name=name, pullspec=pullspec)
    page = 0
    while True:
        f = urlopen('{}/tag/?page={}'.format(repo_uri, page))
        data = json.load(codecs.getreader('utf-8')(f))
        f.close()  # no context manager with-statement because in Python 2: AttributeError: addinfourl instance has no attribute '__exit__'

        for entry in data['tags']:
            if entry['name'] == tag:
                return '{}@{}'.format(name, entry['manifest_digest']), tag

        if data['has_additional']:
            page += 1
            continue

        raise ValueError('tag {} not found in {}'.format(tag, name))


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
    raise ValueError('no release-metadata in {} layers'.format(node['version']))


def update_nodes(directory, pullspecs):
    for pullspec in pullspecs:
        by_digest_pullspec, tag = get_by_digest_pullspec(pullspec=pullspec)
        meta = get_release_metadata(node={'payload': by_digest_pullspec})
        match = _VERSION_REGEXP.match(meta['version'])
        if not match:
            raise ValueError('invalid node version in {}: {!r}'.format(pullspec, meta['version']))
        if tag and meta['version'] != tag:
            raise ValueError('unexpected version {!r} not equal to tag {!r}'.format(meta['version']))
        node = {
            'payload': by_digest_pullspec,
            'version': meta['version'],
        }
        uri = meta.get('metadata', {}).get('url', '').strip()
        if uri:
              node['metadata'] = {'url': uri}
        major_minor_dir = os.path.join(directory, 'nodes', '{major}.{minor}'.format(**match.groupdict()))
        try:
            os.mkdir(major_minor_dir)  # os.makedirs' exist_ok is new in Python 3.2
        except FileExistsError:
            pass
        with open(os.path.join(major_minor_dir, '{}.json'.format(meta['version'])), 'w+') as f:
            json.dump(
                node, f, indent=2, sort_keys=True,
                separators=(',', ': '),  # only needs to be explicit in Python 2 and <3.4
            )
            f.write('\n')


def extract_edges(node, directory):
    meta = get_release_metadata(node=node)
    if not meta.get('previous'):
        return
    try:
        os.mkdir(directory)  # os.makedirs' exist_ok is new in Python 3.2
    except FileExistsError:
        pass
    for previous in meta['previous']:
        with open(os.path.join(directory, '{}.json'.format(previous)), 'w+') as f:
            json.dump({
                'channels': sorted(node['channels']),
                'from': previous,
                'to': node['version'],
            }, f, indent=2, sort_keys=True,
                separators=(',', ': '),  # only needs to be explicit in Python 2 and <3.4
            )
            f.write('\n')


def extract_edges_for_versions(directory, versions):
    nodes = load_nodes(directory=os.path.join(directory, 'channels'))
    for version in versions:
        node = nodes[version]
        match = _VERSION_REGEXP.match(node['version'])
        extract_edges(node=node, directory=os.path.join(directory, 'edges', '{major}.{minor}'.format(**match.groupdict()), version))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Utilities for managing graph data.')
    subparsers = parser.add_subparsers()

    update_node_parser = subparsers.add_parser(
        'update-node',
        help='Create or update a node entry from embeded release-metadata.'
    )
    update_node_parser.add_argument(
        'pullspec', nargs='+',
        help='Pull-specs for releases for which nodes should be created or updated.',
    )
    update_node_parser.set_defaults(action='update-node')

    extract_edges_parser = subparsers.add_parser(
        'extract-edges',
        help='Extract the default edges baked into the given release(s).'
    )
    extract_edges_parser.add_argument(
        'version', nargs='+',
        help='Versions from which edges should be extracted.',
    )
    extract_edges_parser.set_defaults(action='extract-edges')

    push_to_quay_parser = subparsers.add_parser(
        'push-to-quay',
        help='Push graph metadata to Quay.io labels.',
    )
    push_to_quay_parser.add_argument(
        '-t', '--token',
        help='Quay token ( https://docs.quay.io/api/#applications-and-tokens )')
    push_to_quay_parser.set_defaults(action='push-to-quay')

    args = parser.parse_args()

    if args.action == 'update-node':
        update_nodes(directory='.', pullspecs=args.pullspec)
    if args.action == 'extract-edges':
        extract_edges_for_versions(directory='.', versions=args.version)
    elif args.action == 'push-to-quay':
        push(directory='.', token=args.token)
