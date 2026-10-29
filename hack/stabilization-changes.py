#!/usr/bin/env python3

import codecs
import collections
import datetime
import http
import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import textwrap
import time
import types
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request

try:
    import github
except ModuleNotFoundError as error:
    github_import_error = error
    github = None

import yaml

import util


logging.basicConfig(format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)
_ADVISORY_TYPE_REGEXP = re.compile(r'RH[BSE]A')
_ISO_8601_DELAY_REGEXP = re.compile(r'^P((?P<weeks>\d+)W|((?P<days>\d+)D)?(T(?P<hours>\d+)H)?)$')
_GIT_BLAME_COMMIT_REGEXP = re.compile(r'^(?P<hash>[0-9a-f]{40}) .*')
_GIT_BLAME_HEADER_REGEXP = re.compile(r'^(?P<key>[^ \t]+) (?P<value>.*)$')
_GIT_BLAME_LINE_REGEXP = re.compile(r'^\t(?P<value>.*)$')
_GIT_REMOTE_LINE_REGEXP = re.compile(r'^(?P<remote>[^ ]*)\t(?P<uri>(?P<scheme>[^:]*)://(?P<host>[^/]*)/(?P<org>[^/]*)/(?P<repo>[^/.]*)(.git)?) [(](?P<role>.*)[)]$')
_SEM_VER_REGEXP = re.compile(r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')
_REMOTE_CACHE = {}
_SEMANTIC_VERSION_DELIMITERS = re.compile('[.+-]')

socket.setdefaulttimeout(60)


class PullRequest(object):
    """Drop-in stub for github.PullRequest when we fail to import 'github'."""
    def __init__(self, html_url, action='created'):
        self.html_url = html_url
        self.action = action


def parse_iso8601_delay(delay):
    # https://tools.ietf.org/html/rfc3339#page-13
    match = _ISO_8601_DELAY_REGEXP.match(delay)
    if not match:
        raise ValueError('invalid or unsupported ISO 8601 duration {!r}.  Tooling currently only supports P<number>W for weeks, or P<number>DT<number>H for day/hour offsets'.format(delay))
    weeks = int(match.group('weeks') or 0)
    days = int(match.group('days') or 0)
    hours = int(match.group('hours') or 0)
    return datetime.timedelta(weeks=weeks, days=days, hours=hours)


class TestStabilization(unittest.TestCase):
    def test_git_captured_diagnostics_are_logged_without_credentials(self):
        for status in (0, 1):
            command = '!printf "stdout-test-token"; printf "stderr-test-token" >&2; exit {}'.format(status)
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                with self.assertLogs(_LOGGER, level='DEBUG') as logs:
                    if status:
                        with self.assertRaises(subprocess.CalledProcessError):
                            _git('-c', 'alias.diagnostic=' + command, 'diagnostic', cwd=directory,
                                 capture_output=True, github_token='test-token')
                    else:
                        self.assertEqual(_git('-c', 'alias.diagnostic=' + command, 'diagnostic', cwd=directory,
                                              capture_output=True, github_token='test-token'), b'stdout-test-token')
                output = '\n'.join(logs.output)
                self.assertIn('stdout-REDACTED', output)
                self.assertIn('stderr-REDACTED', output)
                self.assertNotIn('test-token', output)

    def test_git_does_not_capture_safe_commands_by_default(self):
        self.assertIsNone(_git('version'))

    def test_add_version_preserves_upstream_content(self):
        original = '# Channel policy\nname: fast-4.13\nfeeder:\n  name: fast\nversions:\n- 4.12.88 # first merge\n- 4.12.90\n# Keep this note\n'
        updated = add_version(original, '4.12.89', 'fast-4.13')
        self.assertEqual(updated, '# Channel policy\nname: fast-4.13\nfeeder:\n  name: fast\nversions:\n- 4.12.88 # first merge\n- 4.12.89\n- 4.12.90\n# Keep this note\n')
        self.assertEqual(add_version(updated, '4.12.89', 'fast-4.13'), updated)

    def test_add_version_rejects_ambiguous_yaml(self):
        for content in [
                'name: fast-4.13\nversions: [4.12.88]\nversions: [4.12.90]\n',
                'name: stable-4.13\nversions: [4.12.88]\n',
                'name: fast-4.13\nversions: [4.12.88, 4.12.88]\n']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                add_version(content, '4.12.89', 'fast-4.13')

    def test_add_version_handles_empty_and_inline_lists(self):
        for versions, expected in [('[]', '[4.12.89]'), ('[4.12.88, 4.12.90]', '[4.12.88, 4.12.89, 4.12.90]')]:
            with self.subTest(versions=versions):
                self.assertEqual(add_version('name: fast-4.13\nversions: {} # Keep\n'.format(versions), '4.12.89', 'fast-4.13'),
                                 'name: fast-4.13\nversions: {} # Keep\n'.format(expected))

    def test_add_version_preserves_existing_unsorted_entries(self):
        for original, expected in [
                ('versions:\n- 4.12.90 # Keep\n- 4.12.87\n',
                 'versions:\n- 4.12.89\n- 4.12.90 # Keep\n- 4.12.87\n'),
                ('versions: [4.12.90, 4.12.87]\n',
                 'versions: [4.12.89, 4.12.90, 4.12.87]\n')]:
            with self.subTest(original=original):
                self.assertEqual(add_version('name: fast-4.13\n' + original, '4.12.89', 'fast-4.13'),
                                 'name: fast-4.13\n' + expected)

    def test_add_version_keeps_comments_with_following_entry(self):
        original = 'name: fast-4.13\nversions:\n- 4.12.87\n\n# Note for 4.12.90\n- 4.12.90\n'
        self.assertEqual(add_version(original, '4.12.89', 'fast-4.13'),
                         'name: fast-4.13\nversions:\n- 4.12.87\n- 4.12.89\n\n# Note for 4.12.90\n- 4.12.90\n')

    def test_add_version_does_not_change_aliased_metadata(self):
        content = 'name: fast-4.13\nother: &shared [4.12.88]\nversions: *shared\n'
        with self.assertRaises(ValueError):
            add_version(content, '4.12.89', 'fast-4.13')

    def test_sem_ver_prerelease_less_than(self):
        test_cases = [
            ('alpha', 'beta', True),
            ('alpha', 'alpha.1', True),
            ('alpha.1', 'alpha.2', True),
            ('ec.2', 'rc.1', True),
            ('rc.1', 'rc.2', True),
            ('rc.1', 'rc.10', True),
            ('rc.2', 'rc.10', True),
            ('rc.2', 'rc.two', True)
        ]

        for a, b, expected in test_cases:
            assert sem_ver_prerelease_less_than(a, b) == expected, f'{a} < {b} should be {expected}'

    def test_sem_ver_less_than(self):
        test_cases = [
            ('4.18.1', '4.18.1', False),
            ('4.18.2', '4.18.1', False),
            ('4.18.1', '4.18.2', True),
            ('4.19.1', '4.18.2', False),
            ('4.19.0-ec.9', '4.19.0-rc.1', True),
            ('4.19.0-rc.1', '4.19.0-rc.2', True),
            ('4.19.0-rc.2', '4.19.0-rc.10', True),
        ]

        for a, b, expected in test_cases:
            assert sem_ver_less_than(a, b) == expected, f'{a} < {b} should be {expected}'


class TestPromotion(unittest.TestCase):
    """Exercise real Git repositories; replace only the GitHub API boundary."""
    channel_path = 'channels/fast-4.13.yaml'
    branch = 'promote-4.12.89-to-fast-4.13'
    message = b'channels/fast-4.13: Promote 4.12.89\n\nOriginal body.\n\nTrailer: keep verbatim\n'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = self.temp.name
        self.upstream = os.path.join(self.directory, 'upstream.git')
        self.fork = os.path.join(self.directory, 'fork.git')
        self.checkout = os.path.join(self.directory, 'checkout')
        self.git('init', '--bare', self.upstream, cwd=self.directory)
        self.git('init', '--bare', self.fork, cwd=self.directory)
        self.git('init', self.checkout, cwd=self.directory)
        self.git('config', 'user.name', 'Automated Stabilization Robot')
        self.git('config', 'user.email', 'noreply@redhat.com')
        self.git('config', 'core.hooksPath', os.path.join(self.directory, 'no-hooks'))
        self.git('remote', 'add', 'upstream', self.upstream)
        self.git('checkout', '-b', 'master')
        os.makedirs(os.path.join(self.checkout, 'channels'))
        self.original = '# Policy\nname: fast-4.13\nfeeder:\n  name: fast\nversions:\n- 4.12.87\n'
        self.write(self.original)
        self.git('add', '.')
        self.git('commit', '--no-gpg-sign', '-m', 'Initial graph')
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.git('push', self.upstream, 'HEAD:refs/heads/master')
        self.git('checkout', '-b', self.branch)
        # Existing OTA commits were generated with safe_dump, losing comments.
        data = yaml.safe_load(self.original)
        data['versions'].append('4.12.89')
        self.write(yaml.safe_dump(data))
        self.git('add', self.channel_path)
        self.git('commit', '--no-gpg-sign', '--cleanup=verbatim', '-F', '-', input=self.message)
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.git('push', self.fork, 'HEAD:refs/heads/' + self.branch)
        self.git('checkout', 'master')
        self.pull = types.SimpleNamespace(
            html_url='https://github.com/upstream/graph/pull/8',
            user=types.SimpleNamespace(login='ota-bot'),
            head=types.SimpleNamespace(ref=self.branch, sha=self.head,
                                       repo=types.SimpleNamespace(full_name='ota-bot/graph')),
            base=types.SimpleNamespace(ref='master'),
            mergeable=False, mergeable_state='dirty', state='open')
        self.repo = unittest.mock.Mock()
        self.repo.get_pulls.side_effect = lambda **kwargs: [self.pull] if kwargs['state'] == 'open' else []
        self.client = unittest.mock.Mock()
        self.client.get_repo.return_value = self.repo
        self.client.get_user.return_value.login = 'ota-bot'
        self.api = unittest.mock.patch.dict(globals(), github=types.SimpleNamespace(Github=lambda token: self.client))
        self.api.start()
        self.addCleanup(self.api.stop)
        self.old_cwd = os.getcwd()
        os.chdir(self.checkout)
        self.addCleanup(os.chdir, self.old_cwd)
        self.remote = unittest.mock.patch.dict(globals(), get_remote=lambda repo: 'upstream')
        self.remote.start()
        self.addCleanup(self.remote.stop)
        # No credentials or network calls: all pushes go to the local bare fork.
        self.uri = unittest.mock.patch.dict(globals(), _push_uri=lambda repo, token: self.fork)
        self.uri.start()
        self.addCleanup(self.uri.stop)
        real_run = subprocess.run

        def local_only(command, **kwargs):
            if any('github.com' in str(arg) for arg in command):
                raise AssertionError('Tests must not contact GitHub')
            return real_run(command, **kwargs)

        guard = unittest.mock.patch.object(subprocess, 'run', side_effect=local_only)
        guard.start()
        self.addCleanup(guard.stop)

    def git(self, *args, cwd=None, input=None):
        return subprocess.run(['git'] + list(args), cwd=cwd or self.checkout,
                              input=input, check=True, capture_output=True).stdout.decode()

    def write(self, content):
        with open(os.path.join(self.checkout, self.channel_path), 'w') as stream:
            stream.write(content)

    def merge_other_versions(self, versions=('4.12.88', '4.12.90')):
        self.git('checkout', 'master')
        for version in versions:
            with open(os.path.join(self.checkout, self.channel_path)) as stream:
                content = stream.read()
            self.write(content + '- ' + version + '\n')
            self.git('add', self.channel_path)
            self.git('commit', '--no-gpg-sign', '-m', 'Merge promotion ' + version)
        self.git('push', self.upstream, 'HEAD:refs/heads/master')
        return self.git('rev-parse', 'HEAD').strip()

    def promote(self):
        return promote(version='4.12.89', channel_name='fast-4.13', channel_path=self.channel_path,
                       subject='New subject must not replace the old message', body='New elapsed time',
                       upstream_github_repo='upstream/graph', push_github_repo='ota-bot/graph',
                       github_token='not-a-real-token', upstream_branch='master')

    def remote_head(self):
        return self.git('rev-parse', 'refs/heads/' + self.branch, cwd=self.fork).strip()

    def test_repair_preserves_multiple_merges_and_commit_message(self):
        latest = self.merge_other_versions()
        self.git('branch', '-D', self.branch)  # Simulate a restarted pod with no local branch.
        result = self.promote()
        repaired = self.remote_head()
        self.assertNotEqual(repaired, self.head)
        self.assertEqual(self.git('rev-parse', repaired + '^').strip(), latest)
        self.assertEqual(self.git('show', repaired + ':' + self.channel_path),
                         '# Policy\nname: fast-4.13\nfeeder:\n  name: fast\nversions:\n- 4.12.87\n- 4.12.88\n- 4.12.89\n- 4.12.90\n')
        self.assertEqual(self.git('cat-file', 'commit', repaired).split('\n\n', 1)[1].encode(), self.message)
        self.assertEqual(result.action, 'repaired')
        self.assertEqual(result.html_url, self.pull.html_url)
        self.repo.create_pull.assert_not_called()
        # A subsequent merge can conflict again; use the newest base and same message.
        self.pull.head.sha = repaired
        self.merge_other_versions(('4.12.91',))
        self.promote()
        again = self.remote_head()
        self.assertEqual(yaml.safe_load(self.git('show', again + ':' + self.channel_path))['versions'],
                         ['4.12.87', '4.12.88', '4.12.89', '4.12.90', '4.12.91'])
        self.assertEqual(self.git('cat-file', 'commit', again).split('\n\n', 1)[1].encode(), self.message)

    def test_clean_or_unknown_pr_is_not_rewritten(self):
        for mergeable in (True, None):
            self.pull.mergeable = mergeable
            self.pull.mergeable_state = 'clean' if mergeable else 'unknown'
            result = self.promote()
            self.assertEqual(self.remote_head(), self.head)
            self.assertEqual(result.action, 'waiting')
        self.repo.create_pull.assert_not_called()

    def test_manual_edits_are_not_overwritten(self):
        self.merge_other_versions()
        self.git('checkout', self.branch)
        self.write('name: fast-4.13\nfeeder:\n  name: stable\nversions:\n- 4.12.87\n- 4.12.89\n')
        self.git('add', self.channel_path)
        self.git('commit', '--no-gpg-sign', '--amend', '--no-edit')
        self.pull.head.sha = self.git('rev-parse', 'HEAD').strip()
        self.git('push', '--force', self.fork, 'HEAD:refs/heads/' + self.branch)
        before = self.remote_head()
        with self.assertRaisesRegex(ValueError, 'human review'):
            self.promote()
        self.assertEqual(self.remote_head(), before)

    def test_concurrent_branch_edit_rejects_push(self):
        self.merge_other_versions()
        self.git('checkout', self.branch)
        self.git('commit', '--no-gpg-sign', '--allow-empty', '-m', 'Concurrent human update')
        concurrent = self.git('rev-parse', 'HEAD').strip()
        real_run = subprocess.run

        def race(command, **kwargs):
            if command[:2] == ['git', 'push'] and any(arg.startswith('--force-with-lease=') for arg in command):
                self.git('push', self.fork, concurrent + ':refs/heads/' + self.branch)
            return real_run(command, **kwargs)

        with unittest.mock.patch.object(subprocess, 'run', side_effect=race), self.assertRaisesRegex(ValueError, 'retry next pass') as failure:
            self.promote()
        self.assertIn(self.pull.html_url, str(failure.exception))
        self.assertEqual(self.remote_head(), concurrent)

    def test_repair_validation_error_includes_pr_link(self):
        self.write('name: fast-4.13\nother: &shared [4.12.87, 4.12.88]\nversions: *shared\n')
        self.git('add', self.channel_path)
        self.git('commit', '--no-gpg-sign', '-m', 'Channel aliases require manual review')
        self.git('push', self.upstream, 'HEAD:refs/heads/master')
        with self.assertRaisesRegex(ValueError, re.escape(self.pull.html_url)):
            self.promote()
        self.assertEqual(self.remote_head(), self.head)

    def test_version_already_upstream_does_not_push(self):
        self.merge_other_versions(('4.12.89',))
        result = self.promote()
        self.assertEqual(self.remote_head(), self.head)
        self.assertEqual(result.action, 'already-present')

    def test_no_token_preserves_local_generation(self):
        result = promote('4.12.89', 'fast-4.13', self.channel_path, 'Subject', 'Body',
                         'upstream/graph', 'ota-bot/graph', None, 'master')
        with open(self.channel_path) as stream:
            self.assertEqual(yaml.safe_load(stream)['versions'], ['4.12.87', '4.12.89'])
        self.assertEqual(result.html_url, 'data://no-token-so-no-pull')
        self.client.get_repo.assert_not_called()

    def test_new_pr_ignores_stale_local_branch(self):
        self.repo.get_pulls.side_effect = lambda **kwargs: []
        self.git('push', self.fork, ':refs/heads/' + self.branch)
        self.repo.create_pull.return_value.html_url = self.pull.html_url
        result = self.promote()
        created = self.remote_head()
        self.assertEqual(yaml.safe_load(self.git('show', created + ':' + self.channel_path))['versions'],
                         ['4.12.87', '4.12.89'])
        self.assertEqual(result.action, 'created')
        self.assertEqual(self.git('rev-parse', self.branch).strip(), self.head)
        self.repo.create_pull.assert_called_once_with(
            title='New subject must not replace the old message', body='New elapsed time',
            head='ota-bot:' + self.branch, base='master', maintainer_can_modify=True)

    def test_failed_pr_creation_removes_new_branch_and_allows_retry(self):
        self.repo.get_pulls.side_effect = lambda **kwargs: []
        self.git('push', self.fork, ':refs/heads/' + self.branch)
        original_error = RuntimeError('PR creation failed')
        self.repo.create_pull.side_effect = original_error
        with self.assertRaises(RuntimeError) as failure:
            self.promote()
        self.assertIs(failure.exception, original_error)
        self.assertEqual(self.git('ls-remote', '--heads', self.fork, 'refs/heads/' + self.branch), '')
        self.repo.create_pull.side_effect = None
        self.repo.create_pull.return_value.html_url = self.pull.html_url
        self.assertEqual(self.promote().action, 'created')

    def test_failed_pr_creation_does_not_delete_concurrent_branch_update(self):
        self.repo.get_pulls.side_effect = lambda **kwargs: []
        self.git('push', self.fork, ':refs/heads/' + self.branch)
        original_error = RuntimeError('PR creation failed')

        def fail_creation(**kwargs):
            self.git('push', '--force', self.fork, self.head + ':refs/heads/' + self.branch)
            raise original_error

        self.repo.create_pull.side_effect = fail_creation
        with self.assertLogs(_LOGGER, level='WARNING') as logs, self.assertRaises(RuntimeError) as failure:
            self.promote()
        self.assertIs(failure.exception, original_error)
        self.assertEqual(self.remote_head(), self.head)
        self.assertIn(self.branch, '\n'.join(logs.output))

    def test_failed_branch_cleanup_preserves_pr_creation_exception(self):
        self.repo.get_pulls.side_effect = lambda **kwargs: []
        self.git('push', self.fork, ':refs/heads/' + self.branch)
        original_error = RuntimeError('PR creation failed')
        self.repo.create_pull.side_effect = original_error
        real_git = _git

        def fail_cleanup(*args, **kwargs):
            if args[0] == 'push' and args[-1] == ':refs/heads/' + self.branch:
                raise OSError('credential-bearing cleanup diagnostic')
            return real_git(*args, **kwargs)

        with unittest.mock.patch.dict(globals(), _git=fail_cleanup), self.assertLogs(_LOGGER, level='WARNING') as logs:
            with self.assertRaises(RuntimeError) as failure:
                self.promote()
        self.assertIs(failure.exception, original_error)
        self.assertTrue(self.remote_head())
        self.assertIn(self.branch, '\n'.join(logs.output))
        self.assertNotIn('credential-bearing', '\n'.join(logs.output))

    def test_missing_or_closed_pr_does_not_recreate_branch(self):
        for closed in ([], [self.pull]):
            self.repo.get_pulls.side_effect = lambda state, **kwargs: closed if state == 'closed' else []
            with self.assertRaisesRegex(ValueError, 'human review'):
                self.promote()
            self.assertEqual(self.remote_head(), self.head)
        self.repo.create_pull.assert_not_called()

    def test_extra_files_and_commits_require_human_review(self):
        self.merge_other_versions()
        self.git('checkout', self.branch)
        with open(os.path.join(self.checkout, 'manual.txt'), 'w') as stream:
            stream.write('Keep my changes\n')
        self.git('add', 'manual.txt')
        self.git('commit', '--no-gpg-sign', '--amend', '--no-edit')
        self.pull.head.sha = self.git('rev-parse', 'HEAD').strip()
        self.git('push', '--force', self.fork, 'HEAD:refs/heads/' + self.branch)
        with self.assertRaisesRegex(ValueError, 'human review'):
            self.promote()
        self.assertEqual(self.remote_head(), self.pull.head.sha)
        self.git('commit', '--no-gpg-sign', '--allow-empty', '-m', 'Human follow-up')
        self.pull.head.sha = self.git('rev-parse', 'HEAD').strip()
        self.git('push', self.fork, 'HEAD:refs/heads/' + self.branch)
        with self.assertRaisesRegex(ValueError, 'human review'):
            self.promote()
        self.assertEqual(self.remote_head(), self.pull.head.sha)

    def test_other_pr_author_is_not_rewritten(self):
        self.pull.user.login = 'someone-else'
        with self.assertRaisesRegex(ValueError, 'ownership'):
            self.promote()
        self.assertEqual(self.remote_head(), self.head)

    def test_lazy_api_refresh_cannot_repair_a_closed_or_retargeted_pr(self):
        self.merge_other_versions()
        original = self.pull
        for change in ('closed', 'retargeted'):
            class LazyPull(types.SimpleNamespace):
                @property
                def mergeable(current):
                    if change == 'closed':
                        current.state = 'closed'
                    else:
                        current.base = types.SimpleNamespace(ref='different-base')
                    return False

            self.pull = LazyPull()
            self.pull.__dict__.update(vars(original))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'human review'):
                self.promote()
            self.assertEqual(self.remote_head(), self.head)

    def test_upstream_advancing_during_repair_is_handled_next_pass(self):
        self.merge_other_versions(('4.12.88',))
        real_commit = _promotion_commit

        def advance(*args, **kwargs):
            commit = real_commit(*args, **kwargs)
            self.merge_other_versions(('4.12.90',))
            return commit

        with unittest.mock.patch.dict(globals(), _promotion_commit=advance):
            self.promote()
        self.pull.head.sha = self.remote_head()
        self.promote()
        content = self.git('show', self.remote_head() + ':' + self.channel_path)
        self.assertEqual(yaml.safe_load(content)['versions'], ['4.12.87', '4.12.88', '4.12.89', '4.12.90'])

    def test_repaired_pr_is_unchanged_when_mergeable_next_pass(self):
        self.merge_other_versions()
        self.promote()
        repaired = self.remote_head()
        self.pull.head.sha = repaired
        self.pull.mergeable, self.pull.mergeable_state = True, 'clean'
        self.assertEqual(self.promote().action, 'waiting')
        self.assertEqual(self.remote_head(), repaired)

    def test_waiting_status_uses_daily_notification_schedule(self):
        kwargs = dict(version='4.12.89', channel={'name': 'fast-4.13'}, channel_path=self.channel_path,
                      delay=datetime.timedelta(0), errata=None, feeder_name='fast',
                      feeder_promotion={'committer-time': datetime.datetime.now() - datetime.timedelta(days=1),
                                        'hash': 'a' * 40, 'summary': 'Original promotion'},
                      candidates={'4.12.89'}, cache={})
        with unittest.mock.patch.dict(globals(), get_concerns_about_risk_extensions=lambda **kw: None,
                             get_concerns_about_updating_out=lambda **kw: None):
            for action in ('waiting', 'already-present', 'repaired', 'created'):
                for waiting_notifications in (False, True):
                    with self.subTest(action=action, waiting_notifications=waiting_notifications), unittest.mock.patch.dict(
                            globals(), promote=lambda **kw: PullRequest(self.pull.html_url, action)):
                        notifications = list(stabilize_release(**kwargs, waiting_notifications=waiting_notifications))
                        if action in ('waiting', 'already-present') and not waiting_notifications:
                            self.assertEqual(notifications, [])
                        else:
                            self.assertEqual(len(notifications), 1)
                            self.assertTrue(notifications[0].startswith(action + ' '))
                            self.assertIn(self.pull.html_url, notifications[0])
                            self.assertNotIn('FAILED', notifications[0])


