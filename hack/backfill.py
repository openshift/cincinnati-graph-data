#!/usr/bin/env python3

import functools
import re

import yaml


SEMVER = re.compile('^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')


def version_key(v, minor):
    match = SEMVER.match(v)
    groups = match.groupdict()
    v_minor = int(groups['minor'])
    v_patch = int(groups['patch'])
    if v_minor != minor:
        v_patch = -v_patch
    return (int(groups['major']), v_minor, v_patch, v)


data = {}
minors = [3, 4, 5, 6]
weights = ['candidate', 'fast', 'stable']
for minor in minors:
    data[minor] = {}
    for weight in weights:
        with open('channels/{}-4.{}.yaml'.format(weight, minor)) as f:
            data[minor][weight] = yaml.safe_load(f)

for minor, next_minor in zip(minors, minors[1:]):
    for weight in weights:
        versions = set(data[minor][weight]['versions'])
        versions.update(v for v in data[next_minor][weight]['versions'] if v.startswith('4.{}.'.format(minor)))
        data[minor][weight]['versions'] = sorted(versions, key=functools.partial(version_key, minor=minor))

        versions = set(data[next_minor][weight]['versions'])
        versions.update(v for v in data[minor][weight]['versions'] if v.startswith('4.{}.'.format(minor)))
        data[next_minor][weight]['versions'] = sorted(versions, key=functools.partial(version_key, minor=next_minor))

for minor in minors:
    for weight in weights:
        with open('channels/{}-4.{}.yaml'.format(weight, minor), 'w') as f:
            yaml.safe_dump(data[minor][weight], f, default_flow_style=False)
