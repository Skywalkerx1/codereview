#!/usr/bin/env python3
"""codereview providers — build reviewer callables from API keys.

A provider is a callable: prompt (str) -> raw model text (str).
Keys are read from environment variables only; nothing is stored,
logged, or written to disk by this module. Redirects are refused on
authenticated requests.

Presets: gemini, openai, xai, nvidia, deepseek.
Custom:  name|openai-compatible|https://base.url/v1|model|KEY_ENV
         name|gemini|-|model|KEY_ENV
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

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 240
AGENT_TIMEOUT = 900


class ProviderError(Exception):
    """A provider/seat failure. `retryable` tells the account pool
    whether rotating to another account could help: True/False when
    the failure class is known (quota vs. a local agent command that
    will fail identically on every account), None to fall back to
    the message heuristics in is_retryable."""

    def __init__(self, message, retryable=None):
        super().__init__(message)
        self.retryable = retryable


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ProviderError("redirect refused on authenticated request")


def _post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code} from {url.split('/')[2]}") from e
    except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
        raise ProviderError(f"network error: {e}") from e


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


def openai_compatible(base_url, model, key_env, extra_payload=None,
                      system=_SYSTEM):
    """Callable for any OpenAI-compatible chat completions endpoint."""
    def call(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 8192,
        }
        if extra_payload:
            payload.update(extra_payload)
        data = _post_json(
            base_url.rstrip("/") + "/chat/completions",
            {"Authorization": f"Bearer {_key(key_env)}"}, payload)
        try:
            text = (data["choices"][0]["message"].get("content")
                    or "").strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model")
        return text
    return call


def gemini(model, key_env="GEMINI_API_KEY", system=_SYSTEM,
           json_mode=True):
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
        data = _post_json(url, {"x-goog-api-key": _key(key_env)}, payload)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise ProviderError(f"bad response shape: {e}") from e
        if not text:
            raise ProviderError("empty content from model")
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


def command_agent(command, timeout=AGENT_TIMEOUT, private_home=False):
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
    failure, and never triggers account rotation."""
    if timeout is None:
        timeout = AGENT_TIMEOUT
    if timeout <= 0:
        raise ProviderError(
            f"agent timeout must be a positive number of seconds, "
            f"got {timeout!r}", retryable=False)

    def call(prompt):
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ProviderError(f"bad agent command {command!r}: {exc}",
                                retryable=False)
        if not argv:
            raise ProviderError("empty agent command", retryable=False)
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
                    try:
                        proc.communicate(
                            input=prompt.encode("utf-8"),
                            timeout=timeout)
                    except subprocess.TimeoutExpired:
                        _kill_tree(proc, pgid)
                        proc.communicate()
                        raise ProviderError(
                            f"agent command timed out after {timeout}s",
                            retryable=False)
            except OSError as exc:
                raise ProviderError(
                    f"agent command failed to start: "
                    f"{exc.strerror or exc}", retryable=False)
            finally:
                if proc is not None:
                    # Normal exit included: an agent's background
                    # children die with their seat (finding 3.2).
                    _kill_tree(proc, pgid)
            if proc.returncode != 0:
                if os.name == "posix" and proc.returncode \
                        == -signal.SIGXFSZ:
                    raise ProviderError(
                        "agent output exceeded the per-file size "
                        f"limit ({MAX_AGENT_FILE} bytes)",
                        retryable=False)
                tail = _read_tail(err_path, 4096).strip()[-300:]
                raise ProviderError(
                    f"agent command exited {proc.returncode}"
                    + (f": {tail}" if tail else ""), retryable=False)
            text = _read_tail(out_path, MAX_AGENT_OUTPUT).strip()
            if not text:
                raise ProviderError("agent command produced no output",
                                    retryable=False)
            return text
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            for cap in cap_fds:
                try:
                    os.unlink(cap)
                except OSError:
                    pass
    return call