def sem_ver_prerelease_less_than(a, b):
    """Returns true if a is less than b, per https://semver.org/spec/v2.0.0.html#spec-item-11, assuming both are non-empty prerelease segments"""
    ids_a = a.split('.')
    ids_b = b.split('.')

    for id_a, id_b in zip(ids_a, ids_b):
        id_a_is_int = id_a.isdigit()
        id_b_is_int = id_b.isdigit()

        # One numeric and one non-numeric -> numeric is lower
        if id_a_is_int and not id_b_is_int:
            return True
        if not id_a_is_int and id_b_is_int:
            return False

        # Both numeric
        if id_a_is_int and id_b_is_int:
            if int(id_a) < int(id_b):
                return True
            if int(id_a) > int(id_b):
                return False
        # ...or both non-numeric
        else:
            if id_a < id_b:
                return True
            if id_a > id_b:
                return False

    if len(ids_a) < len(ids_b):
        return True
    if len(ids_a) > len(ids_b):
        return False

    return False


def sem_ver_less_than(a, b):
    """Returns true if a is less than b, per https://semver.org/spec/v2.0.0.html#spec-item-11"""
    a_match = _SEM_VER_REGEXP.match(a)
    if not a_match:
        raise ValueError('invalid semantic version {!r}'.format(a_match))
    b_match = _SEM_VER_REGEXP.match(b)
    if not b_match:
        raise ValueError('invalid semantic version {!r}'.format(b_match))
    a_groups = a_match.groupdict()
    b_groups = b_match.groupdict()

    if int(a_groups['major']) < int(b_groups['major']):
        return True
    if int(a_groups['major']) > int(b_groups['major']):
        return False

    if int(a_groups['minor']) < int(b_groups['minor']):
        return True
    if int(a_groups['minor']) > int(b_groups['minor']):
        return False

    if int(a_groups['patch']) < int(b_groups['patch']):
        return True
    if int(a_groups['patch']) > int(b_groups['patch']):
        return False

    if a_groups['prerelease'] and not b_groups['prerelease']:
        return True
    if b_groups['prerelease'] and not a_groups['prerelease']:
        return False

    # Reaching here means releases are equal unless both sides
    # have a prerelease segment
    if not (a_groups['prerelease'] or b_groups['prerelease']):
        return False

    return sem_ver_prerelease_less_than(a_groups['prerelease'], b_groups['prerelease'])


