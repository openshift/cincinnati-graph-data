#!/usr/bin/env python3
# https://datagrepper.engineering.redhat.com/
# https://mojo.redhat.com/docs/DOC-1072237

import argparse
import codecs
import datetime
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import github


logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger()


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
    while True:
        _LOGGER.debug('poll for messages')
        for message in poll(period=2*poll_period, **kwargs):
            if cache and message['fulladvisory'] in cache or 'bug fix update' not in message['synopsis']:
                continue
            try:
                message['approved_pr'] = lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)
            except Exception as error:
                _LOGGER.warn('Error looking up PRs: {}'.format(error))
            notify(message=message, webhook=webhook)
            if cache is not None:
                cache[message['fulladvisory']] = {
                    'when': message['when'],
                    'synopsis': message['synopsis'],
                }
        next_time += poll_period
        _LOGGER.debug('sleep until {}'.format(next_time))
        time.sleep((next_time - datetime.datetime.now()).seconds)


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

    msg_text = '<!subteam^STE7S7ZU2>: {fulladvisory} shipped {when}: {synopsis}'.format(**message)
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
        return pr.url


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
        default=os.environ.get('WEBHOOK'),
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
        default=os.environ.get('GITHUB_TOKEN'),
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
