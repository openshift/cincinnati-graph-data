#!/usr/bin/env python3

import os
import re
import util

# Risk names must be CamelCase to be assignable to condition.Reason
# https://github.com/openshift/api/blob/8891815aa476232109dccf6c11b8611d209445d9/vendor/k8s.io/apimachinery/pkg/apis/meta/v1/types.go#L1519-L1520C3
# Note that our regex is stricter, we should never need names more complicated than this.
NAME_RE = re.compile(r'^[A-Z][A-Za-z0-9_]*$')


def validate_blocked_edges(directory):
    for path, data in util.walk_yaml(directory=directory, allowed_extensions=('.yaml',)):
        try:
            validate_blocked_edge(data=data, path=path)
        except Exception as error:
            raise ValueError('invalid blocked edge {}: {}'.format(path, error)) from None


def validate_blocked_edge(data, path):
    for prop in ['to', 'from']:
        if prop not in data:
            raise ValueError('{!r} is a required property'.format(prop))

    to = str(data['to'])
    if 'name' in data and not os.path.basename(path).startswith(to):
        raise ValueError(f"conditional risk to version {to} should be declared in a {to}-<...>.yaml file")

    if 'url' in data and not data['url'].startswith('https://'):
        raise ValueError('url must be an https:// URI, not {!r}'.format(data['url']))
    if 'name' in data and not (isinstance(data['name'], str) and NAME_RE.match(data['name'])):
        raise ValueError('name must be a CamelCase reason, not {!r} (must match {!r}'.format(data['name'], NAME_RE.pattern))
    if 'message' in data and not isinstance(data['message'], str):
        raise ValueError('message must be a string, not {!r}'.format(data['message']))
    if 'matchingRules' in data:
        for key in ['url', 'name', 'message']:
            if key not in data:
                raise ValueError('when matchingRules is set, {} must be set'.format(key))
        if not isinstance(data['matchingRules'], list) or len(data['matchingRules']) == 0:
            raise ValueError('matchingRules must be an array with at least one member')
        types = set()
        for i, rule in enumerate(data['matchingRules']):
            if 'type' not in rule:
                raise ValueError('type must be set for matchingRules[{}]'.format(i))
            if rule['type'] in types:
                raise ValueError('type {} appears multiple times in matchingRules'.format(rule['type']))
            types.add(rule['type'])
            validator = CLUSTER_RULE_VALIDATORS.get(rule['type'])
            if not validator:
                raise ValueError('unrecognized matchingRules[{}] type {!r}'.format(i, rule['type']))
            validator(rule=rule)


def validate_always_rule(rule):
    extra_keys = set(rule.keys()) - {'type'}
    if extra_keys:
        raise ValueError("unrecognized keys in 'Always' rule: {}".format(', '.join(sorted(extra_keys))))


def validate_promql_rule(rule):
    extra_keys = set(rule.keys()) - {'type', 'promql'}
    if extra_keys:
        raise ValueError("unrecognized keys in 'PromQL' rule: {}".format(', '.join(sorted(extra_keys))))
    if 'promql' not in rule:
        raise ValueError("promql must be set for 'PromQL' rules")

    extra_keys = set(rule['promql'].keys()) - {'promql'}
    if extra_keys:
        raise ValueError("unrecognized keys in promql property: {}".format(', '.join(sorted(extra_keys))))
    if 'promql' not in rule['promql']:
        raise ValueError("promql.promql must be set for 'PromQL' rules")
    if not isinstance(rule['promql']['promql'], str):
        raise ValueError('promql.promql value must be a string')  # FIXME: actual PromQL parser validation


CLUSTER_RULE_VALIDATORS = {
    'Always': validate_always_rule,
    'PromQL': validate_promql_rule,
}


if __name__ == '__main__':
    validate_blocked_edges(directory='blocked-edges')
