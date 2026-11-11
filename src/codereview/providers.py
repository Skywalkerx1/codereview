#!/usr/bin/env python3
"""codereview providers — build reviewer callables from API keys.

A provider is a callable: prompt (str) -> raw model text (str).
Keys are read from environment variables only; nothing is stored,
logged, or written to disk by this module. Redirects are refused on
authenticated requests.

Presets: the registry in registry.py (openai, gemini, anthropic,
         deepseek, minimax, moonshot, nvidia, xai, mistral,
         openrouter), each also as preset:model to pick the model.
Custom:  name|openai-compatible|https://base.url/v1|model|KEY_ENV
         name|gemini|-|model|KEY_ENV
         name|anthropic|-|model|KEY_ENV
         openai-compatible:<base>|<model>|<KEY_ENV (escape hatch)
Local:   local:<name>:<base-url>|<model> — a named local model
         server (Epic L5), plus the registry's local presets
         (ollama, lmstudio). Keyless: no key env is read and no
         Authorization header is sent — the endpoint is the
         user's own machine. Family tag 'local'.
Agent:   agent:<name>:<command> — a local agent CLI (Claude Code,
         Codex, Gemini CLI, a wrapper script, ...) seated as a
         reviewer or solver. The prompt is written to a temp file
         whose path is in $CODEREVIEW_PROMPT and also piped to the
         command's stdin; the agent's stdout is the response. The
         command line is split like a shell line (shlex) and run
         WITHOUT a shell — pipes and redirects belong in a wrapper
         script. The command is operator-supplied — the same trust
         level as the loop's --builder-cmd — and is never taken
         from a repo or a diff under review.
"""

from __future__ import annotations

import datetime
import http.client
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from types import ModuleType

try:
    from . import seatstate
except ImportError:  # standalone module load
    import seatstate  # type: ignore

try:
    from . import herdrhost
except ImportError:  # standalone module load
    import herdrhost  # type: ignore

_discovery: ModuleType | None
try:
    from . import discovery as _discovery
except ImportError:  # standalone module load
    try:
        import discovery as _discovery  # type: ignore
    except ImportError:
        _discovery = None

DEFAULT_TIMEOUT = 240
AGENT_TIMEOUT = 900

# Herdr watch discipline (P4-07): a failed pane poll is an event
# break, reconciled via snapshot — but a herdr that keeps
# failing the poll while the snapshot stays healthy must not be
# polled at full loop pace forever. Consecutive pane-get
# failures back off exponentially from the loop pace to the
# cap, and a bounded streak of them ends the seat with the
# recorded herdr-unreachable outcome.
_HERDR_GET_BACKOFF_BASE_S = 0.05
_HERDR_GET_BACKOFF_CAP_S = 2.0
_HERDR_GET_MAX_FAILURES = 20


class ProviderError(Exception):
    """A provider/seat failure. `retryable` tells the account pool
    whether rotating to another account could help: True/False when
    the failure class is known (quota vs. a local agent command that
    will fail identically on every account), None to fall back to
    the message heuristics in is_retryable.

    `kind` is the typed failure kind when the failure class is
    known at the raise site (today: "empty" — the provider
    answered with an empty content channel, the content-class
    failure the bench generation layer re-draws; see
    bench/generation.py). `retry_after` carries the server's
    Retry-After hint in seconds when one was sent, for the retry
    layer to honour as a delay floor (P4-01)."""

    def __init__(self, message, retryable=None, kind=None,
                 retry_after=None):
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ProviderError("redirect refused on authenticated request")


# Response discipline for _post_json (Phase 4 failure injection):
# an HTTP error's body is read (bounded) so the retry classifier
# can see the provider's own error codes (P4-01); the whole call
# lives under ONE deadline derived from `timeout`, not urllib's
# per-socket-operation timeout, so a slow-trickle endpoint cannot
# hold a seat past it (P4-02); a success body is streamed under a
# hard size cap instead of being buffered unbounded (P4-03); and
# transport garbage — malformed JSON, non-UTF-8 bytes, a body
# truncated in transit — is raised as ProviderError with a
# transient reading, never as a raw decode/parse error the retry
# layer would mistake for a model-output failure (P4-04).
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_ERROR_BODY_BYTES = 64 * 1024


def _retry_after_seconds(headers):
    """The Retry-After header as a delay in seconds, or None.
    Both wire forms (RFC 9110): a delay in seconds, or an
    HTTP-date (converted against now; a past date means no
    wait). An unparseable header is no hint at all."""
    raw = None
    if headers is not None:
        try:
            raw = headers.get("Retry-After")
        except Exception:  # noqa: BLE001 — header containers vary
            raw = None
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, (when - datetime.datetime.now(
        datetime.timezone.utc)).total_seconds())


def _read_response_body(resp, deadline, host, timeout):
    """Stream a response body under the call's overall deadline
    and the size cap. read1() performs at most one socket read
    per call, so a trickling endpoint is re-checked against the
    deadline after every byte instead of once per buffer-fill.
    The per-socket timeout urllib set still bounds any single
    silent stretch; this deadline bounds the whole body."""
    chunks = []
    total = 0
    declared = None
    try:
        declared = int(resp.headers.get("Content-Length"))
    except (TypeError, ValueError):
        declared = None
    while True:
        if time.monotonic() > deadline:
            raise ProviderError(
                f"response from {host} did not finish within "
                f"{timeout:g}s overall (temporary transport "
                f"timeout)")
        try:
            chunk = resp.read1(65536)
        except http.client.HTTPException as e:
            raise ProviderError(
                f"response body from {host} broke in transit "
                f"(temporary transport failure): {e}") from e
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise ProviderError(
                f"response body from {host} exceeded the "
                f"{_MAX_RESPONSE_BYTES}-byte cap (temporary "
                f"transport failure)")
        chunks.append(chunk)
    if declared is not None and total < declared:
        raise ProviderError(
            f"response body from {host} was truncated: {total} "
            f"of {declared} bytes arrived (temporary transport "
            f"failure)")
    return b"".join(chunks)


