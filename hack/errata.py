#!/usr/bin/env python3
# https://datagrepper.engineering.redhat.com/
# https://mojo.redhat.com/docs/DOC-1072237

import argparse
import codecs
import datetime
import json
import logging
import time
import urllib.parse
import urllib.request


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


def run(poll_period=datetime.timedelta(seconds=3600), cache=None, webhook=None, **kwargs):
    next_time = datetime.datetime.now()
    while True:
        _LOGGER.debug('poll for messages')
        for message in poll(period=2*poll_period, **kwargs):
            if cache and message['fulladvisory'] in cache or 'bug fix update' not in message['synopsis']:
                continue
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

    urllib.request.urlopen(webhook, data=urllib.parse.urlencode({
        'payload': {
            'text': '<!subteam^STE7S7ZU2>: {fulladvisory} shipped {when}: {synopsis}'.format(**message),
        },
    }).encode('utf-8'))


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Poll for newly published OCP errata, and optionally push notifications to Slack.')
    parser.add_argument('webhook', nargs='?', help='Set this to actually push notifications to Slack.')
    args = parser.parse_args()

    cache_path = '.errata.json'
    cache = load(path=cache_path)
    try:
        run(cache=cache, webhook=args.webhook)
    except:
        save(path=cache_path, cache=cache)
        raise
