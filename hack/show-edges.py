#!/usr/bin/env python3

import codecs
import collections
import io
import json
import logging
import os
import re
import subprocess
import tarfile
import urllib.parse
import urllib.request

import yaml

import util


logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
#_LOGGER.setLevel(logging.DEBUG)
_VERSION_REGEXP = re.compile('^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')
_CHANNEL_REGEXP = re.compile('^(?P<stream>.*)-(?P<major_minor>[1-9]\d*[.][1-9]\d*)$')


def load_channel(channel, revision=None):
    channels, _ = util.load_channels(revision=revision)
    if channel not in channels:
            raise ValueError('no channel named {}'.format(channel))
    return channels[channel]


def normalize_node(node):
    match = _VERSION_REGEXP.match(node['version'])
    if not match:
        raise ValueError('invalid node version: {!r}'.format(node['version']))
    return node


def version_major_minor(version):
    match = _VERSION_REGEXP.match(version)
    if not match:
        raise ValueError('invalid version: {!r}'.format(version))
    return '{major}.{minor}'.format(**match.groupdict())


def get_architecture(meta):
    return meta['image-config-data']['architecture']


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


def get_release_metadata(node):
    pullspec = node['payload']
    repository = pullspec.split('@', 1)[0]
    prefix = 'quay.io/'
    if not repository.startswith(prefix):
        raise ValueError('non-Quay pullspec: {}'.format(pullspec))
    name = repository[len(prefix):]

    with urllib.request.urlopen(manifest_uri(node=node)) as f:
        data = json.load(codecs.getreader('utf-8')(f))

    manifest = json.loads(data['manifest_data'])
    if 'mediaType' in manifest:
        if manifest['mediaType'] == 'application/vnd.docker.distribution.manifest.list.v2+json':
            per_arch_manifest = manifest['manifests'][0]
            digest = per_arch_manifest['digest']
            _LOGGER.debug('using {} for manifest-list {}'.format(per_arch_manifest, pullspec))
            meta = get_release_metadata(node={'payload': '{}@{}'.format(repository, digest)})
            meta['image-config-data']['architecture'] = 'multi'
            return meta

        if manifest['mediaType'] != 'application/vnd.docker.distribution.manifest.v2+json':
            raise ValueError('unsupported media type for {} manifest: {}'.format(node['payload'], manifest['mediaType']))

        if manifest['config']['mediaType'] != 'application/vnd.docker.container.image.v1+json':
            raise ValueError('unsupported media type for {} config: {}'.format(node['payload'], manifest['config']['mediaType']))
        uri = 'https://quay.io/v2/{}/blobs/{}'.format(name, manifest['config']['digest'])
        with urllib.request.urlopen(uri) as f:
            config = json.load(codecs.getreader('utf-8')(f))
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
        with urllib.request.urlopen(uri) as f:
            layer_bytes = f.read()

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


