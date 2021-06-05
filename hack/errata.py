#!/usr/bin/env python3
# https://datagrepper.engineering.redhat.com/
# https://mojo.redhat.com/docs/DOC-1072237

import argparse
import codecs
import datetime
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request

import github


logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger()
_SYNOPSIS_REGEXP = re.compile(r'''
  ^((?P<impact>(Low|Moderate|Important|Critical)):[ ])?
  OpenShift[ ]Container[ ]Platform[ ]
  (?P<version>                         # SemVer regexp from https://semver.org/spec/v2.0.0.html#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
    (?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)(?:\.(?P<patch>0|[1-9]\d*))?
    (?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?
    (?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?
  )
  [ ](?P<type>
    (?:(?:security[ ]and[ ])?bug[ ]fix(?:[ ]and(?:[ ]golang)?[ ]security)?[ ]update)?
    (?:GA[ ]Images)?
  )$
''',
                           re.VERBOSE)


def load(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(path, cache):
    with open(path, 'w') as f:
        json.dump(cache, f, sort_keys=True, indent=2)


def run(poll_period=datetime.timedelta(seconds=3600),
        cache=None,
        webhook=None,
        githubrepo=None,
        githubtoken=None,
        **kwargs):
    next_time = datetime.datetime.now()
    excluded_cache = {}
    while True:
        _LOGGER.debug('poll for messages')
        for message in poll(period=2*poll_period, **kwargs):
            try:
                process_message(
                    message=message,
                    cache=cache,
                    excluded_cache=excluded_cache,
                    webhook=webhook,
                    githubrepo=githubrepo,
                    githubtoken=githubtoken,
                )
            except ValueError as error:
                _LOGGER.warn(error)
        next_time += poll_period
        _LOGGER.debug('sleep until {}'.format(next_time))
        time.sleep((next_time - datetime.datetime.now()).seconds)


def process_message(message, cache, excluded_cache, webhook, githubrepo, githubtoken):
    if excluded_cache and message['synopsis'] in excluded_cache:
        return
    synopsis_match = _SYNOPSIS_REGEXP.match(message['synopsis'])
    if not synopsis_match:
        if excluded_cache is not None:
            excluded_cache[message['synopsis']] = message['fulladvisory']
        raise ValueError('{fulladvisory} shipped {when} does not match synopsis regular expression: {synopsis}'.format(**message))
    if cache and message['fulladvisory'] in cache:
        return
    synopsis_groups = synopsis_match.groupdict()
    advisory = message['fulladvisory'].rsplit('-', 1)[0]  # RHBA-2020:0936-04 -> RHBA-2020:0936, where the -NN suffix is number of respins or something
    channel = 'candidate-{major}.{minor}'.format(**synopsis_groups)
    message['uri'] = public_errata_uri(version=synopsis_groups['version'], advisory=advisory, channel=channel)
    if not message['uri']:
        _LOGGER.warn('No known errata URI for {} in {}'.format(synopsis_groups['version'], channel))
        return
    if not message['uri'].endswith(advisory):
        _LOGGER.warn('Version {} errata {} does not match synopsis {} ({!r})'.format(synopsis_groups['version'], message['uri'], message['fulladvisory'], advisory))
        return
    try:
        message['approved_pr'] = lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)
    except Exception as error:
        _LOGGER.warn('Error looking up PRs: {}'.format(error))
    notify(message=message, webhook=webhook)
    if cache is not None:
        cache[message['fulladvisory']] = {
            'when': message['when'],
            'synopsis': message['synopsis'],
            'uri': message['uri'],
        }


def poll(data_grepper='https://datagrepper.engineering.redhat.com/raw', period=None):
    params = {
        'delta': int(period.total_seconds()),
        'category': 'errata',
        'contains': 'RHOSE',
        'rows_per_page': 100,
    }

    page = 1
    while True:
        params['page'] = page
        uri = '{}?{}'.format(data_grepper, urllib.parse.urlencode(params))
        _LOGGER.debug('query page {}: {}'.format(page, uri))
        try:
            with urllib.request.urlopen(uri) as f:
                data = json.load(codecs.getreader('utf-8')(f))  # hack: should actually respect Content-Type
        except Exception as error:
            _LOGGER.error('{}: {}'.format(uri, error))
            time.sleep(10)
            continue
        for raw_message in data['raw_messages']:
            message = raw_message['msg']
            if message.get('product') == 'RHOSE' and message.get('to') == 'SHIPPED_LIVE':
                yield message
        if page >= data['pages']:
            break
        page += 1
        _LOGGER.debug('{} pages, keep going'.format(data['pages']))


def notify(message, webhook=None):
    if not webhook:
        print(message)
        return

    msg_text = '<!subteam^STE7S7ZU2>: {fulladvisory} shipped {when}: {synopsis} {uri}'.format(**message)
    if  message.get('approved_pr'):
        msg_text += "\nPR {approved_pr} has been approved".format(**message)

    urllib.request.urlopen(webhook, data=urllib.parse.urlencode({
        'payload': {
            'text': msg_text,
        },
    }).encode('utf-8'))