def _post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT):
    host = url.split("/")[2]
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = _read_response_body(
                resp, time.monotonic() + timeout, host, timeout)
    except urllib.error.HTTPError as e:
        # The provider's error body carries the class-deciding
        # codes (insufficient_quota, RESOURCE_EXHAUSTED, ...):
        # read it (bounded, tolerant of a broken error body) and
        # carry an excerpt in the error, so _classify_error's
        # quota rules can fire for API seats exactly as they do
        # for agent seats (P4-01).
        excerpt = ""
        try:
            raw = e.read(_ERROR_BODY_BYTES + 1)
            excerpt = raw[:_ERROR_BODY_BYTES].decode(
                "utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 — an unreadable error
            excerpt = ""      # body must not mask the status
        msg = f"HTTP {e.code} from {host}"
        if excerpt:
            # The body is provider-controlled text that lands in
            # the record and report: redact secret-shaped values
            # (an auth error can echo the key it rejected) before
            # it enters the message (P4-01b). Redact the whole
            # excerpt first, then truncate, so a secret cannot
            # straddle the cut.
            try:
                from . import core as _core
                excerpt = _core.redact_secrets(excerpt)
            except Exception:  # noqa: BLE001 — never mask status
                excerpt = ""
            msg += f": {excerpt[:2000]}"
        raise ProviderError(
            msg, retry_after=_retry_after_seconds(
                getattr(e, "headers", None)
                or getattr(e, "hdrs", None))) from e
    except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
        raise ProviderError(f"network error: {e}") from e
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ProviderError(
            f"response body from {host} is not valid UTF-8 "
            f"(temporary transport failure): {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ProviderError(
            f"response body from {host} is not valid JSON "
            f"(temporary transport failure): {e}") from e


def _post(url, headers, payload, timeout):
    """_post_json under the factory timeout convention: `timeout`
    None keeps _post_json's own default (DEFAULT_TIMEOUT), so the
    default lives in exactly one place; a value bounds the call
    overall (P4-02)."""
    if timeout is None:
        return _post_json(url, headers, payload)
    return _post_json(url, headers, payload, timeout=timeout)


def _key(key_env):
    key = os.environ.get(key_env, "").strip()
    if not key:
        raise ProviderError(f"{key_env} is not set")
    return key


_SYSTEM = ("You are an independent, strict code reviewer in a multi-model "
           "review loop. Output only the JSON object the user prompt "
           "asks for.")

_SOLVER_SYSTEM = ("You are the solver in a software-maintenance "
                  "workflow. You turn an issue report into an "
                  "executable solution plan in Markdown. You never "
                  "write the fix yourself; a builder implements your "
                  "plan and an independent review gates the result.")


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_secure_base_url(base_url, key_env):
    """An authenticated endpoint must speak HTTPS (security
    fix 0.13.2, audit G).

    A keyed provider used to accept any scheme, so a
    plaintext http:// base URL sent the operator's bearer
    credential — and every prompt — unencrypted. Keyless
    seats send no credential and are untouched; http:// is
    still allowed for loopback hosts, where the traffic
    never leaves the machine (a keyed loopback server keeps
    working)."""
    if key_env is None:
        return
    parsed = urllib.parse.urlparse(base_url or "")
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" \
            and (parsed.hostname or "").lower() in _LOOPBACK_HOSTS:
        return
    raise ProviderError(
        f"refusing an authenticated provider at "
        f"{base_url!r}: the credential from {key_env} would "
        "be sent without TLS — use an https:// base URL "
        "(http:// is allowed only for loopback hosts)")


def openai_compatible(base_url, model, key_env, extra_payload=None,
                      system=_SYSTEM, omit_temperature=False,
                      completion_tokens=False, timeout=None):
    """Callable for any OpenAI-compatible chat completions endpoint.

    `omit_temperature` drops the temperature field entirely for
    models whose API rejects a caller-set value (registry quirk
    table — e.g. OpenAI's gpt-5 line answers HTTP 400); the field
    is omitted, never replaced with a fabricated default.

    `completion_tokens` sends the token cap as
    `max_completion_tokens` instead of `max_tokens`, for models
    whose API rejects the old name (registry quirk table — the
    same gpt-5 / o-series lines answer HTTP 400 to `max_tokens`;
    the L3 smoke's first pass failed on exactly this, the openai
    preset's default model being gpt-5-mini). Models outside the
    quirk table keep `max_tokens` — several compatible endpoints
    require it.

    `key_env` None is the keyless local form (Epic L5): no
    credential is read and NO Authorization header is sent — the
    endpoint is a model server on the user's own machine, which
    expects none. Keyed callers are untouched: same header, same
    _key failure when the env var is unset.

    Construction refuses a non-HTTPS base URL whenever a
    credential is attached (security fix 0.13.2, audit G —
    see _require_secure_base_url)."""
    _require_secure_base_url(base_url, key_env)

    def call(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            ("max_completion_tokens" if completion_tokens
             else "max_tokens"): 8192,
        }
        if not omit_temperature:
            payload["temperature"] = 0.1
        if extra_payload:
            payload.update(extra_payload)
        headers = {} if key_env is None else {
            "Authorization": f"Bearer {_key(key_env)}"}
        data = _post(
            base_url.rstrip("/") + "/chat/completions",
            headers, payload, timeout)
        try:
            text = (data["choices"][0]["message"].get("content")
                    or "").strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model",
                                kind="empty")
        return text
    return call


def gemini(model, key_env="GEMINI_API_KEY", system=_SYSTEM,
           json_mode=True, timeout=None):
    """Callable for the Gemini generateContent API.

    json_mode (the reviewer default) asks the API for a JSON body;
    solver callables pass json_mode=False because their answer is a
    Markdown plan, not a JSON object."""
    def call(prompt):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        generation = {"temperature": 0.1, "maxOutputTokens": 8192}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation,
        }
        data = _post(url, {"x-goog-api-key": _key(key_env)},
                     payload, timeout)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model",
                                kind="empty")
        return text
    return call


def anthropic(model, key_env="ANTHROPIC_API_KEY", system=_SYSTEM,
              timeout=None):
    """Callable for the Anthropic Messages API (native wire shape:
    x-api-key + anthropic-version headers, system as a top-level
    field, the answer in content blocks)."""
    def call(prompt):
        payload = {
            "model": model,
            "max_tokens": 8192,
            "temperature": 0.1,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": _key(key_env),
             "anthropic-version": "2023-06-01"}, payload, timeout)
        try:
            text = "".join(
                b.get("text", "") for b in data["content"]
                if b.get("type") == "text").strip()
        except (KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model",
                                kind="empty")
        return text
    return call


MAX_AGENT_OUTPUT = 1_000_000

# The only variables an agent seat inherits by default. Everything
# else in the operator's environment — above all every provider API
# key and token — stays out of the agent process unless the operator
# explicitly opts a name in via CODEREVIEW_AGENT_ENV (comma-separated).
_AGENT_ENV_BASE = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
    "USER", "LOGNAME", "SHELL",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC",
)


def _agent_env(prompt_path):
    # By design (v0.7.0 external review requirement; review-v14
    # finding [14] asked for the intent to be visible here): an
    # agent seat NEVER inherits the operator's provider API keys or
    # tokens by default — it authenticates as itself, with its own
    # account. The allow-list above is the whole inheritance; the
    # only way in for anything else is an explicit operator opt-in
    # via CODEREVIEW_AGENT_ENV.
    names = [n for n in _AGENT_ENV_BASE if n in os.environ]
    extra = [n.strip() for n in
             os.environ.get("CODEREVIEW_AGENT_ENV", "").split(",")
             if n.strip()]
    env = {n: os.environ[n] for n in names + extra if n in os.environ}
    env["CODEREVIEW_PROMPT"] = prompt_path
    return env


def _kill_tree(proc, pgid=None):
    """Kill the agent's whole process group (it was started in its
    own session), so no orphaned grandchildren survive — called on
    timeout AND after a normal exit (an agent may leave daemons
    behind; v0.7.1 external review, finding 3.2). A group that is
    already gone is not an error."""
    try:
        if os.name == "posix":
            os.killpg(pgid if pgid is not None
                      else os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


MAX_AGENT_FILE = 8 * 1024 * 1024


def _limit_files():
    """preexec_fn (POSIX): cap the size of any file the agent
    writes, so a runaway agent cannot fill the disk while its
    output is being captured (finding 3.3). The child dies with
    SIGXFSZ past the cap; the read side keeps the verdict tail."""
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE,
                       (MAX_AGENT_FILE, MAX_AGENT_FILE))