PRESETS = {
    "gemini": ("gemini", None, "gemini-2.5-flash", "GEMINI_API_KEY", None),
    "openai": ("openai-compatible", "https://api.openai.com/v1",
               "gpt-5-mini", "OPENAI_API_KEY", None),
    "xai": ("openai-compatible", "https://api.x.ai/v1",
            "grok-4-mini", "XAI_API_KEY", None),
    "nvidia": ("openai-compatible", "https://integrate.api.nvidia.com/v1",
               "nvidia/nemotron-3.5-lightning-30b-a3b", "NVIDIA_API_KEY",
               {"chat_template_kwargs": {"enable_thinking": False}}),
    "deepseek": ("openai-compatible", "https://api.deepseek.com",
                 "deepseek-chat", "DEEPSEEK_API_KEY", None),
}


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
                   agent_timeout=None):
    """spec -> (name, callable, account_label).

    `occurrence` > 1 (the same seat requested again) selects the
    next account's key env for presets: GEMINI_API_KEY_2, _3, ...

    `text_mode` builds a solver callable instead of a reviewer: a
    solver-persona system prompt and, for Gemini, no JSON response
    mode — the answer is a Markdown plan."""
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
            private_home=options.get("home") == "private"), \
            f"agent:{agent_name}"
    if "|" in spec:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 5:
            raise ProviderError(
                f"bad provider spec {spec!r}: want "
                "name|type|base_url|model|key_env")
        name, kind, base, model, key_env = parts
        if kind == "gemini":
            return name, gemini(model, key_env, system=system,
                                json_mode=not text_mode), key_env
        if kind == "openai-compatible":
            return name, openai_compatible(base, model, key_env,
                                           system=system), key_env
        raise ProviderError(f"unknown provider type {kind!r}")
    name = spec.strip().lower()
    if name not in PRESETS:
        raise ProviderError(
            f"unknown provider {spec!r}; presets: "
            f"{', '.join(sorted(PRESETS))}, or use the custom "
            "name|type|base_url|model|key_env form")
    kind, base, model, key_env, extra = PRESETS[name]
    if occurrence > 1:
        key_env = f"{key_env}_{occurrence}"
    if kind == "gemini":
        return name, gemini(model, key_env, system=system,
                            json_mode=not text_mode), key_env
    return name, openai_compatible(base, model, key_env, extra,
                                   system=system), key_env


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


def build_providers(specs, text_mode=False, agent_timeout=None):
    """specs -> {seat name: callable}. Repeating a seat (the same
    preset twice, or custom specs sharing a name) builds an
    AccountPool for that seat with one account per occurrence.
    Agent seats are the exception: each occurrence runs a different
    command, so occurrences become distinct seats (name, name-2,
    ...) instead of accounts of one seat.

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
        elif "|" in spec:
            nm = spec.split("|")[0].strip().lower()
            parsed.append(("api", nm, spec))
            api_names.add(nm)
        else:
            nm = spec.strip().lower()
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
    for idx, (kind, base, spec) in enumerate(parsed):
        seat_key = (kind, base.lower())
        counts[seat_key] = counts.get(seat_key, 0) + 1
        name, fn, label = build_provider(
            spec, counts[seat_key], text_mode=text_mode,
            agent_timeout=agent_timeout)
        if kind == "agent":
            name = agent_final[idx]
            seats[name] = [(f"agent:{name}", fn)]
            name_kind[name] = kind
            continue
        owner = name_kind.setdefault(name, kind)
        if owner != kind:
            raise ProviderError(
                f"seat name {name!r} is used by both an agent seat "
                f"and an API seat; rename the agent seat "
                f"(e.g. agent:{base}-cli:<command>)")
        seats.setdefault(name, []).append((label, fn))
    providers = {}
    for name, accounts in seats.items():
        providers[name] = accounts[0][1] if len(accounts) == 1 \
            else AccountPool(accounts)
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