def stabilization_changes(directories, webhook=None, **kwargs):
    channels, channel_paths = util.load_channels(directories=directories)

    update_risks = {}
    for path, data in util.walk_yaml(directory='blocked-edges'):
        update_risks[path] = data

    cache = {}
    notifications = []
    for name, channel in sorted(channels.items()):
        notifications.extend(stabilize_channel(name=name, channel=channel, channels=channels, channel_paths=channel_paths, update_risks=update_risks, cache=cache, **kwargs))
    if notifications:
        deduped_notifications = []
        for notification in notifications:
            if notification not in deduped_notifications:
                deduped_notifications.append(notification)
        notify(message='* ' + ('\n* '.join(deduped_notifications)), webhook=webhook)


def stabilize_channel(name, channel, channels, channel_paths, cache=None, waiting_notifications=True, **kwargs):
    if not channel.get('feeder'):
        return
    feeder = channel['feeder']['name']
    conditions = []

    delay_string = channel['feeder'].get('delay')
    if delay_string is not None:
        delay = parse_iso8601_delay(delay=delay_string)
        conditions.append('{}'.format(delay_string))
    else:
        delay = None

    errata = channel['feeder'].get('errata')
    if errata is not None and errata != 'public':
        raise ValueError('invalid errata value for {}: {}', channel, errata)
    if errata:
        conditions.append('the errata is published')

    version_filter = re.compile('^{}$'.format(channel['feeder'].get('filter', '.*')))
    feeder_data = channels[feeder]
    tombstones = set(feeder_data.get('tombstones', {}))
    zombies = set(channel['versions']).intersection(tombstones)
    if zombies:
        _LOGGER.warning('some versions in {} despite tombstones in {}: {}'.format(name, feeder, ', '.join(sorted(zombies))))
    unpromoted = set(feeder_data['versions']) - set(channel['versions']) - tombstones
    candidates = set(v for v in unpromoted if version_filter.match(v))
    if candidates:
        feeder_promotions = get_promotions(channel_paths[feeder])
        _LOGGER.info('considering promotions from {} to {} after {}'.format(feeder, name, ' or '.join(conditions)))
        for version in sorted(candidates):
            feeder_promotion = feeder_promotions[version]
            yield from stabilize_release(
                version=version,
                channel=channel,
                channel_path=channel_paths[name],
                delay=delay,
                errata=errata,
                feeder_name=feeder,
                feeder_promotion=feeder_promotion,
                candidates=candidates,
                cache=cache,
                waiting_notifications=waiting_notifications,
                **kwargs)
    if waiting_notifications:
        yield from get_concerns_about_patch_updates(
            channel=channel,
            cache=cache)