def _read_tail(path, limit):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(-limit, os.SEEK_END)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _run_seat_process(proc, pgid, prompt, timeout, out_path,
                      err_path, cli_key, log, stall_after,
                      block_grace):
    """Supervised wait for one agent-seat process (Epic K2).

    Feeds the prompt on a writer thread (a seat may never read
    stdin; a blocked pipe must not stall supervision), polls the
    capture files for output activity, and returns an outcome
    dict: {"kind": "exit"} when the process ended on its own
    (returncode set); {"kind": "timeout", "facts": ...} when the
    per-call ceiling killed it (facts classify blocked/stalled
    when the seat had been silent past the stall bound, else
    timed-out); {"kind": "blocked", "facts": ...} when a
    verified failure pattern matched on stderr and output then
    stayed silent for the whole grace bound — the seat is stuck
    on a condition it cannot recover from by waiting, so it is
    terminated early instead of burning the full timeout. Live
    stall episodes are emitted to `log` (the job's SeatStateLog)
    as they happen; the terminal classification itself is the
    caller's, taken from the outcome's facts."""

    def _feed():
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    threading.Thread(target=_feed, daemon=True).start()

    def _size(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return -1

    started = time.monotonic()
    deadline = started + timeout
    last_size = _size(out_path) + _size(err_path)
    last_activity = started
    stalled = False
    matched = None
    while True:
        if proc.poll() is not None:
            # A seat's final write can land in the same poll as
            # its exit: an open stall episode still closes, so
            # the trace never ends on a stall the seat recovered
            # from by answering.
            if stalled and log is not None and (
                    _size(out_path) + _size(err_path) != last_size):
                log.emit("working")
            return {"kind": "exit"}
        now = time.monotonic()
        size = _size(out_path) + _size(err_path)
        if size != last_size:
            last_size = size
            last_activity = now
            if stalled:
                stalled = False
                if log is not None:
                    log.emit("working")
        silent = now - last_activity
        if log is not None and not stalled \
                and silent >= stall_after:
            stalled = True
            log.emit("blocked", "stalled",
                     {"silent_s": round(silent, 1),
                      "stall_after_s": stall_after,
                      "transient": True})
        if matched is None and cli_key is not None:
            matched = seatstate.match_failure(
                cli_key, _read_tail(err_path, 8192))
        if matched is not None and silent >= block_grace:
            _kill_tree(proc, pgid)
            proc.wait()
            return {"kind": "blocked", "facts": {
                "state": "blocked", "class": matched["class"],
                "evidence": {"pattern": matched["pattern"],
                             "matched": matched["matched"],
                             "source": "stderr",
                             "early_terminated": True,
                             "silent_s": round(silent, 1)}}}
        if now >= deadline:
            _kill_tree(proc, pgid)
            proc.wait()
            if silent >= stall_after:
                facts = {"state": "blocked", "class": "stalled",
                         "evidence": {
                             "silent_s": round(silent, 1),
                             "timeout_s": timeout}}
            else:
                facts = {"state": "timed-out", "class": None,
                         "evidence": {"timeout_s": timeout}}
            return {"kind": "timeout", "facts": facts}
        time.sleep(0.05)


def _redact_tail(text):
    """Redact secret-shaped values from a seat's stderr tail
    before the tail is quoted into a ProviderError (P4-01b,
    audit extension): the error message is persisted into the
    record verbatim, and a seat's stderr can echo a key just
    as a provider's error body can — a CLI explaining an auth
    failure is exactly where that happens. On any redaction
    failure the tail is dropped rather than quoted raw:
    diagnostics are expendable, secrets are not."""
    try:
        from . import core as _core
        return _core.redact_secrets(text)
    except Exception:  # noqa: BLE001 — never quote it raw
        return ""


def _hosted_outcome_error(outcome, timeout, block_grace):
    """The ProviderError a hosted seat's non-exit outcome maps
    to — the headless messages, verbatim, plus seat_facts, so a
    hosted failure reads exactly like its headless twin in the
    record (the hosting receipt carries the transport facts)."""
    if outcome["kind"] == "timeout":
        err = ProviderError(
            f"agent command timed out after {timeout}s",
            retryable=False)
        err.seat_facts = outcome["facts"]
        return err
    if outcome["kind"] == "blocked":
        facts = outcome["facts"]
        err = ProviderError(
            f"agent command blocked ({facts['class']}): "
            f"matched {facts['evidence']['pattern']} on "
            f"stderr; no output for {block_grace:g}s — "
            f"terminated early", retryable=False)
        err.seat_facts = facts
        return err
    # kind == "herdr-failure": the transport died under the
    # seat (herdr exited, the pane vanished, the session was
    # restarted). A recorded seat failure — never a retry under
    # a new pane inside this attempt, never a silent resume.
    err = ProviderError(
        f"herdr hosting failed ({outcome['stage']}): "
        f"{outcome['detail']}", retryable=False)
    err.seat_facts = {
        "state": "failed", "class": "error",
        "evidence": {"stage": outcome["stage"],
                     "transport": "herdr",
                     "detail": outcome["detail"][:300]}}
    return err


def _run_hosted_seat(host, receipt, pane_id, out_path, err_path,
                     rc_path, cli_key, log, timeout, stall_after,
                     block_grace):
    """Supervised wait for one herdr-hosted seat (Epic K3a).

    The headless wait supervises OUR subprocess; here the
    process lives in a herdr pane, so the truth is recovered
    from the same artefacts the headless runner reads — the
    capture files (activity, stderr patterns, the response)
    plus the exit-code file the pane command writes when the
    seat command finishes. Herdr's agent_status is polled as
    the wrapper-layer subscription (see herdrhost.py): it
    annotates the receipt and may raise an ADVISORY
    blocked:input episode in the seat-state log; it never
    decides the outcome. A failed poll is an event break
    (events_lost at the socket layer): reconcile via
    session.snapshot — same pane, same terminal_id, or the
    seat fails. Consecutive poll failures back off
    exponentially (P4-07) and a bounded streak of them, with
    reconciliation still proving the session healthy, ends
    the seat as herdr-unreachable. Returns the headless
    outcome shapes ({"kind": "exit", "returncode": N} /
    "timeout" / "blocked") plus {"kind": "herdr-failure",
    ...}."""

    def _size(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return -1

    def _rc():
        try:
            with open(rc_path, encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            return None

    started = time.monotonic()
    deadline = started + timeout
    last_size = _size(out_path) + _size(err_path)
    last_activity = started
    stalled = False
    matched = None
    last_status = None
    advisory_blocked = False
    terminal_id = None
    get_failures = 0
    pace = _HERDR_GET_BACKOFF_BASE_S

    def _observe(pane, via):
        """Fold one pane observation into the receipt (+ the
        advisory log episodes). Returns a herdr-failure
        outcome when the observation proves the session was
        restarted under the seat, else None."""
        nonlocal last_status, advisory_blocked, terminal_id
        if not isinstance(pane, dict):
            return None
        tid = pane.get("terminal_id")
        if tid is not None:
            if terminal_id is None:
                terminal_id = tid
                receipt["terminal_id"] = tid
            elif tid != terminal_id:
                return {"kind": "herdr-failure",
                        "stage": "session-restarted",
                        "detail": "the pane's terminal changed "
                        "mid-run (herdr restarted); a resumed "
                        "session is never silently continued"}
        status = pane.get("agent_status")
        if status is not None and status != last_status:
            last_status = status
            observations = receipt.setdefault("observations", [])
            if len(observations) < 100:
                observations.append({
                    "at_ms": int((time.monotonic() - started)
                                 * 1000),
                    "agent_status": status, "via": via})
            if log is not None:
                if status == "blocked" and not advisory_blocked:
                    advisory_blocked = True
                    # K2 signal #4: herdr's blocked is an
                    # approval/question UI — in a non-
                    # interactive seat that is an input wait.
                    # Advisory only: non-terminal, and process
                    # truth (the files) still decides the seat.
                    log.emit("blocked", "input", {
                        "source": "herdr",
                        "herdr_status": "blocked",
                        "advisory": True})
                elif status != "blocked" and advisory_blocked:
                    advisory_blocked = False
                    log.emit("working", None, {
                        "source": "herdr",
                        "herdr_status": status,
                        "advisory": True})
        return None

    def _reconcile():
        """After an event break: session.snapshot is the
        documented recovery. Returns None when the snapshot
        proves the same pane under the same terminal (the
        watch resumes), else the seat-failure outcome."""
        try:
            snap = host.snapshot()
        except herdrhost.HerdrError as exc:
            return {"kind": "herdr-failure",
                    "stage": "herdr-unreachable",
                    "detail": f"event break, and reconciliation "
                    f"failed: {exc}"}
        receipt["reconciled"] = True
        panes = snap.get("panes") or []
        pane = next((p for p in panes
                     if isinstance(p, dict)
                     and p.get("pane_id") == pane_id), None)
        if pane is None:
            if _rc() is not None:
                return None  # the seat finished as the pane
                # went away; the exit file is senior truth
            return {"kind": "herdr-failure",
                    "stage": "pane-exited",
                    "detail": "the pane exited before the seat "
                    "command wrote its exit code"}
        return _observe(pane, "snapshot")

    while True:
        rc = _rc()
        if rc is not None:
            if stalled and log is not None and (
                    _size(out_path) + _size(err_path) != last_size):
                log.emit("working")
            return {"kind": "exit", "returncode": rc}
        now = time.monotonic()
        size = _size(out_path) + _size(err_path)
        if size != last_size:
            last_size = size
            last_activity = now
            if stalled:
                stalled = False
                if log is not None:
                    log.emit("working")
        silent = now - last_activity
        if log is not None and not stalled \
                and silent >= stall_after:
            stalled = True
            log.emit("blocked", "stalled",
                     {"silent_s": round(silent, 1),
                      "stall_after_s": stall_after,
                      "transient": True})
        if matched is None and cli_key is not None:
            matched = seatstate.match_failure(
                cli_key, _read_tail(err_path, 8192))
        if matched is not None and silent >= block_grace:
            return {"kind": "blocked", "facts": {
                "state": "blocked", "class": matched["class"],
                "evidence": {"pattern": matched["pattern"],
                             "matched": matched["matched"],
                             "source": "stderr",
                             "early_terminated": True,
                             "silent_s": round(silent, 1),
                             "transport": "herdr"}}}
        # The watch: one pane poll per loop is the subscription
        # at the wrapper layer. Herdr CLI calls are quick; the
        # seat timeout bounds the whole loop regardless. A
        # failed poll is reconciled, and consecutive failures
        # back the loop off exponentially (P4-07): a persistent
        # failure with a healthy snapshot otherwise spawned a
        # herdr process ~13 times a second for the whole seat
        # timeout. A bounded streak ends the seat with the same
        # herdr-unreachable outcome a failed reconciliation
        # produces.
        try:
            failure = _observe(host.pane_get(pane_id), "pane.get")
            get_failures = 0
            pace = _HERDR_GET_BACKOFF_BASE_S
        except herdrhost.HerdrError:
            receipt["events_lost"] = \
                receipt.get("events_lost", 0) + 1
            get_failures += 1
            failure = _reconcile()
            if failure is None \
                    and get_failures >= _HERDR_GET_MAX_FAILURES:
                failure = {
                    "kind": "herdr-failure",
                    "stage": "herdr-unreachable",
                    "detail": f"pane get failed {get_failures} "
                              f"times in a row while "
                              f"reconciliation kept proving the "
                              f"session healthy; the watch is "
                              f"given up as unreachable"}
            pace = min(_HERDR_GET_BACKOFF_CAP_S,
                       _HERDR_GET_BACKOFF_BASE_S
                       * (2 ** get_failures))
        if failure is not None:
            return failure
        # Fresh clock, not the iteration-start sample: a slow
        # herdr call must not push the timeout outcome past
        # the deadline by its own duration. Silence is
        # recomputed on the same clock so the terminal
        # classification is taken at the decision instant.
        now = time.monotonic()
        silent = now - last_activity
        if now >= deadline:
            if silent >= stall_after:
                facts = {"state": "blocked", "class": "stalled",
                         "evidence": {
                             "silent_s": round(silent, 1),
                             "timeout_s": timeout,
                             "transport": "herdr"}}
            else:
                facts = {"state": "timed-out", "class": None,
                         "evidence": {"timeout_s": timeout,
                                      "transport": "herdr"}}
            return {"kind": "timeout", "facts": facts}
        time.sleep(min(pace, max(0.05, deadline - now)))


def _call_hosted(host, argv, prompt, timeout, private_home,
                 stall_after, block_grace):
    """One herdr-hosted seat call: the headless seat contract
    (providers.command_agent) executed in a herdr pane.

    Isolation mirrors the headless runner where the transport
    allows it: a fresh scratch directory containing ONLY the
    prompt file is the pane's cwd; stdout/stderr are captured
    to files outside it and read back capped. Two honest
    differences: there is no process-group kill or RLIMIT_FSIZE
    to give (the pane is herdr's process, not ours — the seat
    is bounded by closing its workspace and by the same
    timeout), and the pane session carries the user's own
    shell environment (herdrhost.py's U7 note: we add only
    CODEREVIEW_PROMPT, plus HOME for a home=private seat;
    operator keys are never added). Response and failure
    semantics — messages, seat_facts, classifications — are
    the headless ones."""
    log = seatstate.current_log()
    cli_key = seatstate.cli_key_for_argv(argv)
    receipt = {"transport": "herdr",
               "herdr_version": host.version_text}
    box = herdrhost.RECEIPTS.get()
    workdir = tempfile.mkdtemp(prefix="codereview-agent-")
    cap_fds = []
    workspace_id = None
    try:
        prompt_path = os.path.join(workdir, "prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        out_fd, out_path = tempfile.mkstemp(
            prefix="codereview-agent-out-")
        err_fd, err_path = tempfile.mkstemp(
            prefix="codereview-agent-err-")
        os.close(out_fd)
        os.close(err_fd)
        rc_path = out_path + ".rc"
        cap_fds = [out_path, err_path, rc_path]
        pane_env = {"CODEREVIEW_PROMPT": prompt_path}
        if private_home:
            pane_env["HOME"] = workdir
        try:
            workspace_id, pane_id = host.create_workspace(
                cwd=workdir, label="codereview-seat",
                env=pane_env)
        except herdrhost.HerdrError as exc:
            err = ProviderError(
                f"herdr hosting failed (workspace-create): "
                f"{exc}", retryable=False)
            err.seat_facts = {
                "state": "failed", "class": "error",
                "evidence": {"stage": "workspace-create",
                             "transport": "herdr",
                             "detail": str(exc)[:300]}}
            raise err
        receipt["workspace_id"] = workspace_id
        receipt["pane_id"] = pane_id
        # The launcher line: the seat's own argv, stdin FROM
        # the prompt file (never typed — the packet travels by
        # file), output to the capture files, and the exit code
        # to its own file, which is what lets supervision read
        # process truth instead of scraping the screen. POSIX
        # redirection + $? — the pane runs the user's shell.
        line = (shlex.join(argv)
                + f" < {shlex.quote(prompt_path)}"
                + f" > {shlex.quote(out_path)}"
                + f" 2> {shlex.quote(err_path)}"
                + f"; echo $? > {shlex.quote(rc_path)}")
        try:
            host.pane_run(pane_id, line)
        except herdrhost.HerdrError as exc:
            err = ProviderError(
                f"herdr hosting failed (pane-run): {exc}",
                retryable=False)
            err.seat_facts = {
                "state": "failed", "class": "error",
                "evidence": {"stage": "pane-run",
                             "transport": "herdr",
                             "detail": str(exc)[:300]}}
            raise err
        outcome = _run_hosted_seat(
            host, receipt, pane_id, out_path, err_path, rc_path,
            cli_key, log, timeout, stall_after, block_grace)
        if outcome["kind"] in ("timeout", "blocked"):
            # Early termination / deadline: closing the
            # workspace is the pane-side tree kill.
            try:
                host.close_workspace(workspace_id)
            except herdrhost.HerdrError:
                pass
            raise _hosted_outcome_error(
                outcome, timeout, block_grace)
        if outcome["kind"] == "herdr-failure":
            raise _hosted_outcome_error(
                outcome, timeout, block_grace)
        returncode = outcome["returncode"]
        if returncode != 0:
            state, cls, evidence = seatstate.classify_exit(
                cli_key, returncode,
                _read_tail(out_path, 8192),
                _read_tail(err_path, 8192))
            tail = _redact_tail(
                _read_tail(err_path, 4096).strip())[-300:]
            err = ProviderError(
                f"agent command exited {returncode}"
                + (f": {tail}" if tail else ""), retryable=False)
            err.seat_facts = {"state": state, "class": cls,
                              "evidence": evidence}
            raise err
        text = _read_tail(out_path, MAX_AGENT_OUTPUT).strip()
        if not text:
            err = ProviderError("agent command produced no output",
                                retryable=False)
            err.seat_facts = {
                "state": "failed", "class": "error",
                "evidence": {"exit_code": 0,
                             "reason": "no output"}}
            raise err
        return text
    finally:
        if workspace_id is not None:
            try:
                host.close_workspace(workspace_id)
            except Exception:  # noqa: BLE001 — cleanup is
                pass            # best-effort; the outcome stands
        if box is not None:
            box.append(receipt)
        shutil.rmtree(workdir, ignore_errors=True)
        for cap in cap_fds:
            try:
                os.unlink(cap)
            except OSError:
                pass


def command_agent(command, timeout=AGENT_TIMEOUT, private_home=False,
                  stall_after=seatstate.STALL_AFTER_S,
                  block_grace=seatstate.BLOCK_GRACE_S,
                  host=None):
    """Callable backed by a local agent command.

    `timeout` is the per-call ceiling in seconds: None means the
    AGENT_TIMEOUT default; an explicit value is honored verbatim,
    and a non-positive value is refused HERE, at construction —
    never silently swapped for the default (review-v13 finding:
    the library seam used `agent_timeout or AGENT_TIMEOUT`, so a
    caller's explicit 0 became 900 without a word).

    Isolation contract (v0.7.0 external review, findings 1/3/5/6;
    v0.7.1 review, findings 3.2/3.3/3.5): the agent runs in a fresh
    scratch directory containing ONLY the prompt file (its cwd —
    never the repo), with an allow-listed environment (no provider
    keys unless the operator opts names in via CODEREVIEW_AGENT_ENV),
    in its own process group — killed whole on timeout and after a
    normal exit alike, so background children never leak — with a
    per-file write cap (RLIMIT_FSIZE) on POSIX, and its output
    captured to files outside the cwd with the read side capped
    (the verdict tail is kept). With private_home=True the seat's
    HOME is the scratch directory instead of the operator's (for
    agents that need no login state in HOME). The command line is
    split with shlex and executed WITHOUT a shell: metacharacters
    are literal; pipes/redirection belong in a wrapper script.
    Every failure is a ProviderError with retryable=False — the
    seat degrades honestly in the run report, like any provider
    failure, and never triggers account rotation.

    Seat-state supervision (Epic K2): the wait is supervised —
    output activity on the capture files is polled, live stall
    episodes are emitted to the job's seat-state log when one is
    installed (seatstate.CURRENT), a verified per-CLI failure
    pattern matched on stderr followed by `block_grace` seconds
    of total silence terminates the seat early as blocked, and
    every ProviderError raised here carries `seat_facts` (the
    terminal state/class/evidence the job owner records). The
    error MESSAGES are unchanged from the unsupervised wait.

    Herdr hosting (Epic K3a): with `host` (a herdrhost.HerdrHost)
    the same contract executes inside a herdr pane instead of a
    subprocess — see _call_hosted. The default None is the
    headless path, byte-identical to before hosting existed."""
    if timeout is None:
        timeout = AGENT_TIMEOUT
    if timeout <= 0:
        raise ProviderError(
            f"agent timeout must be a positive number of seconds, "
            f"got {timeout!r}", retryable=False)
    if stall_after <= 0 or block_grace <= 0:
        raise ProviderError(
            f"seat supervision bounds must be positive seconds, "
            f"got stall_after={stall_after!r} "
            f"block_grace={block_grace!r}", retryable=False)

    def call(prompt):
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ProviderError(f"bad agent command {command!r}: {exc}",
                                retryable=False)
        if not argv:
            raise ProviderError("empty agent command", retryable=False)
        if host is not None:
            # Epic K3a: this seat is hosted in a herdr pane.
            # The contract, messages, and classifications are
            # the headless ones; only the transport differs.
            return _call_hosted(host, argv, prompt, timeout,
                                private_home, stall_after,
                                block_grace)
        log = seatstate.current_log()
        cli_key = seatstate.cli_key_for_argv(argv)
        workdir = tempfile.mkdtemp(prefix="codereview-agent-")
        cap_fds = []
        try:
            prompt_path = os.path.join(workdir, "prompt.md")
            with open(prompt_path, "w", encoding="utf-8") as fh:
                fh.write(prompt)
            # Capture files live OUTSIDE the scratch cwd: the agent
            # sees a directory containing only its prompt.
            out_fd, out_path = tempfile.mkstemp(
                prefix="codereview-agent-out-")
            err_fd, err_path = tempfile.mkstemp(
                prefix="codereview-agent-err-")
            cap_fds = [out_path, err_path]
            env = _agent_env(prompt_path)
            if private_home:
                env["HOME"] = workdir
            proc = None
            pgid = None
            try:
                with os.fdopen(out_fd, "wb") as out_f, \
                        os.fdopen(err_fd, "wb") as err_f:
                    proc = subprocess.Popen(
                        argv, shell=False, stdin=subprocess.PIPE,
                        stdout=out_f, stderr=err_f,
                        env=env, cwd=workdir,
                        start_new_session=True,
                        preexec_fn=_limit_files
                        if os.name == "posix" else None)
                    if os.name == "posix":
                        pgid = os.getpgid(proc.pid)
                    outcome = _run_seat_process(
                        proc, pgid, prompt, timeout, out_path,
                        err_path, cli_key, log,
                        stall_after=stall_after,
                        block_grace=block_grace)
            except OSError as exc:
                err = ProviderError(
                    f"agent command failed to start: "
                    f"{exc.strerror or exc}", retryable=False)
                err.seat_facts = {
                    "state": "failed", "class": "error",
                    "evidence": {"stage": "start"}}
                raise err
            finally:
                if proc is not None:
                    # Normal exit included: an agent's background
                    # children die with their seat (finding 3.2).
                    _kill_tree(proc, pgid)
            if outcome["kind"] == "timeout":
                err = ProviderError(
                    f"agent command timed out after {timeout}s",
                    retryable=False)
                err.seat_facts = outcome["facts"]
                raise err
            if outcome["kind"] == "blocked":
                facts = outcome["facts"]
                err = ProviderError(
                    f"agent command blocked ({facts['class']}): "
                    f"matched {facts['evidence']['pattern']} on "
                    f"stderr; no output for {block_grace:g}s — "
                    f"terminated early", retryable=False)
                err.seat_facts = facts
                raise err
            if proc.returncode != 0:
                if os.name == "posix" and proc.returncode \
                        == -signal.SIGXFSZ:
                    err = ProviderError(
                        "agent output exceeded the per-file size "
                        f"limit ({MAX_AGENT_FILE} bytes)",
                        retryable=False)
                    err.seat_facts = {
                        "state": "failed", "class": "error",
                        "evidence": {
                            "exit_code": proc.returncode,
                            "signal": "SIGXFSZ"}}
                    raise err
                state, cls, evidence = seatstate.classify_exit(
                    cli_key, proc.returncode,
                    _read_tail(out_path, 8192),
                    _read_tail(err_path, 8192))
                tail = _redact_tail(
                    _read_tail(err_path, 4096).strip())[-300:]
                err = ProviderError(
                    f"agent command exited {proc.returncode}"
                    + (f": {tail}" if tail else ""), retryable=False)
                err.seat_facts = {"state": state, "class": cls,
                                  "evidence": evidence}
                raise err
            text = _read_tail(out_path, MAX_AGENT_OUTPUT).strip()
            if not text:
                err = ProviderError("agent command produced no output",
                                    retryable=False)
                err.seat_facts = {
                    "state": "failed", "class": "error",
                    "evidence": {"exit_code": 0,
                                 "reason": "no output"}}
                raise err
            return text
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            for cap in cap_fds:
                try:
                    os.unlink(cap)
                except OSError:
                    pass
    return call


try:
    from . import registry
except ImportError:  # standalone module load
    import registry  # type: ignore

# Legacy tuple view of the registry (kind, base_url, model,
# key_env, extra_payload) — registry.PRESETS is the source of
# truth; this shape is kept for existing consumers.
PRESETS = {
    name: (p["kind"], p["base_url"], p["model"], p["key_env"],
           p["extra"])
    for name, p in registry.PRESETS.items()
}


def parse_local_spec(spec):
    """local:<name>:<base-url>|<model> -> (name, base_url, model).

    The named local-endpoint form (Epic L5). The base URL keeps
    its own colons (scheme, port) — only the FIRST colon after
    the name separates, and the model rides after the '|' the
    other spec forms already use. Name and model are required:
    a local seat is an ordinary seat, and a seat without a model
    cannot be called. Raises ProviderError on a malformed spec."""
    rest = spec.strip()[len(registry.LOCAL_SPEC_PREFIX):]
    name, colon, tail = rest.partition(":")
    base, pipe, model = tail.partition("|")
    name, base, model = name.strip(), base.strip(), model.strip()
    if not colon or not name or not base or not pipe or not model:
        raise ProviderError(
            f"bad local provider spec {spec!r}: want "
            "local:<name>:<base-url>|<model> (e.g. "
            "local:box:http://localhost:8080/v1|my-model)")
    if not (base.startswith("http://")
            or base.startswith("https://")):
        raise ProviderError(
            f"bad local provider spec {spec!r}: base-url must "
            f"start with http:// or https://, got {base!r}")
    return name, base, model


def _agent_vendor_family(name, command):
    """Vendor family for an agent seat (P6-06): the CLI the
    seat RUNS decides — the command's program, matched
    against discovery's known-CLI table by binary name.
    Before this, every agent seat was family 'agent', so a
    Claude+Codex panel computed as ONE family and could
    never satisfy two-family release eligibility without a
    hand-written --seat-meta.

    The seat NAME never confers a family (review-v11,
    pinned by test_v090_fixes): an agent seat named
    'gemini' running `echo hi` is family 'agent', not
    'google' — the name is operator-chosen text, the
    command is the fact. A seat whose command is a wrapper
    script around a known CLI therefore keeps 'agent' too,
    unless the operator says otherwise via --seat-meta or
    the saved setup's [seat_meta]. A CLI the table does
    not know keeps the generic 'agent' family: recorded,
    never guessed."""
    if _discovery is not None and command:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if tokens:
            program = os.path.basename(
                tokens[0]).strip("\"'").lower()
            for entry in _discovery.KNOWN_CLIS:
                if program in entry["binaries"]:
                    return entry["family"]
    return "agent"


def describe_spec(spec):
    """spec -> {seat, kind, preset, model, key_env, family,
    base_url} WITHOUT building or calling anything. The CLI uses
    this to record which provider/model served which role, and to
    tag seats with their vendor family for the independence
    checks. Raises ProviderError on an unparseable spec."""
    if spec.startswith("agent:"):
        name, _options, _cmd = _parse_agent_spec(spec)
        return {"seat": name, "kind": "agent", "preset": None,
                "model": None, "key_env": None,
                "family": _agent_vendor_family(name, _cmd),
                "base_url": None}
    stripped = spec.strip()
    if stripped.lower().startswith(registry.LOCAL_SPEC_PREFIX):
        name, base, model = parse_local_spec(stripped)
        return {"seat": name, "kind": "openai-compatible",
                "preset": None, "model": model, "key_env": None,
                "family": registry.LOCAL_FAMILY, "base_url": base}
    if stripped.lower().startswith("openai-compatible:"):
        rest = stripped[len("openai-compatible:"):]
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) != 3 or not all(parts):
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "openai-compatible:<base>|<model>|<KEY_ENV>")
        base, model, key_env = parts
        return {"seat": "openai-compatible",
                "kind": "openai-compatible", "preset": None,
                "model": model, "key_env": key_env,
                "family": "unknown", "base_url": base}
    if "|" in spec:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 5:
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "name|type|base_url|model|key_env")
        name, kind, base, model, key_env = parts
        return {"seat": name, "kind": kind, "preset": None,
                "model": model, "key_env": key_env,
                "family": "unknown", "base_url": base}
    name, colon, model_override = stripped.partition(":")
    name = name.strip().lower()
    if name not in registry.PRESETS:
        raise ProviderError(
            f"unknown provider {spec!r}; presets: "
            f"{', '.join(sorted(registry.PRESETS))}, or use the "
            "custom name|type|base_url|model|key_env form")
    preset = registry.PRESETS[name]
    model = (model_override.strip()
             if colon and model_override.strip()
             else preset["model"])
    return {"seat": name, "kind": preset["kind"], "preset": name,
            "model": model, "key_env": preset["key_env"],
            "family": preset["family"],
            "base_url": preset["base_url"]}