def get_open_prs_to_fast(repo):
    query_params = {
        'state': 'open',
        'base': 'master',
        'sort': 'created',
    }
    for pr in repo.get_pulls(**query_params):
        try:
            # Check only bot PRs
            if pr.user.login != "openshift-bot":
                continue
            # Skip unknown PRs
            if not pr.title.startswith("Enable "):
                continue
            # Ignore PRs which don't target fast
            if pr.title.split(" ")[3] != "fast":
                continue
            # Ignore if its already lgtmed
            if any([x.name == "lgtm" for x in pr.labels]):
                continue
            yield pr
        except Exception as e:
            _LOGGER.warn("Failed to parse {}: {}".format(pr.number, e))


def extract_errata_number_from_body(body):
    ERRATA_MARKER = 'https://errata.devel.redhat.com/advisory/'
    first_line = body.split('\n')[0]
    links = [
        x for x in first_line.split(' ') if x.startswith(ERRATA_MARKER)
    ]
    if len(links) == 0:
        _LOGGER.warn("No links found in PR body: {}".format(body))
        return None
    errata_num = links[0].rsplit('/', 1)[-1]

    try:
        return int(errata_num)
    except ValueError:
        _LOGGER.warn("Failed to convert PR number to int: {}".format(errata_num))
        return None


def lgtm_fast_pr_for_errata(githubrepo, githubtoken, message):
    if not githubtoken:
        _LOGGER.debug("Skipping fast PR check: no github token set")
        return

    github_object = github.Github(githubtoken)
    repo = github_object.get_repo(githubrepo)
    _LOGGER.debug('looking for errata {} in open PRs for repo {}'.format(
        message.get('errata_id'),
        repo)
    )

    for pr in get_open_prs_to_fast(repo):
        _LOGGER.debug('Parsing PR {}'.format(pr))
        errata_num = extract_errata_number_from_body(pr.body)
        if not errata_num or errata_num != message.get('errata_id'):
            continue

        _LOGGER.debug("Found PR #{} promoting to fast for {}".format(pr.number, errata_num))
        msg = "Autoapproving PR to fast after the errata has shipped\n/lgtm"
        pr.create_issue_comment(msg)
        _LOGGER.debug("Commented in {}".format(pr.url))
        return pr.html_url


def public_errata_uri(version, advisory, arch='amd64', channel='', update_service='https://api.openshift.com/api/upgrades_info/v1/graph'):
    params = {
        'channel': channel,
        'arch': arch,
    }

    headers = {
        'Accept': 'application/json',
    }

    uri = '{}?{}'.format(update_service, urllib.parse.urlencode(params))
    request = urllib.request.Request(uri, headers=headers)
    _LOGGER.debug('look for {} ({}) in {}'.format(version, advisory, uri))
    while True:
        try:
            with urllib.request.urlopen(request) as f:
                data = json.load(codecs.getreader('utf-8')(f))  # hack: should actually respect Content-Type
        except Exception as error:
            _LOGGER.error('{}: {}'.format(uri, error))
            time.sleep(10)
            continue
        versions = set()
        for node in data['nodes']:
            if node['version'] == version:
                return node.get('metadata', {}).get('url')
            versions.add(node['version'])
        _LOGGER.debug('{} not found in {} ({})'.format(version, uri, ', '.join(sorted(versions))))
        advisories = set()
        for node in data['nodes']:
            node_advisory = node.get('metadata', {}).get('url', '').rsplit('/', 1)[-1]
            if node_advisory == advisory:
                return node['metadata']['url']
            if node_advisory:
                advisories.add(node_advisory)
        _LOGGER.debug('{} not found in {} ({})'.format(advisory, uri, ', '.join(sorted(advisories))))
        return


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Poll for newly published OCP errata, and optionally push notifications to Slack.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        'webhook',
        nargs='?',
        help='Set this to actually push notifications to Slack.  Defaults to the value of the WEBHOOK environment variable.',
        default=os.environ.get('WEBHOOK', ''),
    )
    parser.add_argument(
        'githubrepo',
        nargs='?',
        help='Autoapprove PRs targetting fast in the github repo.',
        default="openshift/cincinnati-graph-data",
    )
    parser.add_argument(
        'githubtoken',
        nargs='?',
        help='Github token for PR autoapproval. Defaults to the value of the GITHUB_TOKEN environment variable.',
        default=os.environ.get('GITHUB_TOKEN', ''),
    )

    args = parser.parse_args()

    cache_path = '.errata.json'
    cache = load(path=cache_path)
    try:
        run(
            cache=cache,
            webhook=args.webhook.strip(),
            githubrepo=args.githubrepo.strip(),
            githubtoken=args.githubtoken.strip(),
        )
    except:
        save(path=cache_path, cache=cache)
        raise
