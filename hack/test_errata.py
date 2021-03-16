import datetime
import os
import tempfile
import unittest
import urllib
from unittest.mock import MagicMock
from unittest.mock import patch

import errata


class GithubUserMock():
    def __init__(self, login):
        self.login = login


class GithubLabelMock():
    def __init__(self, name):
        self.name = name


class GithubPRMock:
    def __init__(self, user, title, labels=[], number=0, body="", url="", html_url=""):
        self.user = user
        self.title = title
        self.labels = labels
        self.number = number
        self.body = body
        self.url = url
        self.html_url = html_url
        self.create_issue_comment = MagicMock()

    def __eq__(self, other):
        if not isinstance(other, GithubPRMock):
            return False
        return self.user == other.user          \
            and self.title == other.title       \
            and self.labels == other.labels     \
            and self.number == other.number     \
            and self.body == other.body         \
            and self.url == other.url           \
            and self.html_url == other.html_url


class ExtractErrataNumberFromBodyTest(unittest.TestCase):
    def test_url_starting_with_valid_errata_marker(self):
        """
        Test errata number extraction from valid URLs.
        URLs starting with corresponding ERRATA_MARKER in errata.py.
        """
        param_list = [
            ('https://errata.devel.redhat.com/advisory/12345', 12345),
            ('https://errata.devel.redhat.com/advisory/67890', 67890),
            ('https://errata.devel.redhat.com/advisory/13579', 13579),
            ('https://errata.devel.redhat.com/advisory/24680', 24680),
            ('https://errata.devel.redhat.com/advisory/', None),
            ('https://errata.devel.redhat.com/advisory/invalid', None)
        ]
        for (url, expected) in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), expected)

    def test_invalid_url(self):
        """
        Test errata number extraction from invalid URLs.
        """
        param_list = [
            'http://errata.devel.redhat.com/advisory/12345',
            'https://errrata.devel.redhat.com/advisory/12345',
            'https://errata.dvel.reddhat.com/advisori/12345',
            'https://errata.devel.redhat.com/12345',
            'https://errata.devel.com/advisory/12345',
            'https://errata.redhat.com/advisory/12345',
            'https://devel.redhat.com/advisory/12345',
            'https://redhat.com/advisory/12345',
            'https://errata.com/advisory/12345'
        ]
        for url in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), None)

    def test_missing_url(self):
        """
        Test errata number extraction from missing URLs.
        """
        param_list = [
            'errata',
            '12345',
            'errata is 12345'
        ]
        for url in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), None)

    def test_url_is_not_on_the_first_line(self):
        """
        Test errata number extraction from valid URLs which are not located on the first line.
        """
        param_list = [
            '\nhttps://errata.devel.redhat.com/advisory/12345',
            '\n\nhttps://errata.devel.redhat.com/advisory/12345'
        ]
        for url in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), None)


class SaveAndLoadTest(unittest.TestCase):
    def test_load_nonexisting_file(self):
        """
        Test loading a nonexisting file.
        """
        with tempfile.TemporaryDirectory() as tempdir:
            cachepath = os.path.join(tempdir, "cache.json")
            self.assertCountEqual(errata.load(cachepath), {})

    def test_save_and_load_as_a_pair(self):
        """
        Test using errata.save and errata.load as a pair to confirm their functionality.
        """
        param_list = [
            (),
            ({"foo": "bar"}),
            ({"value": "1234"}),
            ({"company": "Red Hat"}),
            ({"foo": "bar"}, {"value": "1234"}, {"errata": "1234"}),
            ({"value": "1234"}, {"foo": "bar"}, {"errata": "1234"})
        ]
        for cache in param_list:
            with self.subTest():
                with tempfile.TemporaryDirectory() as tempdir:
                    cachepath = os.path.join(tempdir, "cache.json")
                    errata.save(cachepath, cache)
                    self.assertCountEqual(errata.load(cachepath), cache)