def stabilize_release(version, channel, channel_path, delay, errata, feeder_name, feeder_promotion, candidates, cache, update_risks=None, waiting_notifications=True, github_token=None, **kwargs):
    now = datetime.datetime.now()
    version_delay = now - feeder_promotion['committer-time']
    errata_public = False
    public_errata_message = ''
    if errata:
        errata_uri, errata_public = public_errata_uri(version=version, channel=feeder_name, cache=cache)
        if errata_uri:
            public_errata_message = ' {} is{} public.'.format(errata_uri, '' if errata_public else ' not')

    concerns = []
    concerns_about_risk_extensions = get_concerns_about_risk_extensions(version=version, channel=channel, candidates=candidates, update_risks=update_risks)
    if concerns_about_risk_extensions:
        _LOGGER.error('  failed to promote {} to {}: {}'.format(version, channel['name'], concerns_about_risk_extensions))
        yield 'FAILED {}'.format(concerns_about_risk_extensions)
        return
    concerns_about_updating_out = get_concerns_about_updating_out(version=version, channel=channel, cache=cache)
    if concerns_about_updating_out:
        concerns.append(concerns_about_updating_out)

    if not concerns and ((delay is not None and version_delay > delay) or errata_public):
        path_without_extension, _ = os.path.splitext(channel_path)
        subject = '{}: Promote {}'.format(path_without_extension, version)
        body = 'It was promoted to the feeder {} by {} ({}, {}) {} ago.{}'.format(
                feeder_name,
                feeder_promotion['hash'][:10],
                feeder_promotion['summary'],
                feeder_promotion['committer-time'].date().isoformat(),
                version_delay,
                public_errata_message,
            )
        try:
            pull = promote(
                version=version,
                channel_name=channel['name'],
                channel_path=channel_path,
                subject=subject,
                body=body,
                github_token=github_token,
                **kwargs)
        except Exception as exc:
            _LOGGER.error('  failed to promote {} to {}: {}'.format(version, channel['name'], sanitize(exc, github_token=github_token)))
            yield 'FAILED {}. {} {}'.format(subject, body, sanitize(exc, github_token=github_token))
        else:
            if pull.action in ('created', 'repaired') or waiting_notifications:
                if pull.action == 'repaired':
                    body = ''
                yield '{} {}. {} {}'.format(pull.action, subject, body, pull.html_url)
            else:
                _LOGGER.info('  {}: {} {}'.format(pull.action, subject, pull.html_url))
    else:
        if concerns:
            concerns.insert(0, '')  # when joined with the whitespace delimiter, this will add leading space to offset from the rest of the message
        _LOGGER.info('  waiting: {} ({}){}{}'.format(version, version_delay, public_errata_message, '  '.join(concerns)))
        if waiting_notifications:
            yield 'Recommend waiting to promote {} to {}; it was promoted the feeder {} by {} ({}, {}, {}){}{}'.format(
                version,
                channel['name'],
                feeder_name,
                feeder_promotion['hash'][:10],
                feeder_promotion['summary'],
                feeder_promotion['committer-time'].date().isoformat(),
                version_delay,
                public_errata_message,
                '  '.join(concerns))