def _parse_agent_spec(spec):
    """agent:<name>[<options>]:<command> -> (name, options, command).

    The only option today is home=private (the seat's HOME is its
    scratch directory instead of the operator's). Unknown options
    are rejected loudly rather than ignored."""
    parts = spec.split(":", 2)
    if len(parts) != 3 or not parts[2].strip():
        raise ProviderError(
            f"bad agent spec {spec!r}: want agent:<name>:<command>")
    raw_name, command = parts[1].strip(), parts[2].strip()
    options = {}
    if raw_name.endswith("]") and "[" in raw_name:
        raw_name, _, opt_str = raw_name.partition("[")
        for opt in opt_str.rstrip("]").split(","):
            opt = opt.strip()
            if not opt:
                continue
            if opt == "home=private":
                options["home"] = "private"
            else:
                raise ProviderError(
                    f"unknown agent seat option {opt!r} in {spec!r} "
                    "(supported: home=private)")
    name = raw_name.strip()
    if not name:
        raise ProviderError(
            f"bad agent spec {spec!r}: empty seat name")
    return name, options, command


def build_provider(spec, occurrence=1, text_mode=False,
                   agent_timeout=None, host=None):
    """spec -> (name, callable, account_label).

    `occurrence` > 1 (the same seat requested again) selects the
    next account's key env for presets: GEMINI_API_KEY_2, _3, ...

    `text_mode` builds a solver callable instead of a reviewer: a
    solver-persona system prompt and, for Gemini, no JSON response
    mode — the answer is a Markdown plan.

    `agent_timeout` is the operator's per-seat timeout (the CLI's
    --timeout): it bounds agent seats (default AGENT_TIMEOUT) and,
    since the Phase 4 failure-injection fixes, API seats too —
    an API callable built with it passes it to _post_json as the
    call's overall deadline; without it, API seats keep
    DEFAULT_TIMEOUT (P4-02)."""
    system = _SOLVER_SYSTEM if text_mode else _SYSTEM
    if spec.startswith("agent:"):
        agent_name, options, command = _parse_agent_spec(spec)
        # text_mode changes nothing here: the seat receives the
        # full prompt (reviewer JSON instructions or the solver's
        # plan request) as its input document. Naming: the name
        # returned here is the BASE name — build_providers assigns
        # the final, globally-unique seat names, which only it can
        # see (v0.7.1 external review, finding 3.1).
        return agent_name, command_agent(
            command,
            timeout=(AGENT_TIMEOUT if agent_timeout is None
                     else agent_timeout),
            private_home=options.get("home") == "private",
            host=host), \
            f"agent:{agent_name}"
    if spec.strip().lower().startswith("openai-compatible:"):
        desc = describe_spec(spec)
        return desc["seat"], openai_compatible(
            desc["base_url"], desc["model"], desc["key_env"],
            system=system, timeout=agent_timeout), desc["key_env"]
    if spec.strip().lower().startswith(registry.LOCAL_SPEC_PREFIX):
        # Epic L5 named local endpoint: keyless by construction
        # (key_env None — no credential read, no Authorization
        # header). The account label names the seat, never a
        # credential: there is none.
        desc = describe_spec(spec)
        return desc["seat"], openai_compatible(
            desc["base_url"], desc["model"], None,
            system=system, timeout=agent_timeout), \
            f"local:{desc['seat']}"
    if "|" in spec:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 5:
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "name|type|base_url|model|key_env")
        name, kind, base, model, key_env = parts
        if kind == "gemini":
            return name, gemini(model, key_env, system=system,
                                json_mode=not text_mode,
                                timeout=agent_timeout), key_env
        if kind == "anthropic":
            return name, anthropic(model, key_env,
                                   system=system,
                                   timeout=agent_timeout), key_env
        if kind == "openai-compatible":
            return name, openai_compatible(
                base, model, key_env, system=system,
                timeout=agent_timeout), key_env
        raise ProviderError(f"unknown provider type {kind!r}")
    desc = describe_spec(spec)
    name = desc["preset"]
    kind, base, model, key_env, extra = PRESETS[name]
    model = desc["model"]
    if occurrence > 1 and key_env is not None:
        # Account rotation renames the KEY env; a keyless local
        # preset (Epic L5) has no accounts to rotate — every
        # occurrence is the same local server.
        key_env = f"{key_env}_{occurrence}"
    if kind == "gemini":
        return name, gemini(model, key_env, system=system,
                            json_mode=not text_mode,
                            timeout=agent_timeout), key_env
    if kind == "anthropic":
        return name, anthropic(model, key_env,
                               system=system,
                               timeout=agent_timeout), key_env
    # The account label is the key env for keyed presets; a
    # keyless local preset (Epic L5) labels itself local:<preset>
    # — records show what served, and there is no credential
    # the label could leak.
    label = key_env if key_env is not None else f"local:{name}"
    return name, openai_compatible(
        base, model, key_env, extra, system=system,
        omit_temperature=registry.omit_temperature(name, model),
        completion_tokens=registry.completion_tokens(name, model),
        timeout=agent_timeout), \
        label


_RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "401", "403",
                      "quota", "rate limit", "network", "timed out",
                      "timeout")


def is_retryable(exc):
    """Quota / availability / dead-key errors are worth rotating to
    the next account for; a malformed request is not. A typed
    `retryable` flag on the error wins over the message heuristics
    (an agent command's stderr mentioning "timeout" must not trigger
    rotation — see the v0.7.0 external review, finding 6.3)."""
    flag = getattr(exc, "retryable", None)
    if flag is not None:
        return flag
    msg = str(exc).lower()
    return any(m in msg for m in _RETRYABLE_MARKERS)


class AccountPool:
    """One reviewer seat backed by several accounts, tried in order.

    On a retryable error (quota, rate limit, 5xx, dead key) the next
    account takes the seat. Every rotation is recorded on
    `rotations` and the serving account on `last_account`, so run
    reports show exactly which account reviewed and when a switch
    happened — never a silent substitution. Account labels are key
    env names, never key values."""

    def __init__(self, accounts):
        # accounts: [(label, callable)]
        self.accounts = list(accounts)
        self.rotations = []
        self.last_account = None
        import threading
        self._lock = threading.Lock()

    def __call__(self, prompt):
        last_exc = None
        for i, (label, fn) in enumerate(self.accounts):
            try:
                text = fn(prompt)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not is_retryable(exc):
                    raise
                if i + 1 < len(self.accounts):
                    with self._lock:
                        self.rotations.append({
                            "from": label,
                            "to": self.accounts[i + 1][0],
                            "error": str(exc)[:200]})
                continue
            with self._lock:
                self.last_account = label
            return text
        raise last_exc