def load_nodes(versions, architecture, repository, directory='.nodes'):
    versions_remaining = set(versions)
    nodes = {}
    if not versions_remaining:
        return nodes

    for root, _, files in os.walk(directory):
        for filename in files:
            path = os.path.join(root, filename)
            with open(path) as f:
                try:
                    meta = yaml.load(f, Loader=yaml.SafeLoader)
                except ValueError as error:
                    raise ValueError('failed to load YAML from {}: {}'.format(path, error))
                if not meta:
                    continue  # this pullspec isn't a usable release image
            if not isinstance(meta, dict) or 'version' not in meta:
                continue
            arch = get_architecture(meta=meta)
            if meta['version'] in versions_remaining and arch == architecture:
                _LOGGER.debug('loaded from cache: {}+{} {}'.format(meta['version'], arch, meta))
                nodes[meta['version']] = meta
                versions_remaining.remove(meta['version'])
                if not versions_remaining:
                    return nodes

    reg, repo = repository.split('/', 1)
    repository_uri = 'https://{}/api/v1/repository/{}'.format(reg, repo)
    page = 1
    while versions_remaining:
        uri = '{}/tag/?page={}'.format(repository_uri, page)
        _LOGGER.debug('retrieve tags from {}'.format(uri))
        with urllib.request.urlopen(uri) as f:
            data = json.load(codecs.getreader('utf-8')(f))
        for entry in data['tags']:
            if 'expiration' in entry:
                continue

            algo, hash = entry['manifest_digest'].split(':', 1)
            pullspec = '{}@{}:{}'.format(repository, algo, hash)
            node = {'payload': pullspec}
            path = os.path.join(directory, algo, hash)

            try:
                with open(path) as f:
                    try:
                        meta = yaml.load(f, Loader=yaml.SafeLoader)
                    except ValueError as error:
                        raise ValueError('failed to load YAML from {}: {}'.format(path, error))
                    if not meta:
                        continue  # this pullspec isn't a usable release image
                arch = get_architecture(meta=meta)
                _LOGGER.debug('loaded from cache: {}+{} {}'.format(meta['version'], arch, node['payload']))
            except IOError:
                try:
                    meta = get_release_metadata(node=node)
                except (KeyError, ValueError) as error:
                    _LOGGER.warning('unable to get release metadata for {} {} : {}'.format(pullspec, entry, error))
                    meta = {}
                os.makedirs(os.path.join(directory, algo), exist_ok=True)
                try:
                    with open(path, 'w') as f:
                        yaml.safe_dump(meta, f, default_flow_style=False)
                except:
                    os.remove(path)
                    raise
                if not meta:
                    _LOGGER.debug('caching empty metadata for {} {}'.format(entry['name'], node['payload']))
                    continue
                arch = get_architecture(meta=meta)
                _LOGGER.debug('caching metadata for {}+{} {}'.format(meta['version'], arch, node['payload']))
            node['version'] = meta['version']
            node['meta'] = meta
            if meta.get('previous'):
                node['previous'] = set(meta['previous'])
                node['internal-previous'] = set(meta['previous'])
            if meta.get('next'):
                node['next'] = set(meta['next'])
            try:
                node = normalize_node(node=node)
            except ValueError as error:
                _LOGGER.debug(error)
                continue
            version = node['version']
            arch = get_architecture(meta=meta)
            if version in versions_remaining and arch == architecture:
                nodes[version] = node
                versions_remaining.remove(version)
                if not versions_remaining:
                    break

        if data['has_additional']:
            page += 1
            continue

        break

    if versions_remaining:
        _LOGGER.warning('walked all tag pages, but did not find releases for: {}'.format(', '.join(sorted(versions_remaining))))

    return nodes


def get_edges(nodes):
    edges = set()
    for node in nodes.values():
        for previous in node.get('previous', []):
            if previous in nodes:
                edges.add((previous, node['version']))
    return edges


def load_blocks(versions, revision=None, directory='blocked-edges'):
    blocks = []
    for path, data in util.walk_yaml(directory=directory, revision=revision):
        if data['to'] in versions:
            blocks.append(data)
    return blocks


def get_blocked(edges, blocks, architecture):
    blocked = collections.defaultdict(set)
    for from_version, to_version in edges:
        for block in blocks:
            if to_version == block['to']:
                regexp = re.compile(block['from'])
                if regexp.match('{}+{}'.format(from_version, architecture)):
                    key = (from_version, to_version)
                    blocked[key].add(block.get('name'))
    return blocked