def get_promotions(path):
    # https://git-scm.com/docs/git-blame#_the_porcelain_format
    process = subprocess.run(['git', 'blame', '--first-parent', '--porcelain', path], check=True, capture_output=True, text=True)
    commits = {}
    lines = {}
    for i, line in enumerate(process.stdout.strip().split('\n')):
        match = _GIT_BLAME_COMMIT_REGEXP.match(line)
        if match:
            commit = match.group('hash')
            if commit not in commits:
                commits[commit] = {'hash': commit}
            continue
        match = _GIT_BLAME_HEADER_REGEXP.match(line)
        if match:
            key = match.group('key')
            value = match.group('value')
            if key == 'committer-time':
                commits[commit]['committer-time'] = datetime.datetime.fromtimestamp(int(value))
            else:
                commits[commit][key] = value
            continue
        match = _GIT_BLAME_LINE_REGEXP.match(line)
        if not match:
            raise ValueError('unrecognized blame output for {} (blame line {}): {}'.format(path, i+1, line))
        lines[match.group('value')] = commit
    promotions = {}
    for line, commit in lines.items():
        if line.startswith('- '):
            version = line[2:]
            promotions[version] = commits[commit]
    return promotions


def public_errata_uri(version, cache=None, **kwargs):
    if cache and cache.get('versions', {}).get(version, -1) != -1:
        cached = cache['versions'][version]
        if not cached:
            return None, None
        return cached['uri'], cached['public']
    if kwargs.get('channel') == 'candidate':
        major_minor = '.'.join(version.split('.', 2)[:2])
        kwargs['channel'] = 'candidate-{}'.format(major_minor)
    cincinnati_uri, cincinnati_data = get_cincinnati_channel(cache=cache, **kwargs)
    canonical_errata_uri = errata_uri_from_cincinnati(version=version, cincinnati_data=cincinnati_data, cincinnati_uri=cincinnati_uri)
    if not canonical_errata_uri:
        if cache is not None:
            if 'versions' not in cache:
                cache['versions'] = {}
            cache['versions'][version] = None
        return None, None
    errata_uri, public = _public_errata_uri(uri=canonical_errata_uri)
    if cache is not None:
        if 'versions' not in cache:
            cache['versions'] = {}
        cache['versions'][version] = {
            'uri': errata_uri,
            'public': public,
        }
    return errata_uri, public


def get_concerns_about_risk_extensions(version, channel, candidates, update_risks=None):
    if update_risks is None:
        return

    release_major_minor = '.'.join(version.split('.', 2)[:2])
    previous_version = None
    candidate_previous_versions = set(channel.get('versions', [])).union(candidates)
    for target in candidate_previous_versions:
        target_major_minor = '.'.join(target.split('.', 2)[:2])
        if target_major_minor != release_major_minor:
            continue  # we're only looking at earlier patch releases in the same 4.y
        if sem_ver_less_than(target, version) and (previous_version is None or sem_ver_less_than(previous_version, target)):
            previous_version = target
    if previous_version is None:
        return

    risks = set()
    previous_risks_fixed_in = {}
    previous_risks_auto_extend = {}
    for path, risk in sorted(update_risks.items()):
        key = risk.get('name', path)
        if risk['to'] == version:
            risks.add(key)
        if risk['to'] == previous_version:
            fixed_in = risk.get('fixedIn', None)
            if fixed_in is None or (version != fixed_in and sem_ver_less_than(version, fixed_in)):
                previous_risks_fixed_in[key] = fixed_in
            auto_extend = risk.get('autoExtend', None)
            if auto_extend:
                previous_risks_auto_extend[key] = auto_extend

    unfixed = []
    for key, fixed_in in sorted(previous_risks_fixed_in.items()):
        if key in risks:
            continue
        if fixed_in:
            unfixed.append('{} affects {} and is not fixed until {}.  Extend the risk to {}.'.format(key, previous_version, fixed_in, version))
        elif previous_risks_auto_extend.get(key):
            unfixed.append('{} affects {} and needs to be extended to {} because {}'.format(key, previous_version, version, previous_risks_auto_extend[key]))
        else:
            unfixed.append(
                '{risk} affects {prev} and has no fixedIn set.'
                '  Check the url in the blocked-edges YAML for {risk} to determine if the issue has been fixed.'
                '  If the issue is fixed in {ver} or earlier, set "fixedIn" in the blocked-edges YAML for {risk} to the version containing the fix.'
                '  If the issue is NOT yet fixed, copy the existing blocked-edges entry for {risk} and change "to" to {ver} so clusters are still warned when updating to {ver}.'
                .format(risk=key, prev=previous_version, ver=version)
            )

    if unfixed:
        return ' '.join(unfixed)
    return


def get_concerns_about_updating_out(version, channel, cache=None):
    release_major_minor = '.'.join(version.split('.', 2)[:2])
    try:
        phase, channel_major_minor = channel['name'].rsplit('-', 1)
    except ValueError:
        return  # 'fast' and similar version-agnostic channels do not need updating-out concerns
    if phase == 'candidate':
        return  # we need ungated candidate-4.y admission to bootstrap using candidate-4.y update recommendations for gating later phases.
    if release_major_minor == channel_major_minor:
        return  # we are concerned about getting from 4.(y-1) and earlier into 4.y, not about movement within 4.y.
    updates = {}
    channel_versions = set(channel.get('versions', set()))
    cincinnati_uris = []

    # work around 4.(y-1) limit for today's candidate-4.y channels by iterating over multiple candidate channels
    release_major, release_minor = (int(x) for x in release_major_minor.split('.'))
    channel_major, channel_minor = (int(x) for x in channel_major_minor.split('.'))
    if release_major != channel_major:
        raise ValueError('unclear which candidate channels to pull for update information between {} and {}'.format(release_major_minor, channel_major_minor))
    candidate_minor = channel_minor
    while candidate_minor > release_minor:
        cincinnati_uri, cincinnati_data = get_cincinnati_channel(cache=cache, channel='candidate-{}.{}'.format(channel_major, candidate_minor))
        nodes = cincinnati_data.get('nodes', [])
        for edge in cincinnati_data.get('edges', []):
            source = nodes[edge[0]]['version']
            target = nodes[edge[1]]['version']
            if target not in channel_versions or (source != version and source not in channel_versions):
                continue  # even if we promote version, this edge will not be in the target channel
            if source not in updates:
                updates[source] = set()
            updates[source].add(target)
        for conditional in cincinnati_data.get('conditionalEdges', []):
            for edge in conditional.get('edges', []):
                if edge['to'] not in channel_versions or (edge['from'] != version and edge['from'] not in channel_versions):
                    continue  # even if we promote version, this edge will not be in the target channel
                if edge['from'] not in updates:
                    updates[edge['from']] = set()
                updates[edge['from']].add(edge['to'])
        cincinnati_uris.append(cincinnati_uri)
        candidate_minor -= 1

    reachable = {version}
    while reachable:
        source = reachable.pop()
        targets = updates.get(source, set())
        for target in targets:
            target_major_minor = '.'.join(target.split('.', 2)[:2])
            if target_major_minor == channel_major_minor:
                return  # we have update path to the target major.minor.
        reachable.update(targets)  # maybe additional hops will get us to the target major.minor.

    return 'No paths from {} to {} in {}'.format(version, channel_major_minor, ' '.join(cincinnati_uris))


