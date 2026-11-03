#!/usr/bin/env python3
"""reviewloop GitHub integration — review a pull request where it
lives.

Read path (works without a token on public repos): fetch the PR's
metadata and unified diff from the GitHub API and run the review
loop on the diff.

Write path (needs GITHUB_TOKEN with access to the repo): post the
report as a PR review comment and set a commit status on the PR
head — `reviewloop` context: success (gate pass), failure
(blocked), pending (inconclusive). Review events are COMMENT by
default; --request-changes opts into REQUEST_CHANGES on a blocked
gate. The bot never auto-approves.

Tokens come from the environment only, are never logged, and
authenticated requests refuse redirects (same rules as providers).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from . import providers as _providers
from .core import run_review, run_verification

_API = "https://api.github.com"
_PR_URL_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)")


class GitHubError(Exception):
    pass


def parse_pr_url(url):
    m = _PR_URL_RE.match((url or "").strip())
    if not m:
        raise GitHubError(f"not a GitHub PR URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))


class GitHubClient:
    def __init__(self, token=None, base=_API, opener=None):
        self.token = token if token is not None \
            else os.environ.get("GITHUB_TOKEN", "").strip()
        self.base = base.rstrip("/")
        self._opener = opener or urllib.request.build_opener(
            _providers._NoRedirect())

    def _request(self, method, path, accept="application/vnd.github+json",
                 payload=None):
        headers = {"Accept": accept,
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "reviewloop"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=120) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            raise GitHubError(
                f"GitHub API {method} {path}: HTTP {e.code} {detail}"
            ) from e
        except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
            raise GitHubError(f"GitHub API network error: {e}") from e

    def get_pr(self, owner, repo, number):
        raw = self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise GitHubError(f"bad PR payload: {e}") from e

    def get_pr_diff(self, owner, repo, number):
        return self._request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}",
            accept="application/vnd.github.diff")

    def post_review(self, owner, repo, number, body, event="COMMENT"):
        raw = self._request(
            "POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            payload={"body": body, "event": event})
        return json.loads(raw) if raw.strip() else {}

    def set_status(self, owner, repo, sha, state, description,
                   target_url=None):
        payload = {"state": state, "context": "reviewloop",
                   "description": description[:140]}
        if target_url:
            payload["target_url"] = target_url
        raw = self._request(
            "POST", f"/repos/{owner}/{repo}/statuses/{sha}",
            payload=payload)
        return json.loads(raw) if raw.strip() else {}


_GATE_STATUS = {"pass": "success", "blocked": "failure",
                "inconclusive": "pending"}


def render_pr_comment(report, owner, repo, number):
    """The PR-visible summary of a report (Markdown)."""
    gate = report["gate"].upper()
    icon = {"PASS": "✅", "BLOCKED": "⛔",
            "INCONCLUSIVE": "⚠️"}.get(gate, "")
    lines = [f"## {icon} ReviewLoop gate: **{gate}**",
             "",
             "; ".join(report.get("gate_reasons") or []), ""]
    def cell(text):
        return (str(text or "").replace("|", "/")
                .replace("\r", " ").replace("\n", " "))

    findings = [f for f in report.get("findings") or []]
    if findings:
        lines.append("| Severity | File | Finding | Reviewer(s) |")
        lines.append("|---|---|---|---|")
        for f in findings:
            who = ", ".join(f.get("sources") or [])
            lines.append(f"| {f['severity']} | {cell(f.get('file'))} "
                         f"| {cell(f.get('title'))} | {who} |")
        lines.append("")
    if report.get("mode") == "verify":
        lines.append(f"Cleared: {len(report.get('cleared') or [])} · "
                     f"Still open: {len(report.get('remaining') or [])}")
        lines.append("")
    if report.get("degraded"):
        lines.append("_Degraded round: at least one reviewer failed "
                     "(see the full report)._\n")
    lines.append(f"ReviewLoop {report.get('version')} · "
                 f"revision `{report.get('patch_sha256', '')[:12]}` · "
                 f"PR #{number}")
    return "\n".join(lines)


def review_pr(client, owner, repo, number, reviewer_providers,
              post=False, request_changes=False, previous=None,
              builder_response="", test_results=None, strict=False,
              allow_major=False):
    """Fetch a PR, review (or verify) its diff, optionally post.

    Returns (report, actions) where actions records what was posted.
    """
    pr = client.get_pr(owner, repo, number)
    diff = client.get_pr_diff(owner, repo, number)
    if not diff.strip():
        raise GitHubError("the PR diff is empty")
    head_sha = ((pr.get("head") or {}).get("sha") or "")
    context = (f"GitHub PR {owner}/{repo}#{number}: "
               f"{pr.get('title') or ''}\n"
               f"Author: {(pr.get('user') or {}).get('login') or ''}\n"
               f"{(pr.get('body') or '')[:1500]}")
    if previous is not None:
        report = run_verification(
            diff, reviewer_providers, previous, builder_response,
            test_results=test_results or [], allow_major=allow_major,
            strict=strict)
    else:
        report = run_review(
            diff, reviewer_providers, context=context,
            test_results=test_results or [], allow_major=allow_major,
            strict=strict)
    report["pr"] = {"owner": owner, "repo": repo, "number": number,
                    "head_sha": head_sha, "title": pr.get("title") or ""}
    actions = []
    if post:
        if not client.token:
            raise GitHubError("--post needs GITHUB_TOKEN")
        event = "COMMENT"
        if request_changes and report["gate"] == "blocked":
            event = "REQUEST_CHANGES"
        body = render_pr_comment(report, owner, repo, number)
        client.post_review(owner, repo, number, body, event=event)
        actions.append(f"review comment posted (event={event})")
        if head_sha:
            state = _GATE_STATUS.get(report["gate"], "pending")
            desc = ("; ".join(report.get("gate_reasons") or [])
                    or report["gate"])
            client.set_status(owner, repo, head_sha, state, desc)
            actions.append(f"commit status set: reviewloop={state}")
    return report, actions