class PollTest(unittest.TestCase):
    def setUp(self):
        self.raw_messages = [
            (
                True,
                {
                    "additional_unnecessary_info": "shouldn't be processed",
                    "msg": {
                        "errata_id": 11,
                        "product": "RHOSE",
                        "to": "SHIPPED_LIVE",
                    }
                }
            ),
            (
                True,
                {
                    "additional_unnecessary_info": "shouldn't be processed",
                    "msg": {
                        "errata_id": 12,
                        "product": "RHOSE",
                        "to": "SHIPPED_LIVE",
                    }
                }
            ),
            (
                False,
                {
                    "additional_unnecessary_info": "shouldn't be processed",
                    "msg": {
                        "errata_id": 21,
                        "product": "RHOSE",
                        "to": "QE",
                    }
                }
            ),
            (
                False,
                {
                    "additional_unnecessary_info": "shouldn't be processed",
                    "msg": {
                        "errata_id": 22,
                        "product": "RHEL",
                        "to": "SHIPPED_LIVE",
                    }
                }
            ),
            (
                False,
                {
                    "additional_unnecessary_info": "shouldn't be processed",
                    "msg": {
                        "errata_id": 23,
                        "product": "RHEL",
                        "to": "QE",
                    }
                }
            ),
            (
                False,
                {
                    "additional_unnecessary_info": "shouldn't be processed",
                    "msg": {
                        "errata_id": 24,
                        "product": "SHIPPED_LIVE",
                        "to": "RHOSE",
                    }
                }
            )
        ]
        self.valid_messages = [x[1] for x in self.raw_messages if x[0]]
        self.invalid_messages = [x[1] for x in self.raw_messages if not x[0]]

    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_params_of_urlopen_call(self, urlopen_mock, json_load_mock):
        """
        Test parameters used in the data_grepper's url which is used for getting raw messages.
        """
        urlopen_mock.return_value = MagicMock()
        json_load_mock.return_value = {
            "raw_messages": [],
            "pages": 1
        }

        polled_messages = []
        for message in errata.poll(period=datetime.timedelta(seconds=3600)):
            polled_messages.append(message)

        # Get params of the url used in urlopen in errata.poll
        parsed_url = urllib.parse.urlparse(urlopen_mock.call_args[0][0])
        params = urllib.parse.parse_qs(parsed_url.query)

        # Assert if parameters complies with datagrepper reference
        self.assertGreater(int(params["page"][0]), 0)               # Page must be greater than 0
        self.assertLessEqual(int(params["rows_per_page"][0]), 100)  # Must be less than or equal to 100
        self.assertEqual(params["category"][0], "errata")           # Should only look for errata category
        self.assertEqual(params["contains"][0], "RHOSE")            # Only messages containing RHOSE

    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_number_of_returned_pages_is_zero(self, urlopen_mock, json_load_mock):
        """
        Test poll's functionality if returned data contains number of pages equal to zero.
        """
        urlopen_mock.return_value = MagicMock()
        json_load_mock.return_value = {
            "raw_messages": [],
            "pages": 0
        }

        polled_messages = []
        for message in errata.poll(period=datetime.timedelta(seconds=3600)):
            polled_messages.append(message)
        self.assertEqual(polled_messages, [])

    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_poll_no_raw_messages(self, urlopen_mock, json_load_mock):
        """
        Test polling messages if data doesn't contain any raw messages.
        """
        urlopen_mock.return_value = MagicMock()
        json_load_mock.return_value = {
            "raw_messages": [],
            "pages": 1
        }

        polled_messages = []
        for message in errata.poll(period=datetime.timedelta(seconds=3600)):
            polled_messages.append(message)
        self.assertEqual(polled_messages, [])

    @patch("json.load")
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_poll_unresponsive_url_becomes_responsive(self, urlopen_mock, sleep_mock, json_load_mock):
        """
        Test polling messages if request.urlopen throws exception on a first try.
        """
        urlopen_mock.side_effect = [
            Exception("Unresponsive, request.urlopen has failed"),
            MagicMock()
        ]
        json_load_mock.return_value = {
            "raw_messages": self.valid_messages,
            "pages": 1
        }

        polled_messages = []
        for message in errata.poll(period=datetime.timedelta(seconds=3600)):
            polled_messages.append(message)

        sleep_mock.assert_called_once()  # URL wasn't responsive only once, so time.sleep should have been called only once
        expected_msgs = [x['msg'] for x in self.valid_messages]
        self.assertEqual(polled_messages, expected_msgs)

    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_poll_multiple_messages(self, urlopen_mock, json_load_mock):
        """
        Test polling messages from raw messages that include wanted and unwanted messages.
        """
        urlopen_mock.return_value = MagicMock()
        messages = self.valid_messages + self.invalid_messages
        json_load_mock.return_value = {
            "raw_messages": messages,
            "pages": 1
        }

        polled_messages = []
        for message in errata.poll(period=datetime.timedelta(seconds=3600)):
            polled_messages.append(message)
        expected_msgs = [x['msg'] for x in self.valid_messages]
        self.assertEqual(polled_messages, expected_msgs)


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.messages_including_approved_pr = [
            (
                {
                    "errata_id": 11,
                    "fulladvisory": "RHSA-2020:0000-00",
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                    "synopsis": "OpenShift Container Platform 4.6 GA Images",
                    "when": "2021-01-01 12:00:00 UTC",
                    "uri": "Public_Errata_URI_11",
                    "approved_pr": "PR_HTML_URL_11"
                },
                '<!subteam^STE7S7ZU2>: '
                'RHSA-2020:0000-00 shipped '
                '2021-01-01 12:00:00 UTC: '
                'OpenShift Container Platform 4.6 GA Images '
                'Public_Errata_URI_11'
                '\nPR PR_HTML_URL_11 has been approved'
            ),
            (
                {
                    "errata_id": 12,
                    "fulladvisory": "RHSA-2020:2000-20",
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                    "synopsis": "Moderate: OpenShift Container Platform 4.5.20 bug fix and golang security update",
                    "when": "2021-01-02 13:00:00 UTC",
                    "uri": "Public_Errata_URI_12",
                    "approved_pr": "PR_HTML_URL_12"
                },
                '<!subteam^STE7S7ZU2>: '
                'RHSA-2020:2000-20 shipped '
                '2021-01-02 13:00:00 UTC: '
                'Moderate: OpenShift Container Platform 4.5.20 bug fix and golang security update '
                'Public_Errata_URI_12'
                '\nPR PR_HTML_URL_12 has been approved'
            )
        ]
        self.messages_not_including_approved_pr = [
            (
                {
                    "errata_id": 21,
                    "fulladvisory": "RHSA-2020:0000-00",
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                    "synopsis": "OpenShift Container Platform 4.6 GA Images",
                    "when": "2021-01-01 12:00:00 UTC",
                    "uri": "Public_Errata_URI_21",
                },
                '<!subteam^STE7S7ZU2>: '
                'RHSA-2020:0000-00 shipped '
                '2021-01-01 12:00:00 UTC: '
                'OpenShift Container Platform 4.6 GA Images '
                'Public_Errata_URI_21'
            ),
            (
                {
                    "errata_id": 22,
                    "fulladvisory": "RHSA-2020:2000-20",
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                    "synopsis": "Moderate: OpenShift Container Platform 4.5.20 bug fix and golang security update",
                    "when": "2021-01-02 13:00:00 UTC",
                    "uri": "Public_Errata_URI_22",
                },
                '<!subteam^STE7S7ZU2>: '
                'RHSA-2020:2000-20 shipped '
                '2021-01-02 13:00:00 UTC: '
                'Moderate: OpenShift Container Platform 4.5.20 bug fix and golang security update '
                'Public_Errata_URI_22'
            )
        ]
        self.messages =                                 \
            self.messages_including_approved_pr +       \
            self.messages_not_including_approved_pr

    @patch("builtins.print")
    @patch("urllib.request.urlopen")
    def test_no_webhook(self, urlopen_mock, print_mock):
        """
        Test functionality of notify if parameter webhook is set to its default value.
        """
        for message in self.messages:
            with self.subTest():
                errata.notify(message[0])
                expected_message = message[0]
                self.assertEqual(print_mock.call_args, unittest.mock.call(expected_message))

    @patch("urllib.request.urlopen")
    def test_format_of_message_not_including_approved_pr(self, urlopen_mock):
        """
        Test format of data passed as argument to request.urlopen in errata.get_open_prs_to_fast.
        This tests encoded format of the message in data as well.
        Only testing messages including approved_pr key.
        """
        for (message, expected_message_in_data_to_be_uploaded) in self.messages_not_including_approved_pr:
            with self.subTest():
                expected_data_to_be_uploaded = urllib.parse.urlencode({
                    'payload': {
                        'text': expected_message_in_data_to_be_uploaded
                    }
                }).encode('utf-8')

                errata.notify(message, MagicMock())
                uploaded_data = urlopen_mock.call_args[1]['data']
                self.assertEqual(uploaded_data, expected_data_to_be_uploaded)

    @patch("urllib.request.urlopen")
    def test_format_of_message_including_approved_pr(self, urlopen_mock):
        """
        Test format of data passed as argument to request.urlopen in errata.get_open_prs_to_fast.
        This tests encoded format of the message in data as well.
        Only testing messages that do not include approved_pr key.
        """
        for (message, expected_message_in_data_to_be_uploaded) in self.messages_including_approved_pr:
            with self.subTest():
                expected_data_to_be_uploaded = urllib.parse.urlencode({
                    'payload': {
                        'text': expected_message_in_data_to_be_uploaded
                    }
                }).encode('utf-8')

                errata.notify(message, MagicMock())
                uploaded_data = urlopen_mock.call_args[1]['data']
                self.assertEqual(uploaded_data, expected_data_to_be_uploaded)