def get_concerns_about_patch_updates(channel, cache=None):
    if len(channel['versions']) > 1:
        patch_updates = collections.defaultdict(lambda: collections.defaultdict(set))
        largest_version = list(sorted(channel['versions'], key=semver_sort_key))[-1]
        release_major, release_minor = (int(x) for x in largest_version.split('.')[:2])
        major_minor_prefix = '{}.{}.'.format(release_major, release_minor)
        early_channel = 'candidate-{}.{}'.format(release_major, release_minor)
        if major_minor_prefix == '4.1.':
            early_channel = 'prerelease-{}.{}'.format(release_major, release_minor)
        cincinnati_uri, cincinnati_data = get_cincinnati_channel(cache=cache, channel=early_channel)
        nodes = cincinnati_data.get('nodes', [])
        for edge in cincinnati_data.get('edges', []):
            source = nodes[edge[0]]['version']
            target = nodes[edge[1]]['version']
            if target in channel['versions']:
                patch_updates[source][None].add(target)
        for conditional in cincinnati_data.get('conditionalEdges', []):
            for edge in conditional.get('edges', []):
                if edge['to'] in patch_updates[edge['from']].get(None, {}):  # work around https://issues.redhat.com/browse/OCPBUGS-25833
                    patch_updates[edge['from']][None].remove(edge['to'])
                    if len(patch_updates[edge['from']][None]) == 0:
                        del patch_updates[edge['from']][None]
                    if len(patch_updates[edge['from']]) == 0:
                        del patch_updates[edge['from']]
                for risk in conditional.get('risks', []):
                    patch_updates[edge['from']][risk['name']].add(edge['to'])
        warnings = {}
        for version in sorted(channel['versions'], key=semver_sort_key):
            if not version.startswith(major_minor_prefix):
                continue  # older major.minor will have patch updates checked in channels capped at that major.minor
            if version == largest_version:
                continue  # there can be no updates from the largest release in the channel, that will need future releases
            if None in patch_updates.get(version, {}):
                continue  # unconditional patch update exists
            if version in patch_updates:
                risks = sorted(set(patch_updates[version].keys()))
                warnings[version] = '{} has patch updates in {}, but they are exposed to risks: {}'.format(version, channel['name'], ', '.join(risks))
                continue
            warnings[version] = '{} has no patch updates in {}'.format(version, channel['name'])
        for version, warning in sorted(warnings.items()):
            will_complain_about_later_release = False
            for risk, targets in patch_updates[version].items():
                for target in targets:
                    if target in warnings:
                        will_complain_about_later_release = True
                        _LOGGER.debug('ignore {} ({}), because it can update to {}, and we will complain about {} ({})'.format(version, warning, target, target, warnings[target]))
                        break
                if will_complain_about_later_release:
                    break
            if not will_complain_about_later_release:
                sem_ver = _SEM_VER_REGEXP.match(version)
                if sem_ver and sem_ver.group('prerelease'):
                    _LOGGER.debug('ignore patch connectivity for prerelease {}'.format(warning))
                    continue  # do not worry about connectivity among prereleases
                if version in {
                        '4.1.38',  # has no patch updates in stable-4.1, but nothing we can do about that now
                        '4.2.14+amd64',  # has no patch updates in fast-4.2, because this function doesn't understand graph-data's arch suffixes
                    }:
                    continue
                yield warning


def get_cincinnati_channel(arch='amd64', channel='', update_service='https://api.openshift.com/api/upgrades_info/v1/graph', cache=None):
    params = {
        'channel': channel,
        'arch': arch,
    }

    headers = {
        'Accept': 'application/json',
    }

    uri = '{}?{}'.format(update_service, urllib.parse.urlencode(params))

    if cache and cache.get('channels', {}).get(channel, {}).get(arch):
        return uri, cache['channels'][channel][arch]

    request = urllib.request.Request(uri, headers=headers)
    _LOGGER.debug('retrieve Cincinnati data from {}'.format(uri))
    while True:
        try:
            with urllib.request.urlopen(request) as f:
                data = json.load(codecs.getreader('utf-8')(f))  # hack: should actually respect Content-Type
        except Exception as exc:
            _LOGGER.error('{}: {}'.format(uri, exc))
            time.sleep(10)
            continue
        break
    if cache is not None:
        if 'channels' not in cache:
            cache['channels'] = {}
        if channel not in cache['channels']:
            cache['channels'][channel] = {}
        cache['channels'][channel][arch] = data
    return uri, data


def errata_uri_from_cincinnati(version, cincinnati_data, cincinnati_uri='Cincinnati'):
    versions = set()
    errata_uri = None
    for node in cincinnati_data['nodes']:
        if node['version'] == version:
            errata_uri = node.get('metadata', {}).get('url')
            if not errata_uri:
                _LOGGER.debug('{} found in {}, but does not declare metadata.url'.format(version, cincinnati_uri))
                return None
            break
        versions.add(node['version'])
    if not errata_uri:
        _LOGGER.debug('{} not found in {} ({})'.format(version, cincinnati_uri, ', '.join(sorted(versions))))
    return errata_uri


def _public_errata_uri(uri):
    for potential_errata_uri in advisory_phrasings(advisory=uri):
        headers = {
            'User-Agent': 'cincinnati-graph-data/0.1',  # for some reason, https://access.redhat.com/ 403s urllib/{version}
        }
        request = urllib.request.Request(potential_errata_uri, headers=headers)
        while True:
            try:
                with urllib.request.urlopen(request):
                    pass
            except urllib.error.HTTPError as exc:
                if exc.code == http.HTTPStatus.FORBIDDEN or exc.code == http.HTTPStatus.NOT_FOUND:
                    _LOGGER.debug('{}: {}'.format(potential_errata_uri, exc))
                    break
                _LOGGER.error('{}: {}'.format(potential_errata_uri, exc))
                time.sleep(10)
                continue
            except Exception as exc:
                _LOGGER.error('{}: {}'.format(potential_errata_uri, exc))
                time.sleep(10)
                continue
            return potential_errata_uri, True
    return uri, False


def advisory_phrasings(advisory):
    match = _ADVISORY_TYPE_REGEXP.search(advisory)
    if not match:
        _LOGGER.warning('advisory did not match the advisory type regular expression: {}'.format(advisory))
        return
    for phrasing in ['RHBA', 'RHSA', 'RHEA']:
        yield '{}{}{}'.format(advisory[:match.start()], phrasing, advisory[match.end():])


def notify(message, webhook=None):
    if not webhook:
        print(message)
        return

    msg_text = '<!subteam^STE7S7ZU2>: Cincinnati stabilization:\n{}'.format(message)

    urllib.request.urlopen(webhook, data=urllib.parse.urlencode({
        'payload': {
            'text': msg_text,
        },
    }).encode('utf-8'))


class _ChannelLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ValueError('duplicate YAML keys require human review')
        return mapping