def show_edges(channel, architecture, repository, revision=None, cache='.metadata.json', root_version=None, cincinnati=None, list_unable_to_reach_target_minor_version=False):
    if not repository and not cincinnati:
        raise ValueError('either an image registry repository or a Cincinnati URI must be configured to retrieve node metadata.')
    if revision and cincinnati:
        raise ValueError('cannot specify both revision (for loading from graph-data) and a Cincinnati URI (for loading from Cincinnati).')

    if cincinnati:
        split_uri = urllib.parse.urlsplit(cincinnati)
        query = urllib.parse.parse_qs(split_uri.query)
        query['channel'] = channel
        uri = urllib.parse.urlunsplit((split_uri.scheme, split_uri.netloc, split_uri.path, urllib.parse.urlencode(query, doseq=True), split_uri.fragment))
        with urllib.request.urlopen(uri) as f:
            data = json.load(codecs.getreader('utf-8')(f))
        channel = {
            'name': channel,
            'versions': [node['version'] for node in data.get('nodes', [])],
        }
        edges = []
        for from_index, to_index in data.get('edges', []):
            edges.append((data['nodes'][from_index]['version'], data['nodes'][to_index]['version']))
        blocked = {}
        for conditional_edge in data.get('conditionalEdges', []):
            for edge in conditional_edge['edges']:
                key = (edge['from'], edge['to'])
                edges.append(key)
                blocked[key] = set(risk['name'] for risk in conditional_edge['risks'])
    else:
        channel = load_channel(channel=channel, revision=revision)
        nodes = load_nodes(versions=channel.get('versions', []), architecture=architecture, repository=repository)
        edges = get_edges(nodes=nodes)
        blocks = load_blocks(versions=[node['version'] for node in nodes.values()], revision=revision)
        blocked = get_blocked(edges=edges, blocks=blocks, architecture=architecture)

    reachable = set()
    if root_version is None:
        reachable = set(channel['versions'])
    else:
        reachable.add(root_version)
        extended = True
        while extended:
            extended = False
            for from_version, to_version in sorted(edges):
                if from_version in reachable and to_version not in reachable:
                    reachable.add(to_version)
                    extended = True

    for from_version, to_version in sorted(edges):
        if from_version not in reachable:
            continue
        key = (from_version, to_version)
        if key in blocked:
            if None not in blocked[key]:
                reasons = ', '.join(sorted(blocked[key]))
                print('{} -(risks: {})-> {}'.format(from_version, reasons, to_version))
            elif len([name for name in blocked[key] if name != None]) > 0:
                reasons = ', '.join(sorted([r or 'SILENT-BLOCK-CINCINNATI-WILL-IGNORE' for r in blocked[key]]))  # https://issues.redhat.com/browse/OTA-1043
                print('{} -(risks: {})-> {}'.format(from_version, reasons, to_version))
            else:  # None is the only entry
                print('{} -(SILENT-BLOCK)-> {}'.format(from_version, to_version))
        else:
            print('{} -> {}'.format(from_version, to_version))

    if list_unable_to_reach_target_minor_version:
        match = _CHANNEL_REGEXP.match(channel['name'])
        if not match:
            raise ValueError('unable to extract major.minor version from channel {!r}'.format(channel['name']))
        channel_major_minor = match.groupdict()['major_minor']

        for version in channel.get('versions', []):
            try:
                assert_path_to_minor(version=version, edges=edges, blocked=blocked, target_major_minor=channel_major_minor)
            except ValueError as error:
                print(error)


def assert_path_to_minor(version, edges, blocked, target_major_minor):
    if version_major_minor(version=version) == target_major_minor:
        return  # already on the target minor version

    all_reachable = set()
    reachable = set([version])
    while reachable:
        source = reachable.pop()
        targets = set(target for s,target in edges if s == source and (s, target) not in blocked)
        for target in targets:
            if version_major_minor(version=target) == target_major_minor:
                return  # hooray, we made it
            reachable.update(targets)  # maybe additional hops will get us to the target major.minor.
            all_reachable.update(targets)

    err = 'No unconditional paths from {} to {}'.format(version, target_major_minor)
    if all_reachable:
        raise ValueError('{}.  Reachable targets are: {}'.format(err, ', '.join(sorted(all_reachable))))
    raise ValueError(err)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Display edges for a particular channel and commit.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--architecture',
        metavar='ARCHITECTURE',
        help='Architecture to use when selecting release images, when multiple releases share a single version name.',
        default='amd64',
    )
    parser.add_argument(
        '--repository',
        metavar='REPOSITORY',
        help='Image registry repository for loading release images.',
        default='quay.io/openshift-release-dev/ocp-release',
    )
    parser.add_argument(
        '--revision',
        metavar='REVISION',
        help='Git revision for loading graph-data configuration (see gitrevisions(7) for syntax).',
    )
    parser.add_argument(
        '--root-version',
        dest='root_version',
        metavar='VERSION',
        help='Only show the graph downstream of a given version.',
    )
    parser.add_argument(
        '--cincinnati',
        metavar='URI',
        help='Instead of loading graph-data, retrieve channel information from Cincinnati.  This makes it harder to see historical or still-unmerged data, but avoids the time spend building a cache of node metadata with image registry repository scraping.',
    )
    parser.add_argument(
        '--list-unable-to-reach-target-minor-version',
        dest='list_unable_to_reach_target_minor_version',
        action='store_true',
        help="In addition to showing edges, list releases that cannot update to the channel's target 4.y minor version.",
    )
    parser.add_argument(
        'channel',
        metavar='CHANNEL',
        help='Cincinnati channel to load.',
    )

    args = parser.parse_args()

    show_edges(
        channel=args.channel,
        architecture=args.architecture,
        repository=args.repository,
        revision=args.revision,
        root_version=args.root_version,
        cincinnati=args.cincinnati,
        list_unable_to_reach_target_minor_version=args.list_unable_to_reach_target_minor_version,
    )