class GetOpenPRsToFastTest(unittest.TestCase):
    def setUp(self):
        self.repo = MagicMock()
        self.labels_multiple_including_lgtm = [
            [
                GithubLabelMock('lgtm')
            ],
            [
                GithubLabelMock('bug'), GithubLabelMock('duplicate'), GithubLabelMock('lgtm'),
                GithubLabelMock('documentation'), GithubLabelMock('invalid')
            ],
            [
                GithubLabelMock('wontfix'), GithubLabelMock('lgtm'),
                GithubLabelMock('question'), GithubLabelMock('invalid')
            ],
            [
                GithubLabelMock('help wanted'), GithubLabelMock('lgtm'),
                GithubLabelMock('good first issue'), GithubLabelMock('bug')
            ]
        ]
        self.labels_multiple_not_including_lgtm = [
            [
            ],
            [
                GithubLabelMock('wontfix'), GithubLabelMock('bug'),
                GithubLabelMock('question'), GithubLabelMock('invalid')
            ],
            [
                GithubLabelMock('help wanted'), GithubLabelMock('invalid'),
                GithubLabelMock('good first issue'), GithubLabelMock('duplicate')
            ],
            [
                GithubLabelMock('bug'), GithubLabelMock('duplicate'), GithubLabelMock('invalid'),
                GithubLabelMock('documentation'), GithubLabelMock('enhancement')
            ]
        ]
        self.prs_correct_and_expected_to_be_yielded = [
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.6.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_not_including_lgtm[0]),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_not_including_lgtm[1]),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_not_including_lgtm[2]),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_not_including_lgtm[3]),
        ]
        self.prs_including_the_lgtm_label = [
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_including_lgtm[0]),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_including_lgtm[1]),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_including_lgtm[2]),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", self.labels_multiple_including_lgtm[3])
        ]
        self.prs_author_is_not_openshift_bot = [
            GithubPRMock(GithubUserMock("user1234"), "Enable 4.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("bot-openshift"), "Enable 4.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("Openshift-Bot"), "Enable 4.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("GitHubUser1234"), "Enable 4.0.0 in fast channel(s)")
        ]
        self.prs_title_not_starting_with_Enable = [
            GithubPRMock(GithubUserMock("openshift-bot"), ""),
            GithubPRMock(GithubUserMock("openshift-bot"), "Fix component"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Add features in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "enable 4.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Disable 4.0.0 in fast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enablee 4.0.0 in fast channel(s)")
        ]
        self.prs_do_not_target_fast = [
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable "),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in FAST channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in faast channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in stable channel(s)"),
            GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in candidate channel(s)")
        ]

    def test_prs_including_the_lgtm_label(self):
        """
        Test retrieving PRs which include the LGTM label. These PRs should be skipped.
        """
        self.repo.get_pulls = MagicMock(return_value=self.prs_including_the_lgtm_label)

        open_prs_to_fast = []
        for pr in errata.get_open_prs_to_fast(self.repo):
            open_prs_to_fast.append(pr)

        expected_prs = []
        self.assertEqual(open_prs_to_fast, expected_prs)

    def test_prs_author_is_not_openshift_bot(self):
        """
        Test getting PRs whose author is not openshift-bot. These PRs should be skipped.
        """
        self.repo.get_pulls = MagicMock(return_value=self.prs_author_is_not_openshift_bot)

        open_prs_to_fast = []
        for pr in errata.get_open_prs_to_fast(self.repo):
            open_prs_to_fast.append(pr)

        expected_prs = []
        self.assertEqual(open_prs_to_fast, expected_prs)

    def test_unknown_prs_should_be_skipped(self):
        """
        Test getting unknown PRs. These PRs should be skipped.
        """
        self.repo.get_pulls = MagicMock(return_value=self.prs_title_not_starting_with_Enable)

        open_prs_to_fast = []
        for pr in errata.get_open_prs_to_fast(self.repo):
            open_prs_to_fast.append(pr)

        expected_prs = []
        self.assertEqual(open_prs_to_fast, expected_prs)

    def test_ignore_prs_which_dont_target_fast(self):
        """
        Test getting PRs which don't target fast. These PRs should be skipped.
        """
        self.repo.get_pulls = MagicMock(return_value=self.prs_do_not_target_fast)

        open_prs_to_fast = []
        for pr in errata.get_open_prs_to_fast(self.repo):
            open_prs_to_fast.append(pr)

        expected_prs = []
        self.assertEqual(open_prs_to_fast, expected_prs)

    def test_correct_prs_should_be_yielded(self):
        """
        Test getting PRs which are correct and should be yielded back.
        """
        self.repo.get_pulls = MagicMock(return_value=self.prs_correct_and_expected_to_be_yielded)

        open_prs_to_fast = []
        for pr in errata.get_open_prs_to_fast(self.repo):
            open_prs_to_fast.append(pr)

        expected_prs = self.prs_correct_and_expected_to_be_yielded
        self.assertEqual(open_prs_to_fast, expected_prs)

    def test_get_pulls_query_params(self):
        """
        Test query params used for getting the initial PRs from the repository.
        """
        self.repo.get_pulls = MagicMock(return_value=[])

        open_prs_to_fast = []
        for pr in errata.get_open_prs_to_fast(self.repo):
            open_prs_to_fast.append(pr)

        expected_params = {
            'state': 'open',
            'base': 'master',
            'sort': 'created',
        }
        self.assertEqual(self.repo.get_pulls.call_args, (unittest.mock.call(**expected_params)))