def _load_channel(content, channel_name):
    try:
        data = yaml.load(content, Loader=_ChannelLoader)
    except yaml.YAMLError as exc:
        raise ValueError('invalid channel YAML; human review required: {}'.format(exc)) from exc
    if not isinstance(data, dict) or data.get('name') != channel_name:
        raise ValueError('unexpected channel name; human review required')
    versions = data.get('versions')
    if (not isinstance(versions, list) or
            any(not isinstance(v, str) or not _SEM_VER_REGEXP.fullmatch(v) for v in versions) or
            len(set(versions)) != len(versions)):
        raise ValueError('unexpected version list; human review required')
    return data


def add_version(content, version, channel_name):
    """Insert one version without reserializing upstream comments or metadata."""
    data = _load_channel(content, channel_name)
    if version in data['versions']:
        return content
    if not _SEM_VER_REGEXP.fullmatch(version):
        raise ValueError('invalid promotion version')
    # Some historical channels are unsorted.  Preserve their existing entries
    # rather than refusing promotion or reordering unrelated upstream content.
    insertion = next((index for index, value in enumerate(data['versions'])
                      if semver_sort_key(version) < semver_sort_key(value)), len(data['versions']))
    root = yaml.compose(content)
    versions = next(value for key, value in root.value if key.value == 'versions')
    expected = dict(data, versions=data['versions'][:insertion] + [version] + data['versions'][insertion:])
    if versions.flow_style and versions.start_mark.line == versions.end_mark.line:
        replacement = yaml.safe_dump(expected['versions'], default_flow_style=True, width=1000000).strip()
        updated = content[:versions.start_mark.index] + replacement + content[versions.end_mark.index:]
        if _load_channel(updated, channel_name) != expected:
            raise ValueError('could not safely insert version; human review required')
        return updated
    if versions.flow_style or not versions.value:
        raise ValueError('unexpected version list formatting; human review required')
    lines = content.splitlines(keepends=True)
    position = versions.value[-1].end_mark.line + 1
    for item in versions.value:
        if item.start_mark.line != item.end_mark.line:
            raise ValueError('multiline version entry; human review required')
        if semver_sort_key(version) < semver_sort_key(item.value):
            position = item.start_mark.line
            # Keep a preceding note next to the entry it describes.
            while position > 0 and (not lines[position - 1].strip() or
                                    lines[position - 1].lstrip().startswith('#')):
                position -= 1
            break
    match = re.match(r'^( *)- ', lines[versions.value[0].start_mark.line])
    if not match:
        raise ValueError('unexpected version list formatting; human review required')
    if position == len(lines) and lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines.insert(position, '{}- {}\n'.format(match.group(1), version))
    updated = ''.join(lines)
    if _load_channel(updated, channel_name) != expected:
        raise ValueError('could not safely insert version; human review required')
    return updated


def _git(*args, capture_output=False, github_token=None, **kwargs):
    # Capture commands containing credentials or returning data to the caller.
    process = subprocess.run(['git'] + list(args), capture_output=capture_output, **kwargs)
    if capture_output:
        level = logging.ERROR if process.returncode else logging.DEBUG
        for output in (process.stdout, process.stderr):
            if output:
                _LOGGER.log(level, 'git %s: %s', args[0], sanitize(output.decode(errors='replace'), github_token))
    process.check_returncode()
    return process.stdout


def _push_uri(repo, token):
    return 'https://{}@github.com/{}.git'.format(token, repo)


def _promotion_commit(base, channel_path, content, message, author=None):
    """Build a commit in a temporary index, leaving HEAD and local files alone."""
    with tempfile.TemporaryDirectory() as directory:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(directory, 'index'))
        if author:
            env.update(author)
        _git('read-tree', base, env=env)
        entry = _git('ls-tree', base, '--', channel_path, capture_output=True).decode().split()
        if len(entry) != 4 or entry[:2] != ['100644', 'blob']:
            raise ValueError('unexpected channel file type; human review required')
        blob = _git('hash-object', '-w', '--stdin', input=content.encode(), capture_output=True).decode().strip()
        _git('update-index', '--cacheinfo', entry[0], blob, channel_path, env=env)
        tree = _git('write-tree', env=env, capture_output=True).decode().strip()
        commit = _git('commit-tree', tree, '-p', base, input=message, env=env, capture_output=True).decode().strip()
        if _git('cat-file', 'commit', commit, capture_output=True).split(b'\n\n', 1)[1] != message:
            raise ValueError('commit message could not be preserved; human review required')
        return commit


