"""GitHub integration tests — fake transport, no network."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview.github import (GitHubClient, GitHubError, parse_pr_url,
                               render_pr_comment, review_pr)

PR_JSON = {"title": "Add the thing", "body": "does stuff",
           "user": {"login": "dev"}, "head": {"sha": "abc123def"}}
DIFF = ("diff --git a/app.py b/app.py\n"
        "--- a/app.py\n+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n x = 1\n+run_all_the_things()\n")


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Records requests; answers from canned routes."""

    def __init__(self):
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        path = req.full_url
        accept = req.get_header("Accept") or ""
        if req.method == "GET" and path.endswith("/pulls/7"):
            if "diff" in accept:
                return FakeResponse(DIFF)
            return FakeResponse(json.dumps(PR_JSON))
        if req.method == "POST" and "/reviews" in path:
            return FakeResponse('{"id": 11}')
        if req.method == "POST" and "/statuses/" in path:
            return FakeResponse('{"id": 12}')
        raise AssertionError(f"unexpected request {req.method} {path}")


def fake_reviewer(findings=None):
    """Core-level provider protocol: a callable prompt -> JSON text."""
    def fn(prompt):
        return json.dumps({"findings": findings or [],
                           "summary": "fake", "usage": {}})
    return fn


class HtmlPostOpener(FakeOpener):
    """POSTs answer 200 with an HTML body (captive portal /
    proxy), GETs behave as the canned routes."""

    def open(self, req, timeout=None):
        if req.method == "POST":
            self.requests.append(req)
            return FakeResponse("<html>captive portal</html>")
        return super().open(req, timeout=timeout)


class TestBadJsonPost(unittest.TestCase):
    """L6 F3: a non-JSON 2xx body on a POST must surface as
    GitHubError (which review_pr records in the report), never
    as a raw JSONDecodeError escaping with no record written —
    the failure P5-03 set out to prevent."""

    def test_post_review_bad_json_is_github_error(self):
        client = GitHubClient(token="t", opener=HtmlPostOpener())
        with self.assertRaises(GitHubError):
            client.post_review("octo", "hello", 7, "body")

    def test_set_status_bad_json_is_github_error(self):
        client = GitHubClient(token="t", opener=HtmlPostOpener())
        with self.assertRaises(GitHubError):
            client.set_status("octo", "hello", "abc123def",
                              "success", "ok")

    def test_review_pr_records_posting_error(self):
        client = GitHubClient(token="t", opener=HtmlPostOpener())
        report, _actions = review_pr(
            client, "octo", "hello", 7, {"fake": fake_reviewer()},
            post=True)
        self.assertIn("posting", report)
        self.assertTrue(report["posting"]["error"])


BLOCKER = [{"severity": "blocker", "file": "app.py", "line": 2,
            "rule": "", "title": "Unguarded mass action",
            "detail": "runs everything with no guard"}]


def _client(token="tok"):
    op = FakeOpener()
    return GitHubClient(token=token, opener=op), op


class TestParse(unittest.TestCase):
    def test_url(self):
        self.assertEqual(
            parse_pr_url("https://github.com/octo/hello/pull/42"),
            ("octo", "hello", 42))

    def test_bad_url(self):
        with self.assertRaises(GitHubError):
            parse_pr_url("https://example.com/nope")

    def test_number_must_end_the_url(self):
        # L6 F4: "12abc" used to parse silently as PR 12.
        with self.assertRaises(GitHubError):
            parse_pr_url("https://github.com/octo/hello/pull/12abc")

    def test_trailing_slash_ok(self):
        self.assertEqual(
            parse_pr_url("https://github.com/octo/hello/pull/42/"),
            ("octo", "hello", 42))

    def test_owner_repo_charset(self):
        # L6 F4: `?`, `#`, `%` in owner/repo used to flow into
        # the API path; a path suffix after the number likewise.
        for bad in ("https://github.com/oc?to/hello/pull/42",
                    "https://github.com/octo/hel#lo/pull/42",
                    "https://github.com/octo/hel%20lo/pull/42",
                    "https://github.com/octo/hello/pull/42/files"):
            with self.assertRaises(GitHubError, msg=bad):
                parse_pr_url(bad)


class TestClient(unittest.TestCase):
    def test_get_pr_and_diff(self):
        client, _ = _client()
        pr = client.get_pr("octo", "hello", 7)
        self.assertEqual(pr["head"]["sha"], "abc123def")
        self.assertIn("run_all_the_things",
                      client.get_pr_diff("octo", "hello", 7))

    def test_auth_header_sent(self):
        client, op = _client()
        client.get_pr("octo", "hello", 7)
        self.assertEqual(op.requests[0].get_header("Authorization"),
                         "Bearer tok")


class TestReviewPr(unittest.TestCase):
    def test_blocked_posts_comment_and_failure_status(self):
        client, op = _client()
        report, actions = review_pr(
            client, "octo", "hello", 7, {"fake": fake_reviewer(BLOCKER)},
            post=True, request_changes=True)
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(report["pr"]["head_sha"], "abc123def")
        self.assertEqual(len(actions), 2)
        posts = [r for r in op.requests if r.method == "POST"]
        review_body = json.loads(posts[0].data.decode())
        self.assertEqual(review_body["event"], "REQUEST_CHANGES")
        self.assertIn("BLOCKED", review_body["body"])
        status_body = json.loads(posts[1].data.decode())
        self.assertEqual(status_body["state"], "failure")
        self.assertEqual(status_body["context"], "codereview")

    def test_pass_posts_comment_event_and_success(self):
        client, op = _client()
        report, actions = review_pr(
            client, "octo", "hello", 7, {"fake": fake_reviewer()},
            post=True, request_changes=True)
        self.assertEqual(report["gate"], "pass")
        posts = [r for r in op.requests if r.method == "POST"]
        self.assertEqual(json.loads(posts[0].data.decode())["event"],
                         "COMMENT")
        self.assertEqual(json.loads(posts[1].data.decode())["state"],
                         "success")

    def test_post_without_token_refused(self):
        client, _ = _client(token="")
        with self.assertRaises(GitHubError):
            review_pr(client, "octo", "hello", 7, {"fake": fake_reviewer()},
                      post=True)

    def test_read_only_makes_no_posts(self):
        client, op = _client()
        report, actions = review_pr(
            client, "octo", "hello", 7, {"fake": fake_reviewer(BLOCKER)})
        self.assertEqual(report["gate"], "blocked")
        self.assertEqual(actions, [])
        self.assertFalse(any(r.method == "POST" for r in op.requests))


class TestRender(unittest.TestCase):
    def test_comment_shape(self):
        report = {"gate": "blocked", "gate_reasons": ["1 blocker"],
                  "findings": [{"severity": "blocker", "file": "a.py",
                                "title": "Bad | thing",
                                "sources": ["fake"]}],
                  "version": "0.4.0", "patch_sha256": "x" * 32}
        md = render_pr_comment(report, "o", "r", 3)
        self.assertIn("BLOCKED", md)
        self.assertIn("Bad / thing", md)  # pipe escaped for the table

    def test_comment_title_newlines_collapsed(self):
        report = {"gate": "pass", "gate_reasons": [],
                  "findings": [{"severity": "minor", "file": "a.py",
                                "title": "one\ntwo",
                                "sources": ["fake"]}],
                  "version": "0.4.0", "patch_sha256": "x" * 32}
        md = render_pr_comment(report, "o", "r", 3)
        self.assertIn("one two", md)


if __name__ == "__main__":
    unittest.main()