class LgtmFastPrForErrata(unittest.TestCase):
    def setUp(self):
        self.repo = MagicMock()
        self.github_object_mock = MagicMock()
        self.github_object_mock.get_repo.return_value = self.repo
        self.prs_with_html_url_of_expected_pr = [
            (
                [
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)", [], 1, "https://errata.devel.redhat.com/advisory/1111", "PR_URL1", "PR_HTML_URL1"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", [], 2, "https://errata.devel.redhat.com/advisory/1234", "PR_URL2", "PR_HTML_URL2"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)", [], 3, "https://errata.devel.redhat.com/advisory/5678", "PR_URL3", "PR_HTML_URL3"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)", [], 4, "https://errata.devel.redhat.com/advisory/1357", "PR_URL4", "PR_HTML_URL4")
                ],
                {
                    "errata_id": 1357
                },
                "PR_HTML_URL4"  # HTML url of a PR which body has the wanted errata id.
            ),
            (
                [
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)", [], 12345, "https://errata.devel.redhat.com/advisory/41", "PR_URL12345", "PR_HTML_URL12345"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", [], 12354, "https://errata.devel.redhat.com/advisory/42", "PR_URL12354", "PR_HTML_URL12354"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)", [], 12340, "https://errata.devel.redhat.com/advisory/43", "PR_URL12340", "PR_HTML_URL12340"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)", [], 43215, "https://errata.devel.redhat.com/advisory/44", "PR_URL43215", "PR_HTML_URL43215")
                ],
                {
                    "errata_id": 41
                },
                "PR_HTML_URL12345"
            ),
            (
                [
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)", [], 1111, "https://errata.devel.redhat.com/advisory/51", "PR_URL1111", "PR_HTML_URL1111"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", [], 2222, "https://errata.devel.redhat.com/advisory/62", "PR_URL2222", "PR_HTML_URL2222"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)", [], 3333, "https://errata.devel.redhat.com/advisory/73", "PR_URL3333", "PR_HTML_URL3333"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)", [], 4444, "https://errata.devel.redhat.com/advisory/84", "PR_URL4444", "PR_HTML_URL4444")
                ],
                {
                    "errata_id": 73
                },
                "PR_HTML_URL3333"
            )
        ]
        self.prs_with_index_of_expected_pr = [
            (
                [
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)", [], 1, "https://errata.devel.redhat.com/advisory/1111", "PR_URL1", "PR_HTML_URL1"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", [], 2, "https://errata.devel.redhat.com/advisory/1234", "PR_URL2", "PR_HTML_URL2"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)", [], 3, "https://errata.devel.redhat.com/advisory/5678", "PR_URL3", "PR_HTML_URL3"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)", [], 4, "https://errata.devel.redhat.com/advisory/1357", "PR_URL4", "PR_HTML_URL4")
                ],
                {
                    "errata_id": 1357
                },
                3   # Index of the PR which has the wanted errata id.
            ),
            (
                [
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)", [], 12345, "https://errata.devel.redhat.com/advisory/41", "PR_URL12345", "PR_HTML_URL12345"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", [], 12354, "https://errata.devel.redhat.com/advisory/42", "PR_URL12354", "PR_HTML_URL12354"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)", [], 12340, "https://errata.devel.redhat.com/advisory/43", "PR_URL12340", "PR_HTML_URL12340"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)", [], 43215, "https://errata.devel.redhat.com/advisory/44", "PR_URL43215", "PR_HTML_URL43215")
                ],
                {
                    "errata_id": 41
                },
                0
            ),
            (
                [
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 3.0.0 in fast channel(s)", [], 1111, "https://errata.devel.redhat.com/advisory/51", "PR_URL1111", "PR_HTML_URL1111"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.0.0 in fast channel(s)", [], 2222, "https://errata.devel.redhat.com/advisory/62", "PR_URL2222", "PR_HTML_URL2222"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.1.2 in fast channel(s)", [], 3333, "https://errata.devel.redhat.com/advisory/73", "PR_URL3333", "PR_HTML_URL3333"),
                    GithubPRMock(GithubUserMock("openshift-bot"), "Enable 4.2.3 in fast channel(s)", [], 4444, "https://errata.devel.redhat.com/advisory/84", "PR_URL4444", "PR_HTML_URL4444")
                ],
                {
                    "errata_id": 73
                },
                2
            )
        ]

    @patch("github.Github")
    def test_return_value_is_correct_for_specific_pr(self, Github_mock):
        """
        Test retrieving the HTML url of a PR which is related to a specific errata id.
        """
        githubrepo = MagicMock()
        githubtoken = MagicMock()
        Github_mock.return_value = self.github_object_mock
        param_list = self.prs_with_html_url_of_expected_pr

        for (prs, message, expected_pr_html_url) in param_list:
            with self.subTest():
                self.repo.get_pulls = MagicMock(return_value=prs)

                pr_html_url = errata.lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)
                self.assertEqual(pr_html_url, expected_pr_html_url)

    @patch("github.Github")
    def test_only_create_issue_on_the_expected_pr(self, Github_mock):
        """
        Test creating an issue comment only on the PR which is related to the specific errata id.
        """
        githubrepo = MagicMock()
        githubtoken = MagicMock()
        Github_mock.return_value = self.github_object_mock
        param_list = self.prs_with_index_of_expected_pr

        for (prs, message, expected_index_of_pr_to_create_issue) in param_list:
            self.repo.get_pulls = MagicMock(return_value=prs)
            errata.lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)

            for index, pr in enumerate(prs):
                with self.subTest():
                    if index == expected_index_of_pr_to_create_issue:
                        pr.create_issue_comment.assert_called_once()
                    else:
                        pr.create_issue_comment.assert_not_called()

    @patch("github.Github")
    def test_issue_comment_format(self, Github_mock):
        """
        Test the format of the created issue comment on the PR which is related to the specific errata id.
        """
        githubrepo = MagicMock()
        githubtoken = MagicMock()
        Github_mock.return_value = self.github_object_mock
        param_list = self.prs_with_index_of_expected_pr

        for (prs, message, expected_index_of_pr_to_create_issue) in param_list:
            with self.subTest():
                self.repo.get_pulls = MagicMock(return_value=prs)
                errata.lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)

                issue_comment = prs[expected_index_of_pr_to_create_issue].create_issue_comment.call_args
                expected_issue_comment = "Autoapproving PR to fast after the errata has shipped\n/lgtm"
                self.assertEqual(issue_comment, (unittest.mock.call(expected_issue_comment)))


if __name__ == '__main__':
    unittest.main()
