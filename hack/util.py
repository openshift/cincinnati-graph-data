# Assorted utilities for processing graph-data.

import io
import os
import subprocess

import yaml


def walk_yaml(directory, revision=None, allowed_extensions=None):
    if revision is None:
        for root, _, files in os.walk(directory):
            for filename in files:
                if not filename.endswith('.yaml'):
                    if allowed_extensions:
                        _, ext = os.path.splitext(filename)
                        if ext not in allowed_extensions:
                            raise ValueError('invalid filename: {!r} (allowed extensions: {})'.format(os.path.join(root, filename), allowed_extensions))
                    continue
                path = os.path.join(root, filename)
                with open(path) as f:
                    try:
                        data = yaml.load(f, Loader=yaml.SafeLoader)
                    except ValueError as error:
                        raise ValueError('failed to load YAML from {}: {}'.format(path, error))
                yield (path, data)
        return

    list_process = subprocess.run(
        ['git', 'ls-tree', '-r', '--name-only', revision, directory],
        capture_output=True,
        check=True,
        text=True,
    )
    for path in list_process.stdout.splitlines():
        if not path.endswith('.yaml'):
            continue
        process = subprocess.run(
            ['git', 'cat-file', '-p', '{}:{}'.format(revision, path)],
            capture_output=True,
            check=True,
            text=True,
        )
        try:
            data = yaml.load(io.StringIO(process.stdout), Loader=yaml.SafeLoader)
        except ValueError as error:
            raise ValueError('failed to load YAML from {}: {}'.format(path, error))
        yield (path, data)


def load_channels(revision=None, directories=('channels', 'internal-channels')):
    channels = {}
    paths = {}
    for directory in directories:
        for path, data in walk_yaml(directory=directory, revision=revision):
            channel = data['name']
            if channel in channels:
                raise ValueError('multiple definitions for {}: {} and {}'.format(channel, paths[channel], path))
            paths[channel] = path
            channels[channel] = data
    return channels, paths