def _repair_promotion(pull, base, content, version, channel_name, channel_path, push_uri, github_token=None):
    failure = '{} requires human review'.format(pull.html_url)
    _git('fetch', '--no-tags', push_uri, 'refs/heads/' + pull.head.ref, capture_output=True, github_token=github_token)
    head = _git('rev-parse', 'FETCH_HEAD', capture_output=True).decode().strip()
    if head != pull.head.sha:
        raise ValueError('{}: branch changed during inspection; retry next pass'.format(failure))
    parents = _git('rev-list', '--parents', '-n', '1', head, capture_output=True).decode().split()
    if len(parents) != 2 or _git('merge-base', base, head, capture_output=True).decode().strip() != parents[1]:
        raise ValueError('{}: expected one promotion commit'.format(failure))
    parent = parents[1]
    paths = _git('diff', '--name-only', '--no-renames', parent, head, capture_output=True).decode().splitlines()
    if paths != [channel_path]:
        raise ValueError('{}: unexpected changed files'.format(failure))
    before = _git('show', '{}:{}'.format(parent, channel_path), capture_output=True).decode()
    after = _git('show', '{}:{}'.format(head, channel_path), capture_output=True).decode()
    data = _load_channel(before, channel_name)
    if version in data['versions']:
        raise ValueError('{}: expected a new version addition'.format(failure))
    data['versions'] = sorted(data['versions'] + [version], key=semver_sort_key)
    # Accept existing safe_dump-generated bot PRs as well as new minimal edits.
    expected = [yaml.safe_dump(data, default_flow_style=False)]
    try:
        expected.append(add_version(before, version, channel_name))
    except ValueError:
        pass
    if after not in expected or _git('diff', '--summary', parent, head, capture_output=True):
        raise ValueError('{}: branch contains unexpected edits'.format(failure))
    message = _git('cat-file', 'commit', head, capture_output=True).split(b'\n\n', 1)[1]
    name, email, date = _git('show', '-s', '--format=%an%x00%ae%x00%aI', head, capture_output=True).decode().rstrip('\n').split('\0')
    commit = _promotion_commit(base, channel_path, add_version(content, version, channel_name), message,
                               author={'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email, 'GIT_AUTHOR_DATE': date})
    _git('push', '--force-with-lease=refs/heads/{}:{}'.format(pull.head.ref, head), push_uri,
         '{}:refs/heads/{}'.format(commit, pull.head.ref), capture_output=True, github_token=github_token)
    return PullRequest(pull.html_url, action='repaired')


def promote(version, channel_name, channel_path, subject, body, upstream_github_repo, push_github_repo, github_token, upstream_branch, labels=None):
    if not github_token:
        # Preserve the local generation mode used by release management scripts.
        with open(channel_path) as stream:
            data = yaml.safe_load(stream)
        if version in data['versions']:
            raise ValueError('version {} has already been promoted to {}'.format(version, channel_name))
        data['versions'] = sorted(set(data['versions']) | {version}, key=semver_sort_key)
        with open(channel_path, 'w') as stream:
            yaml.safe_dump(data, stream, default_flow_style=False)
        return PullRequest('data://no-token-so-no-pull')
    if github is None:
        raise github_import_error

    upstream_remote = get_remote(repo=upstream_github_repo)
    _git('fetch', '--no-tags', upstream_remote, upstream_branch)
    base = _git('rev-parse', 'FETCH_HEAD', capture_output=True).decode().strip()
    content = _git('show', '{}:{}'.format(base, channel_path), capture_output=True).decode()
    if version in _load_channel(content, channel_name)['versions']:
        return PullRequest('', action='already-present')

    branch = 'promote-{}-to-{}'.format(version, channel_name)
    owner = push_github_repo.split('/')[0]
    client = github.Github(github_token)
    repo = client.get_repo(upstream_github_repo)
    query = {'head': '{}:{}'.format(owner, branch), 'base': upstream_branch}
    pulls = list(repo.get_pulls(state='open', **query))
    push_uri = _push_uri(push_github_repo, github_token)
    if pulls:
        if len(pulls) != 1:
            raise ValueError('multiple matching promotion PRs; human review required')
        pull = pulls[0]
        # PyGithub may refresh all PR fields lazily when reading mergeability.
        # Materialize those fields before validating the current PR identity.
        mergeable, mergeable_state = pull.mergeable, pull.mergeable_state
        if (pull.state != 'open' or
                pull.head.repo is None or pull.head.repo.full_name != push_github_repo or
                pull.head.ref != branch or pull.base.ref != upstream_branch or
                pull.user.login != client.get_user().login):
            raise ValueError('{}: unexpected PR state, target, or ownership; human review required'.format(pull.html_url))
        if mergeable is not False or mergeable_state != 'dirty':
            return PullRequest(pull.html_url, action='waiting')
        try:
            return _repair_promotion(pull, base, content, version, channel_name, channel_path, push_uri, github_token=github_token)
        except subprocess.CalledProcessError as exc:
            raise ValueError('{}: repair failed during git {}; the branch may have changed or access may be unavailable; retry next pass'.format(
                pull.html_url, exc.cmd[1])) from exc
        except ValueError as exc:
            if pull.html_url in str(exc):
                raise
            raise ValueError('{}: {}'.format(pull.html_url, exc)) from exc

    closed = next(iter(repo.get_pulls(state='closed', **query)), None)
    if closed:
        raise ValueError('{}: promotion PR is closed; human review required'.format(closed.html_url))
    if _git('ls-remote', '--heads', push_uri, 'refs/heads/' + branch, capture_output=True, github_token=github_token):
        raise ValueError('branch {} exists without an open PR; human review required'.format(branch))
    message = '{}\n\n{}\n'.format(subject, textwrap.fill(body, width=76)).encode()
    commit = _promotion_commit(base, channel_path, add_version(content, version, channel_name), message)
    # An empty expected SHA means the branch must still not exist at push time.
    _git('push', '--force-with-lease=refs/heads/{}:'.format(branch), push_uri,
         '{}:refs/heads/{}'.format(commit, branch), capture_output=True, github_token=github_token)
    try:
        pull = repo.create_pull(title=subject, body=body, head=query['head'], base=upstream_branch, maintainer_can_modify=True)
    except Exception:
        try:
            _git('push', '--force-with-lease=refs/heads/{}:{}'.format(branch, commit), push_uri,
                 ':refs/heads/' + branch, capture_output=True, github_token=github_token)
        except Exception:
            # Do not expose credential-bearing Git commands or mask the API error.
            _LOGGER.warning('failed to clean up promotion branch %s after PR creation failed; human review may be required', branch)
        raise
    if labels:
        pull.add_to_labels(*labels)
    return PullRequest(pull.html_url)


def sanitize(err, github_token=None):
    if github_token is None:
        return err
    return str(err).replace(github_token, 'REDACTED')


def semver_sort_key(version):
    # Precedence is defined in https://semver.org/spec/v2.0.0.html#spec-item-11
    identifiers = _SEMANTIC_VERSION_DELIMITERS.sub(' ', version)
    ids = []
    for indx, identifier in enumerate(identifiers.split()):
        if indx < 3:
            try:
                identifier = int(identifier)
            except ValueError:
                pass
        ids.append(identifier)
    return tuple(ids)


def get_remote(repo):
    remote = _REMOTE_CACHE.get(repo)
    if remote is not None:
        return remote

    process = subprocess.run(['git', 'remote', '--verbose'], check=True, capture_output=True, text=True)
    for line in process.stdout.strip().split('\n'):
        match = _GIT_REMOTE_LINE_REGEXP.match(line)
        if not match:
            _LOGGER.info('ignoring unrecognized remote line syntax: {}'.format(line))
            continue
        data = match.groupdict()
        if data['host'] != 'github.com':
            _LOGGER.info('ignoring non-GitHub remote host {}: {}'.format(data['host'], line))
            continue
        line_repo = '{org}/{repo}'.format(**data)
        if line_repo not in _REMOTE_CACHE:
            _REMOTE_CACHE[line_repo] = data['remote']
            _LOGGER.info('caching remote {} for {}'.format(data['remote'], line_repo))

    return _REMOTE_CACHE[repo]


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description=(
            'Check for stabilization changes as versions are promoted from feeder channels. '
            'With a GitHub token, create promotion PRs or repair confirmed merge conflicts '
            'in existing PRs opened by the authenticated bot. Repair requires one commit '
            'containing only the expected channel/version addition; unexpected edits, '
            'closed PRs, and branches without an open PR require human review. '
            'Repair preserves upstream content, the original commit message and author, '
            'and PR metadata, and uses an expected-head lease to protect concurrent edits. '
            'Clean PRs and PRs with unknown mergeability are left waiting. Creation and '
            'repair are notified immediately; waiting status is reported on the daily '
            'notification schedule. Without a token, update local channel YAML only.'
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--poll',
        metavar='SECONDS',
        type=int,
        help='Seconds to wait after each stabilization pass finishes.  By default runs a single round of stabilization changes.',
        default=None,
    )
    parser.add_argument(
        '--upstream-github-repo',
        dest='upstream_github_repo',
        metavar='REPO',
        help='Automatically create promotion pull requests in the GitHub repository (requires --github-token).',
        default="openshift/cincinnati-graph-data",
    )
    parser.add_argument(
        '--push-github-repo',
        dest='push_github_repo',
        metavar='REPO',
        help='Automatically create promotion branches in the GitHub repository (requires --github-token and --upstream-github-repo).  Defaults to --upstream-github-repo.',
    )
    parser.add_argument(
        '--github-token',
        dest='github_token',
        metavar='TOKEN',
        help='GitHub token for pull request creation ( https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token ). Defaults to the value of the GITHUB_TOKEN environment variable.',
        default=os.environ.get('GITHUB_TOKEN', ''),
    )
    parser.add_argument(
        '--labels',
        nargs='*',
        help='Set these labels on newly created pull request.  For example: "--labels lgtm approved".',
    )
    parser.add_argument(
        '--webhook',
        metavar='URI',
        help='Set this to actually push notifications to Slack.  Defaults to the value of the WEBHOOK environment variable.',
        default=os.environ.get('WEBHOOK', ''),
    )

    args = parser.parse_args()

    next_notification = datetime.datetime.now()
    while True:
        waiting_notifications = False
        if datetime.datetime.now() > next_notification:
            waiting_notifications = True
            next_notification += datetime.timedelta(hours=24)  # don't flood notifications

        upstream_branch = 'master'
        upstream_github_repo = args.upstream_github_repo.strip()

        if args.poll:
            upstream_remote = get_remote(repo=upstream_github_repo)
            subprocess.run(['git', 'fetch', upstream_remote], check=True)
            subprocess.run(['git', 'checkout', '{}/{}'.format(upstream_remote, upstream_branch)], check=True)
        stabilization_changes(
            directories={'channels', 'internal-channels'},
            upstream_github_repo=upstream_github_repo,
            push_github_repo=(args.push_github_repo or upstream_github_repo).strip(),
            github_token=args.github_token.strip() or None,
            labels=args.labels,
            webhook=args.webhook.strip(),
            waiting_notifications=waiting_notifications,
            upstream_branch=upstream_branch,
        )
        if args.poll:
            _LOGGER.info('sleeping {} seconds before reconsidering promotions'.format(args.poll))
            time.sleep(args.poll)
        else:
            break


if __name__ == '__main__':
    main()