def _bump_name(name):
    """bot -> bot-2 -> bot-3: increment a trailing number if the
    name has one, else start the suffix sequence."""
    m = re.match(r"^(.*-)(\d+)$", name)
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}"
    return name + "-2"


def build_providers(specs, text_mode=False, agent_timeout=None,
                    herdr_host=None, herdr_seats=None):
    """specs -> {seat name: callable}. Repeating a seat (the same
    preset twice, or custom specs sharing a name) builds an
    AccountPool for that seat with one account per occurrence.
    Agent seats are the exception: each occurrence runs a different
    command, so occurrences become distinct seats (name, name-2,
    ...) instead of accounts of one seat.

    Herdr hosting (Epic K3a): `herdr_host` (a detected
    herdrhost.HerdrHost) plus `herdr_seats` (the seat names the
    saved config marks for hosting) host those agent seats in
    herdr panes; the match is on the seat's FINAL name (the one
    build_providers assigns), case-insensitively. Both default
    to None — every existing caller builds headless seats,
    byte-identical to before hosting existed.

    Seat names live in one namespace per KIND: an agent seat and an
    API seat sharing a name (agent:gemini next to the gemini preset)
    is a configuration error, raised loudly in either spec order —
    silently merging them into one pool would drop a configured
    reviewer (v0.7.0 external review, finding 4).

    Agent final names are assigned in a pre-pass over ALL specs, so
    a suffixed name can never collide with a name another seat owns
    — including a literal agent name like bot-2 meeting the second
    bot seat (v0.7.1 external review, finding 3.1): suffixes keep
    incrementing until the name is unique, and a candidate owned by
    an API seat raises the cross-kind error. Either way, no
    configured seat is ever silently dropped or pooled."""
    parsed = []
    api_names = set()
    for spec in specs:
        if spec.startswith("agent:"):
            base, _options, _cmd = _parse_agent_spec(spec)
            parsed.append(("agent", base, spec))
        elif spec.strip().lower().startswith(
                registry.LOCAL_SPEC_PREFIX):
            # Epic L5: the seat's base name is the name INSIDE
            # the spec (local:<name>:<base-url>|<model>), so two
            # distinct local endpoints are two seats — pooling
            # them under 'local' would merge different servers
            # into one seat — and the family-tag pass below finds
            # each seat by that name.
            nm, _base, _model = parse_local_spec(spec.strip())
            parsed.append(("api", nm, spec))
            api_names.add(nm.lower())
        elif spec.strip().lower().startswith("openai-compatible:"):
            parsed.append(("api", "openai-compatible", spec))
            api_names.add("openai-compatible")
        elif "|" in spec:
            nm = spec.split("|")[0].strip().lower()
            parsed.append(("api", nm, spec))
            api_names.add(nm)
        else:
            # A preset spec may carry a model override
            # (preset:model); the seat's base name is the preset.
            nm = spec.strip().partition(":")[0].strip().lower()
            parsed.append(("api", nm, spec))
            api_names.add(nm)
    agent_final = {}
    used = set()
    counters = {}
    for idx, (kind, base, _spec) in enumerate(parsed):
        if kind != "agent":
            continue
        n = counters.get(base.lower(), 0) + 1
        counters[base.lower()] = n
        candidate = base if n == 1 else f"{base}-{n}"
        while True:
            # Cross-kind and uniqueness checks compare on the
            # canonical (lowercased) name: seat identity is
            # case-insensitive, so an agent named 'Bot' must not
            # slip past an API seat named 'bot' (review-v11
            # finding — the custom-spec branch above once kept
            # its case while preset names were lowered).
            if candidate.lower() in api_names:
                raise ProviderError(
                    f"seat name {candidate!r} is used by both an "
                    f"agent seat and an API seat; rename the agent "
                    f"seat (e.g. agent:{base}-cli:<command>)")
            if candidate.lower() not in used:
                break
            candidate = _bump_name(candidate)
        used.add(candidate.lower())
        agent_final[idx] = candidate
    seats = {}
    counts = {}
    name_kind = {}
    seat_models = {}
    agent_spec_by_name = {}
    for idx, (kind, base, spec) in enumerate(parsed):
        seat_key = (kind, base.lower())
        counts[seat_key] = counts.get(seat_key, 0) + 1
        seat_host = None
        if kind == "agent" and herdr_host is not None \
                and agent_final[idx].lower() in {
                    str(s).lower() for s in (herdr_seats or ())}:
            seat_host = herdr_host
        name, fn, label = build_provider(
            spec, counts[seat_key], text_mode=text_mode,
            agent_timeout=agent_timeout, host=seat_host)
        if kind == "agent":
            name = agent_final[idx]
            seats[name] = [(f"agent:{name}", fn)]
            name_kind[name] = kind
            agent_spec_by_name[name] = spec
            continue
        owner = name_kind.setdefault(name, kind)
        if owner != kind:
            raise ProviderError(
                f"seat name {name!r} is used by both an agent seat "
                f"and an API seat; rename the agent seat "
                f"(e.g. agent:{base}-cli:<command>)")
        seats.setdefault(name, []).append((label, fn))
        # Remember which model each account of this seat serves,
        # so a later consumer (the CLI's role assignments) can
        # tell what an existing seat will ACTUALLY send — a pool
        # built from repeated specs serves its specs' models, not
        # whatever a later same-name spec requests (78ddf4d5ea27).
        try:
            seat_models.setdefault(name, []).append(
                describe_spec(spec)["model"])
        except ProviderError:
            pass
    providers = {}
    for name, accounts in seats.items():
        providers[name] = accounts[0][1] if len(accounts) == 1 \
            else AccountPool(accounts)
        # Tag the seat with its vendor family (registry truth, not
        # the display name): the CLI's seat metadata and the
        # independence checks read family from here, so a seat
        # named 'kimi' built from the moonshot preset is family
        # 'moonshot', and a custom-named DeepSeek seat is family
        # 'deepseek'. Unknown for fully custom specs, as before —
        # --seat-meta remains the operator's override.
        # Agent seats carry the vendor family of the CLI
        # they run (P6-06: claude -> anthropic, codex ->
        # openai, gemini -> google; an unknown CLI keeps the
        # generic 'agent'), read off the seat's own spec via
        # describe_spec — the same derivation the CLI's role
        # records use, so the two can never disagree.
        fam = None
        if name_kind.get(name) == "agent":
            try:
                fam = describe_spec(
                    agent_spec_by_name[name])["family"]
            except ProviderError:
                fam = "agent"
        if fam is None:
            for (_k, base, spec) in parsed:
                if base.lower() == name.lower() and _k == "api":
                    try:
                        fam = describe_spec(spec)["family"]
                    except ProviderError:
                        fam = None
                    break
        try:
            providers[name]._codereview_family = fam or "unknown"
        except Exception:  # noqa: BLE001 — tagging is advisory
            pass
        # The distinct model(s) this seat's accounts serve
        # (78ddf4d5ea27): read by the CLI's role assignments so a
        # role record credits the model that serves, never a
        # discarded same-name override.
        try:
            providers[name]._codereview_models = tuple(sorted(
                {m for m in seat_models.get(name, []) if m}))
        except Exception:  # noqa: BLE001 — tagging is advisory
            pass
        if name_kind.get(name) == "agent":
            # Tag the seat callable so consumers that only see the
            # providers dict (the CLI's default seat metadata) can
            # still tell an agent seat from a preset seat — even
            # when the agent's name matches a preset's, and after
            # suffixing (bot, bot-2, ...). Resolved seat names
            # carry no 'agent:' prefix, so the kind has to travel
            # with the callable (review-v11 finding).
            try:
                providers[name]._codereview_kind = "agent"
            except Exception:  # noqa: BLE001 — tagging is advisory
                pass
    return providers


def build_solvers(specs, agent_timeout=None):
    """specs -> {seat name: solver callable} for intake mode: same
    seats and account pools as build_providers, but each callable
    answers in plain Markdown (see build_provider's text_mode).
    Agent solver seats default to a 300s timeout — the intake
    deadline — so a hung agent dies with its run instead of keeping
    the process alive past it (finding 5)."""
    if agent_timeout is None:
        agent_timeout = 300
    return build_providers(specs, text_mode=True,
                           agent_timeout=agent_timeout)
