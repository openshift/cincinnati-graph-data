import datetime
import errata
import github
import http
import json
import os
import re
import tempfile
import unittest
import urllib
from collections import namedtuple
from unittest.mock import MagicMock
from unittest.mock import patch

# Mocking classes of PyGithub
GitUser = namedtuple("GitUser", "login")
GitLabel = namedtuple("GitLabel", "name")
class GithubRepoPrMock:
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
        if not isinstance(other, GithubRepoPrMock):
            return False
        return      self.user == other.user     \
                and self.title == other.title   \
                and self.labels == other.labels \
                and self.number == other.number \
                and self.body == other.body     \
                and self.url == other.url       \
                and self.html_url == other.html_url

class ExtractErrataNumberFromBodyTest(unittest.TestCase):
    def test_valid_url(self):
        """
        Test errata number extraction from valid URLs.
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
            ('http://errata.devel.redhat.com/advisory/12345', None),
            ('https://errrata.devel.redhat.com/advisory/12345', None),
            ('https://errata.dvel.reddhat.com/advisori/12345', None),
            ('https://errata.devel.redhat.com/12345', None),
            ('https://errata.devel.com/advisory/12345', None),
            ('https://errata.redhat.com/advisory/12345', None),
            ('https://devel.redhat.com/advisory/12345', None),
            ('https://redhat.com/advisory/12345', None),
            ('https://errata.com/advisory/12345', None)
        ]
        for (url, expected) in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), expected)


    def test_missing_url(self):
        """
        Test errata number extraction from missing URLs.
        """
        param_list = [
            ('errata', None),
            ('12345', None),
            ('errata is 12345', None)
        ]
        for (url, expected) in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), expected)


    def test_url_is_not_on_the_first_line(self):
        """
        Test errata number extraction from valid URLs which are not located on the first line.
        """
        param_list = [
            ('\nhttps://errata.devel.redhat.com/advisory/12345', None),
            ('\n\nhttps://errata.devel.redhat.com/advisory/12345', None),
        ]
        for (url, expected) in param_list:
            with self.subTest():
                self.assertEqual(errata.extract_errata_number_from_body(url), expected)


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


class ErrataTest(unittest.TestCase):
    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_poll_params_of_url(self, urlopen_mock, json_load_mock):
        urlopen_mock.return_value = MagicMock()

        # Mocked response from API
        raw_messages = []
        json_load_mock.return_value = {
            "raw_messages": raw_messages,
            "pages": 1
        }

        # Call errata.poll function
        polled_messages = []
        poll_period = datetime.timedelta(seconds=3600)
        for message in errata.poll(period=poll_period):
            polled_messages.append(message)

        #Get arguments of urlib.request.urlopen call inside errata.poll
        urlopen_called_with_args = urlopen_mock.call_args
        # Get params of the url
        url = re.search(r"call\(\'(.*)\'\)", str(urlopen_called_with_args)).group(1)
        parsed_url = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed_url.query)

        # Assert if parameters complies with datagrepper reference
        self.assertGreater(int(params["page"][0]), 0)               # Page must be greater than 0
        self.assertLessEqual(int(params["rows_per_page"][0]), 100)  # Must be less than or equal to 100
        self.assertEqual(params["category"][0], "errata")           # Should only look for errata category
        self.assertEqual(params["contains"][0], "RHOSE")            # Only messages containing RHOSE


    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_poll_number_of_returned_pages_is_zero(self, urlopen_mock, json_load_mock):
        urlopen_mock.return_value = MagicMock()

        raw_messages = []
        json_load_mock.return_value = {
            "raw_messages": raw_messages,
            "pages": 0
        }

        polled_messages = []
        poll_period = datetime.timedelta(seconds=3600)
        for message in errata.poll(period=poll_period):
            polled_messages.append(message)

        # Test if data was polled correctly
        self.assertEqual(polled_messages, [])


    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_poll_no_results(self, urlopen_mock, json_load_mock):
        urlopen_mock.return_value = MagicMock()

        raw_messages = []
        json_load_mock.return_value = {
            "raw_messages": raw_messages,
            "pages": 1
        }

        polled_messages = []
        poll_period = datetime.timedelta(seconds=3600)
        for message in errata.poll(period=poll_period):
            polled_messages.append(message)

        # Test if data was polled correctly
        self.assertEqual(polled_messages, [])


    @patch("json.load")
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_poll_unresponsive_url_becomes_responsive(self, urlopen_mock, sleep_mock, json_load_mock):
        # First time calling request.urlopen returns Exception, 
        # second time returns mocked HTTPResponse
        urlopen_mock.side_effect = [
        Exception("Unresponsive, request.urlopen has failed"), MagicMock()]
        raw_messages = [
            {
                "msg": {
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                }
            }
        ]
        json_load_mock.return_value = {
            "raw_messages": raw_messages,
            "pages": 1
        }

        # Retrive messages from errata.poll
        poll_period = datetime.timedelta(seconds=3600)
        polled_messages = []
        for message in errata.poll(period=poll_period):
            polled_messages.append(message)

        # Test if data was polled correctly
        expected_messages = [x['msg'] for x in raw_messages]
        self.assertEqual(expected_messages, polled_messages)

        # URL wasn't responsive only once, so sleep should be called only once
        sleep_mock.assert_called_once()


    @patch("json.load")
    @patch("urllib.request.urlopen")
    def test_poll_multiple_messages(self, urlopen_mock, json_load_mock):
        urlopen_mock.return_value = MagicMock()
        raw_messages = [
            {
                "additional_necessary_info": "shouldn't be processed",
                "msg": {
                    "errata_id": 1,
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                }
            },
            {
                "additional_necessary_info": "shouldn't be processed",
                "msg": {
                    "errata_id": 2,
                    "product": "RHOSE",
                    "to": "QE",
                }
            },
            {
                "additional_necessary_info": "shouldn't be processed",
                "msg": {
                    "errata_id": 3,
                    "product": "RHEL",
                    "to": "SHIPPED_LIVE",
                }
            },
            {
                "additional_necessary_info": "shouldn't be processed",
                "msg": {
                    "errata_id": 4,
                    "product": "RHEL",
                    "to": "QE",
                }
            },
            {
                "additional_necessary_info": "shouldn't be processed",
                "msg": {
                    "errata_id": 5,
                    "product": "RHOSE",
                    "to": "SHIPPED_LIVE",
                }
            }
        ]
        expected_messages = [
           {
                "errata_id": 1,
                "product": "RHOSE",
                "to": "SHIPPED_LIVE",
            },
            {
                "errata_id": 5,
                "product": "RHOSE",
                "to": "SHIPPED_LIVE",
            }
        ]
        json_load_mock.return_value = {
            "raw_messages": raw_messages,
            "pages": 1
        }
        # Retrive messages from errata.poll
        poll_period = datetime.timedelta(seconds=3600)
        polled_messages = []
        for message in errata.poll(period=poll_period):
            polled_messages.append(message)
        # Test if data was polled correctly
        self.assertEqual(expected_messages, polled_messages)


    @patch("builtins.print")
    @patch("urllib.request.urlopen")
    def test_notify_no_webhook(self, urlopen_mock, print_mock):
        input_msgs = [
            {
                "errata_id": 1,
                "product": "RHOSE",
                "to": "SHIPPED_LIVE",
            },
            {
                "errata_id": 5,
                "product": "RHOSE",
                "to": "SHIPPED_LIVE",
            }
        ]
        errata.notify(message=input_msgs)
        self.assertEqual(print_mock.call_args, (unittest.mock.call(input_msgs)))

        input_msgs = [
            {
                "errata_id": 3,
                "product": "RHEL",
                "to": "SHIPPED_LIVE",
            },
        ]
        errata.notify(message=input_msgs)
        self.assertEqual(print_mock.call_args, (unittest.mock.call(input_msgs)))

        input_msgs = [
            {
                "errata_id": 4,
                "product": "RHEL",
                "to": "QE",
            },
        ]
        errata.notify(message=input_msgs)
        self.assertEqual(print_mock.call_args, (unittest.mock.call(input_msgs)))


    @patch("urllib.request.urlopen")
    def test_notify_format_of_message_pr_not_approved(self, urlopen_mock):
        message = {
            "fulladvisory": "RHEL",
            "when": "today",
            "synopsis": "OpenShift Container Platform X.X.X",
            "uri": "example_uri"
        }

        errata.notify(message, True)

        msg_text = '<!subteam^STE7S7ZU2>: {fulladvisory} shipped {when}: {synopsis} {uri}'.format(**message)
        expected_data = urllib.parse.urlencode({
            'payload': {
                'text': msg_text,
            },
        }).encode('utf-8')
        self.assertEqual(urlopen_mock.call_args[1]["data"], expected_data)


    @patch("urllib.request.urlopen")
    def test_notify_format_of_message_pr_approved(self, urlopen_mock):
        message = {
            "fulladvisory": "RHEL",
            "when": "today",
            "synopsis": "OpenShift Container Platform X.X.X",
            "uri": "example_uri",
            "approved_pr": "example_approved"
        }

        errata.notify(message, True)

        msg_text = '<!subteam^STE7S7ZU2>: {fulladvisory} shipped {when}: {synopsis} {uri}'.format(**message)
        msg_text += "\nPR {approved_pr} has been approved".format(**message)

        expected_data = urllib.parse.urlencode({
            'payload': {
                'text': msg_text,
            },
        }).encode('utf-8')
        self.assertEqual(urlopen_mock.call_args[1]["data"], expected_data)


    def test_get_open_prs_to_fast_labels_not_lgtmed(self):
        # Create multiple groups of label(s)
        labels_empty = []
        labels_bug = [GitLabel("bug")]
        labels_duplicate = [GitLabel("duplicate")]
        labels_enhancement = [GitLabel("enhancement")]
        labels_multiple = [GitLabel("bug"), GitLabel("duplicate"), GitLabel("documentation")]

        # Mock Pullrequests in a repository
        prs = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channel(s)", labels_empty, 1))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable GHI in fast channel(s)", labels_bug, 2))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channel(s)", labels_duplicate, 3))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channel(s)", labels_enhancement, 4))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable MNO in fast channel(s)", labels_multiple, 5))

        # Mock repo.get_pulls used in errata.get_open_prs_to_fast
        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        get_prs = []
        for pr in errata.get_open_prs_to_fast(repo):
            get_prs.append(pr)

        self.assertEqual(get_prs, prs)


    def test_get_open_prs_to_fast_labels_lgtmed(self):
        # Create multiple groups of label(s) including 'lgtm' at different indexes
        labels_only_lgtm = [GitLabel("lgtm")]
        labels_lgtm_index_0 = [GitLabel("lgtm"), GitLabel("bug")]
        labels_lgtm_index_1 = [GitLabel("duplicate"), GitLabel("lgtm")]
        labels_lgtm_index_2 = [GitLabel("bug"), GitLabel("duplicate"), GitLabel("lgtm"), GitLabel("documentation")]
        labels_lgtm_index_last = [GitLabel("enhancement"), GitLabel("bug"), GitLabel("fix"), GitLabel("lgtm")]

        prs = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channels", labels_only_lgtm, 1))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channels", labels_lgtm_index_0, 2))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable GHI in fast channels", labels_lgtm_index_1, 3))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channels", labels_lgtm_index_2, 4))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable MNO in fast channels", labels_lgtm_index_last, 5))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        get_prs = []
        for pr in errata.get_open_prs_to_fast(repo):
            get_prs.append(pr)

        self.assertEqual(get_prs, [])


    def test_get_open_prs_to_fast_user_login(self):
        labels_empty = []
        prs = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channels", labels_empty, 1))
        prs.append(GithubRepoPrMock(GitUser("openshift-user"), "Enable DEF in fast channels", labels_empty, 2))
        prs.append(GithubRepoPrMock(GitUser("user1234"), "Enable GHI in fast channels", labels_empty, 3))
        prs.append(GithubRepoPrMock(GitUser("abcdefgh"), "Enable JKL in fast channels", labels_empty, 4))
        prs.append(GithubRepoPrMock(GitUser("bot-openshift"), "Enable MNO in fast channels", labels_empty, 5))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        get_prs = []
        for pr in errata.get_open_prs_to_fast(repo):
            get_prs.append(pr)

        self.assertEqual(get_prs, [GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channels", labels_empty, 1)])


    def test_get_open_prs_to_fast_channel(self):
        labels_empty = []
        prs = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in stable channel(s)", labels_empty, 1))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable GHI in candidate channel(s)", labels_empty, 2))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in candidate channel(s)", labels_empty, 3))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channel(s)", labels_empty, 4))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable MNO in stable channel(s)", labels_empty, 5))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        get_prs = []
        for pr in errata.get_open_prs_to_fast(repo):
            get_prs.append(pr)

        self.assertEqual(get_prs, [GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channel(s)", labels_empty, 4)])


    def test_get_open_prs_to_fast_title(self):
        labels_empty = []
        prs = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Disable ABC in fast channel(s)", labels_empty, 1))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Fix GHI in fast channel(s)", labels_empty, 2))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channel(s)", labels_empty, 3))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Disable DEF in fast channel(s)", labels_empty, 4))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Add features in fast channel(s)", labels_empty, 5))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        get_prs = []
        for pr in errata.get_open_prs_to_fast(repo):
            get_prs.append(pr)

        self.assertEqual(get_prs, [GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channel(s)", labels_empty, 3)])


    def test_get_open_prs_to_fast_query_params(self):
        prs = []

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        get_prs = []
        for pr in errata.get_open_prs_to_fast(repo):
            get_prs.append(pr)

        query_params_expected = {
            'state': 'open',
            'base': 'master',
            'sort': 'created',
        }
        self.assertEqual(repo.get_pulls.call_args, (unittest.mock.call(**query_params_expected)))


    @patch("github.Github")
    def test_lgtm_fast_pr_for_errata_test_return_value(self, Github_mock):
        prs = []
        labels_empty = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channel(s)", labels_empty, 1, "https://errata.devel.redhat.com/advisory/1234", "pr_url_1234", "pr_html_url_1234"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable GHI in fast channel(s)", labels_empty, 2, "https://errata.devel.redhat.com/advisory/2345", "pr_url_2345", "pr_html_url_2345"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channel(s)", labels_empty, 3, "https://errata.devel.redhat.com/advisory/3456", "pr_url_3456", "pr_html_url_3456"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channel(s)", labels_empty, 4, "https://errata.devel.redhat.com/advisory/4567", "pr_url_4567", "pr_html_url_4567"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable MNO in fast channel(s)", labels_empty, 5, "https://errata.devel.redhat.com/advisory/5678", "pr_url_5678", "pr_html_url_5678"))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        github_object_mock = MagicMock()
        github_object_mock.get_repo.return_value = repo
        Github_mock.return_value = github_object_mock

        githubrepo = MagicMock()
        githubtoken = MagicMock()
        message = {
            "errata_id" : 5678,
        }

        html = errata.lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)
        self.assertEqual(html, "pr_html_url_5678")


    @patch("github.Github")
    def test_lgtm_fast_pr_for_errata_test_creating_issue(self, Github_mock):
        # Mock Pullrequests in a repository
        prs = []
        labels_empty = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channel(s)", labels_empty, 1, "https://errata.devel.redhat.com/advisory/1234", "pr_url_1234", "pr_html_url_1234"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable GHI in fast channel(s)", labels_empty, 2, "https://errata.devel.redhat.com/advisory/2345", "pr_url_2345", "pr_html_url_2345"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channel(s)", labels_empty, 3, "https://errata.devel.redhat.com/advisory/3456", "pr_url_3456", "pr_html_url_3456"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channel(s)", labels_empty, 4, "https://errata.devel.redhat.com/advisory/4567", "pr_url_4567", "pr_html_url_4567"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable MNO in fast channel(s)", labels_empty, 5, "https://errata.devel.redhat.com/advisory/5678", "pr_url_5678", "pr_html_url_5678"))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        github_object_mock = MagicMock()
        github_object_mock.get_repo.return_value = repo
        Github_mock.return_value = github_object_mock

        githubrepo = MagicMock()
        githubtoken = MagicMock()
        message = {
            "errata_id" : 5678,
        }

        errata.lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)
        prs[0].create_issue_comment.assert_not_called()
        prs[1].create_issue_comment.assert_not_called()
        prs[2].create_issue_comment.assert_not_called()
        prs[3].create_issue_comment.assert_not_called()
        prs[4].create_issue_comment.assert_called_once()


    @patch("github.Github")
    def test_lgtm_fast_pr_for_errata_test_issue_format(self, Github_mock):
        # Mock Pullrequests in a repository
        prs = []
        labels_empty = []
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable ABC in fast channel(s)", labels_empty, 1, "https://errata.devel.redhat.com/advisory/1234", "pr_url_1234", "pr_html_url_1234"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable GHI in fast channel(s)", labels_empty, 2, "https://errata.devel.redhat.com/advisory/2345", "pr_url_2345", "pr_html_url_2345"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable JKL in fast channel(s)", labels_empty, 3, "https://errata.devel.redhat.com/advisory/3456", "pr_url_3456", "pr_html_url_3456"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable DEF in fast channel(s)", labels_empty, 4, "https://errata.devel.redhat.com/advisory/4567", "pr_url_4567", "pr_html_url_4567"))
        prs.append(GithubRepoPrMock(GitUser("openshift-bot"), "Enable MNO in fast channel(s)", labels_empty, 5, "https://errata.devel.redhat.com/advisory/5678", "pr_url_5678", "pr_html_url_5678"))

        repo = MagicMock()
        repo.get_pulls = MagicMock(return_value=prs)

        github_object_mock = MagicMock()
        github_object_mock.get_repo.return_value = repo
        Github_mock.return_value = github_object_mock

        githubrepo = MagicMock()
        githubtoken = MagicMock()
        message = {
            "errata_id" : 5678,
        }

        errata.lgtm_fast_pr_for_errata(githubrepo, githubtoken, message)

        msg = "Autoapproving PR to fast after the errata has shipped\n/lgtm"
        self.assertEqual(prs[4].create_issue_comment.call_args, (unittest.mock.call(msg)))