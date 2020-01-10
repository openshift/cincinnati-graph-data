#!/usr/bin/env python

import argparse
import codecs
import functools
import io
import json
import logging
import multiprocessing.dummy
import os
import re
import shutil
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


_VERSION_REGEXP = re.compile('^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')
logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)


def remove_build(semver_match):
    data = semver_match.groupdict()
    version = '{major}.{minor}.{patch}'.format(**data)
    if data.get('prerelease'):
        version += '-{prerelease}'.format(**data)
    return version


def load_nodes(directory, registry, repository):
    cache_version = 1
    write_version = True
    try:
        os.mkdir(directory)  # os.makedirs' exist_ok is new in Python 3.2
    except FileExistsError:
        try:
            with open(os.path.join(directory, 'version')) as f:
                version = int(f.read())
        except IOError:
            _LOGGER.debug('no cache version found; clearing the old cache...')
            shutil.rmtree(directory)
            os.mkdir(directory)
        else:
            write_version = version != cache_version
            if write_version:
                _LOGGER.debug('existing cache had version {}; clearing the old cache...'.format(version))
                shutil.rmtree(directory)
                os.mkdir(directory)
    if write_version:
        _LOGGER.debug('creating new node cache with version {}'.format(cache_version))
        with open(os.path.join(directory, 'version'), 'w') as f:
            f.write('{}\n'.format(cache_version))

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
                except (KeyError, ValueError) as error:
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
            if node['version'] not in nodes:
               nodes[node['version']] = {}
            nodes[node['version']][meta['image-config-data']['architecture']] = node

        if data['has_additional']:
            page += 1
            continue

        break

    return nodes


def load_channels(directory, nodes):
    for arch_nodes in nodes.values():
        for node in arch_nodes.values():
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
                    semver_match = _VERSION_REGEXP.match(version)
                    if not semver_match:
                        raise ValueError('{} claims version {}, but that is not a valid Semantic Version'.format(path, version))
                    try:
                        arch_nodes = nodes[remove_build(semver_match=semver_match)]
                    except KeyError:
                        raise ValueError('{} claims version {}, but no nodes found with that version'.format(path, version))
                    arch = semver_match.group('buildmetadata')
                    for node_arch, node in arch_nodes.items():
                        if node_arch == arch or not arch:
                            node['channels'].add(channel)

    for arch_nodes in nodes.values():
        for node in arch_nodes.values():
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
                to_version = _VERSION_REGEXP.match(data['to'])
                if not to_version:
                    raise ValueError('{} claims version {}, but that is not a valid Semantic Version'.format(path, data['to']))
                try:
                    to_nodes = nodes[remove_build(semver_match=to_version)]
                except KeyError:
                    raise ValueError('{} claims version {}, but no nodes found with that version'.format(path, data['to']))
                to_arch = to_version.group('buildmetadata')
                arch_matching_to_nodes = [
                    node for arch, node in to_nodes.items()
                    if arch == to_arch or not to_arch
                ]
                if not arch_matching_to_nodes:
                    raise ValueError('{} claims version {}, but the only nodes with version {} are for {}'.format(path, data['to'], remove_build(semver_match=to_version), sorted(to_nodes.keys())))
                try:
                    from_regexp = re.compile(data['from'])
                except ValueError as error:
                    raise ValueError('{} invalid from regexp: {}'.format(path, data['from']))
                for to_node in arch_matching_to_nodes:
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

    sync_nodes = []
    for version, arch_nodes in sorted(nodes.items()):
        if not push_versions or version in push_versions.split(','):
            sync_nodes.extend(arch_nodes.values())

    sync = functools.partial(sync_node, token=token)
    pool = multiprocessing.dummy.Pool(processes=16)
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
    pullspec = node['payload']
    name = pullspec.split('@', 1)[0]
    prefix = 'quay.io/'
    if not name.startswith(prefix):
        raise ValueError('non-Quay pullspec: {}'.format(pullspec))
    name = name[len(prefix):]

    f = urlopen(manifest_uri(node=node))
    data = json.load(codecs.getreader('utf-8')(f))
    f.close()  # no with-statement because in Python 2: AttributeError: addinfourl instance has no attribute '__exit__'

    manifest = json.loads(data['manifest_data'])
    if 'mediaType' in manifest:
        if manifest['mediaType'] != 'application/vnd.docker.distribution.manifest.v2+json':
            raise ValueError('unsupported media type for {} manifest: {}'.format(node['payload'], manifest['mediaType']))

        if manifest['config']['mediaType'] != 'application/vnd.docker.container.image.v1+json':
            raise ValueError('unsupported media type for {} config: {}'.format(node['payload'], manifest['config']['mediaType']))
        uri = 'https://quay.io/v2/{}/blobs/{}'.format(name, manifest['config']['digest'])
        f = urlopen(uri)
        config = json.load(codecs.getreader('utf-8')(f))
        f.close()  # no with-statement because in Python 2: AttributeError: addinfourl instance has no attribute '__exit__'
        image_config_data = {}
        for prop in ['architecture', 'os']:
            try:
                image_config_data[prop] = config[prop]
            except KeyError:
                raise ValueError('{} config {} has no {!r} property'.format(node['payload'], manifest['config']['digest'], prop))
    elif manifest.get('schemaVersion') == 1:
        image_config_data = {}
        if 'architecture' in manifest:
            image_config_data['architecture'] = manifest['architecture']
        for history in manifest.get('history', []):
            if 'v1Compatibility' in history:
                hist = json.loads(history['v1Compatibility'])
                for prop in ['architecture', 'os']:
                    if prop in hist:
                        image_config_data[prop] = hist[prop]
        for prop in ['architecture', 'os']:
            if prop not in image_config_data:
                raise ValueError('unrecognized {} manifest format without {!r}: {}'.format(node['payload'], prop, json.dumps(manifest)))
        if 'layers' not in manifest:
            if 'fsLayers' not in manifest:
                raise ValueError('unrecognized {} manifest format without layers: {}'.format(node['payload'], json.dumps(manifest)))
            manifest['layers'] = [
                {
                    'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                    'digest': layer['blobSum'],
                }
                for layer in manifest['fsLayers']
            ]
    else:
        raise ValueError('unrecognized {} manifest format: {}'.format(node['payload'], json.dumps(manifest)))


    for layer in reversed(manifest['layers']):
        if layer['mediaType'] != 'application/vnd.docker.image.rootfs.diff.tar.gzip':
            raise ValueError('unsupported media type for {} layer {}: {}'.format(node['payload'], layer['digest'], layer['mediaType']))

        uri = 'https://quay.io/v2/{}/blobs/{}'.format(name, layer['digest'])
        f = urlopen(uri)
        layer_bytes = f.read()
        f.close()

        with tarfile.open(fileobj=io.BytesIO(layer_bytes), mode='r:gz') as tar:
            try:
                f = tar.extractfile('release-manifests/release-metadata')
            except KeyError:
                try:
                    f = tar.extractfile('release-manifests/image-references')
                except KeyError:
                    continue
                else:
                    image_references = json.load(codecs.getreader('utf-8')(f))
                    meta = {
                        'version': image_references['metadata']['name']
                    }
                    if image_references['metadata'].get('annotations'):
                        meta['metadata'] = image_references['metadata']['annotations']
            else:
                meta = json.load(codecs.getreader('utf-8')(f))
            meta['image-config-data'] = image_config_data
            return meta
            # TODO: assert meta.get('kind') == 'cincinnati-metadata-v0'

    raise ValueError('no release-metadata in {} layers ( {} )'.format(node['payload'], json.dumps(manifest)))


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
