"""MCP tool layer (Epic L2): the gate, served to other agents.

`codereview mcp serve` speaks the Model Context Protocol over
stdio (transport: codereview.mcp_transport) and exposes two
tools:

- `run_gate` — a diff (patch text, or a git range in a repo)
  plus an optional policy path → the gate's verdict and the
  run record's path;
- `get_verdict` — a stored record (file or directory) → the
  verdict summary and findings.

Serving only, by design: the server is a new front door onto
the EXISTING gate, not a new gate. A run goes through the
CLI's own `main()` with the arguments translated, so a verdict
served here is the CLI's verdict on the same change — same
panel resolution, same saved-setup and environment discipline,
same record on disk. The review path itself consumes no MCP
tools and reviewers stay read-only and tool-less (Epic F2
unchanged).

The server holds no credentials of its own: seats come only
from the user's saved setup (or $CODEREVIEW_PROVIDERS), exactly
as for the CLI. With no setup, run_gate answers with the CLI's
own not-set-up message — there is no built-in panel to fall
back to, here or anywhere.

Fail-closed: a malformed tool call (wrong types, unknown
arguments, patch+range together) is refused with an error
result before anything runs; a refused or failed run is an
`isError` tool result carrying the reason, never an exception
escaping into the transport loop.

Path roots (item E, owner ruling 2026-11-10): the operator
can pin every caller-supplied path — `repo`, `out`, and
`record` in both tools — to a single approved root, given at
server start with `codereview mcp serve --root DIR` or the
$CODEREVIEW_MCP_ROOT environment variable (the flag wins when
both are set). A path that resolves outside the root is
refused before anything runs; a relative path resolves
against the server's working directory. With no root
configured, paths are accepted exactly as before — the
restriction is an operator opt-in, set server-side, never
something a tool caller can widen.

Policy trust (owner-approved route (b), 2026-11-10 — CSA
finding F2 closed in full): a policy a CALLER names through
the `policy` argument NEVER receives full trust, wherever
the file lives: it is forwarded with the CLI's
--policy-restricted flag and applied exactly like a
repo-discovered policy (strengthening keys only; hooks and
gate-weakening keys dropped and named in the record's
policy.ignored_keys, origin "mcp-caller"). Full trust is
reserved for the operator, at server start:
`codereview mcp serve --policy FILE` or
$CODEREVIEW_MCP_POLICY (the flag wins), read once. When an
operator policy is set it governs EVERY run: a caller-named
policy is refused, never an override. A caller-named policy
that does not exist is refused before anything runs —
fail-closed, never a silent fallback.
"""

import contextlib
import io
import json
import os
import re
import tempfile

from . import __version__, hardening
from .mcp_transport import (INVALID_PARAMS, METHOD_NOT_FOUND,
                            JsonRpcError, StdioServer)

# Protocol versions this subset implements, newest first. The
# handshake echoes the client's version when it is one of
# these and answers with the newest otherwise (the MCP
# negotiation rule).
PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")

SERVER_INFO = {"name": "codereview", "version": __version__}

TOOL_DEFS = [
    {
        "name": "run_gate",
        "description": (
            "Run the CodeReview gate on a change and return "
            "the verdict plus the run record's path. Give "
            "either `patch` (unified diff text) or `range` "
            "(a git range such as HEAD~1..HEAD, evaluated in "
            "`repo`); with neither, the repo's working-tree "
            "change is reviewed, as with the CLI. Seats come "
            "from the operator's saved CodeReview setup — "
            "with no setup the call fails with the setup "
            "instructions, exactly like the CLI."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "repository path (default: "
                                   "the server's working "
                                   "directory). When the operator "
                                   "starts the server with a path "
                                   "root (--root / "
                                   "$CODEREVIEW_MCP_ROOT), it "
                                   "must resolve inside that root",
                },
                "range": {
                    "type": "string",
                    "description": "git diff range, e.g. "
                                   "main...HEAD",
                },
                "patch": {
                    "type": "string",
                    "description": "unified diff text (mutually "
                                   "exclusive with range)",
                },
                "policy": {
                    "type": "string",
                    "description": "project policy file (TOML) "
                                   "named by the caller. A "
                                   "caller-named policy is ALWAYS "
                                   "applied in restricted form "
                                   "(pre-review condition, "
                                   "2026-11-10): only its "
                                   "strengthening keys take "
                                   "effect — hooks and "
                                   "gate-weakening keys are "
                                   "dropped and returned as "
                                   "policy_ignored_keys — wherever "
                                   "the file lives. A policy "
                                   "inside the reviewed "
                                   "repository is refused "
                                   "outright (item E): it is "
                                   "discovered and applied "
                                   "restricted, so refusing loses "
                                   "nothing. Full trust is "
                                   "reserved for the operator's "
                                   "server-start policy "
                                   "(codereview mcp serve "
                                   "--policy / "
                                   "$CODEREVIEW_MCP_POLICY); "
                                   "when one is set it governs "
                                   "every run and a caller-named "
                                   "policy is refused, never an "
                                   "override. To review under a "
                                   "repo policy in full, run the "
                                   "CLI locally with --policy / "
                                   "--trust-repo-policy",
                },
                "out": {
                    "type": "string",
                    "description": "output directory for the "
                                   "run record (default: "
                                   "<repo>/codereview-out); when "
                                   "the operator configures a "
                                   "path root, it must resolve "
                                   "inside that root",
                },
                "context": {
                    "type": "string",
                    "description": "builder's change "
                                   "description, shown to the "
                                   "reviewers. Literal text "
                                   "only: a leading @ is NOT "
                                   "treated as a file path "
                                   "(unlike the CLI's "
                                   "--context, MCP context is "
                                   "never read from disk)",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_verdict",
        "description": (
            "Read a stored CodeReview run record and return "
            "its verdict summary and findings. `record` is a "
            "record JSON file or the directory holding it "
            "(the newest timestamped record in the directory "
            "wins, as with the CLI's record arguments)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "record": {
                    "type": "string",
                    "description": "record JSON file or "
                                   "record directory; when the "
                                   "operator configures a path "
                                   "root, it must resolve inside "
                                   "that root",
                },
                "repo": {
                    "type": "string",
                    "description": "repository the record "
                                   "belongs to (default: the "
                                   "server's working "
                                   "directory); when the "
                                   "operator configures a path "
                                   "root, it must resolve inside "
                                   "that root",
                },
            },
            "required": ["record"],
            "additionalProperties": False,
        },
    },
]


class ToolError(Exception):
    """A tool-level refusal or failure: returned to the client
    as an isError tool result, never raised into the
    transport."""


_FINDING_FIELDS = ("id", "severity", "category", "file", "line",
                   "title", "recommendation", "confidence")


def _finding_summary(finding):
    return {key: finding.get(key) for key in _FINDING_FIELDS}


def _verdict_payload(record, record_path):
    """The verdict shape both tools answer with: the gate,
    its reasons, the findings (summarised — the full record
    stays on disk at record_path), and severity counts.

    Policy visibility (P3-01 follow-ups): the payload also
    carries the record's policy origin, its self-modification
    flag, and — since the trust restriction landed — the keys
    dropped from a repo-discovered policy. The CLI's stderr
    warning is captured and discarded on a successful
    run_gate, so without these fields an MCP client could not
    tell that the verdict was produced under a policy
    discovered in the reviewed repo, which of its keys were
    ignored, or that the change touched the policy file
    itself. The keys are always present (null / [] when the
    run had no policy section) so clients can rely on the
    shape."""
    findings = [_finding_summary(f)
                for f in record.get("findings") or []]
    by_severity = {}
    for finding in findings:
        sev = finding["severity"] or "unknown"
        by_severity[sev] = by_severity.get(sev, 0) + 1
    policy = record.get("policy") or {}
    return {
        "gate": record.get("gate"),
        "gate_reasons": record.get("gate_reasons") or [],
        "mode": record.get("mode"),
        "degraded": bool(record.get("degraded")),
        "policy_origin": policy.get("origin"),
        "policy_ignored_keys": policy.get("ignored_keys") or [],
        "policy_self_modification":
            record.get("policy_self_modification") or [],
        "record_path": record_path,
        "findings": findings,
        "counts": {
            "total": len(findings),
            "blocking": by_severity.get("blocker", 0)
                        + by_severity.get("major", 0),
            "by_severity": by_severity,
        },
    }


class GateTools:
    """The two gate tools. The *_override seams are the CLI's
    own (tests and internal runners inject stub seats through
    them); a production server is constructed with none, so
    seats resolve from the saved setup / environment exactly
    as a CLI run's do."""

    def __init__(self, providers_override=None,
                 seat_meta_override=None, fallbacks_override=None,
                 path_root=None, operator_policy=None):
        self._providers_override = providers_override
        self._seat_meta_override = seat_meta_override
        self._fallbacks_override = fallbacks_override
        # Item E path root: None = no restriction (the
        # pre-0.13.3 behaviour). serve_stdio resolves the
        # operator's configured root (flag > environment)
        # and passes it here; tests may inject one directly.
        self._path_root = (os.path.realpath(path_root)
                           if path_root else None)
        # Operator policy (pre-review condition, 2026-11-10):
        # the ONLY full-trust policy channel through this
        # server — set once at server start, never by a tool
        # caller. serve_stdio resolves it (flag >
        # environment); tests may inject one directly.
        self._operator_policy = (os.path.realpath(
            operator_policy) if operator_policy else None)

    # -- path-root discipline --------------------------------------

    def _require_within_root(self, tool, label, path):
        """Item E: when the operator pinned a path root at
        server start, a caller-supplied path must resolve
        inside it; otherwise the call is refused before
        anything runs or is read. Relative paths resolve
        against the server's working directory, as the
        tools resolved them before the restriction existed."""
        if self._path_root is None:
            return
        resolved = os.path.realpath(path)
        root = self._path_root
        if resolved != root and not resolved.startswith(
                root + os.sep):
            raise ToolError(
                f"{tool}: {label} {path!r} resolves outside "
                f"the server's configured path root ({root}); "
                f"paths are restricted to that root by the "
                f"operator (codereview mcp serve --root / "
                f"$CODEREVIEW_MCP_ROOT)")

    # -- argument discipline -------------------------------------

    @staticmethod
    def _checked_args(tool, arguments):
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ToolError(
                f"{tool}: arguments must be an object")
        schema = next(t["inputSchema"] for t in TOOL_DEFS
                      if t["name"] == tool)
        allowed = schema["properties"]
        for key, value in arguments.items():
            if key not in allowed:
                raise ToolError(
                    f"{tool}: unknown argument {key!r} "
                    f"(allowed: {', '.join(sorted(allowed))})")
            if allowed[key].get("type") == "boolean":
                if not isinstance(value, bool):
                    raise ToolError(
                        f"{tool}: argument {key!r} must be "
                        f"a boolean")
            elif not isinstance(value, str):
                raise ToolError(
                    f"{tool}: argument {key!r} must be a string")
        for key in schema.get("required", []):
            if key not in arguments:
                raise ToolError(
                    f"{tool}: missing required argument {key!r}")
        return arguments

    # -- run_gate --------------------------------------------------

    def run_gate(self, arguments):
        from . import cli, userconfig
        args = self._checked_args("run_gate", arguments)
        if args.get("patch") and args.get("range"):
            raise ToolError(
                "run_gate: give either patch or range, not both")
        # P3-09: same repo validation as the CLI — an
        # explicitly given repo must be an existing directory;
        # "" must not silently become the server's CWD and a
        # nonexistent path must not silently skip the project
        # context in patch mode.
        if "repo" in args and (not args["repo"]
                               or not os.path.isdir(args["repo"])):
            raise ToolError(
                f"run_gate: repo {args['repo']!r} is not an "
                f"existing directory")
        repo = args.get("repo") or "."
        out = args.get("out") or os.path.join(
            repo, "codereview-out")
        # Item E path root: the effective repo and out
        # (caller-given or defaulted) must sit inside the
        # operator's root when one is configured.
        self._require_within_root("run_gate", "repo", repo)
        self._require_within_root("run_gate", "out", out)
        argv = ["--repo", repo, "--out", out]
        if args.get("range"):
            argv += ["--range", args["range"]]
        if args.get("policy"):
            # Owner-approved route (b) (2026-11-10): a
            # caller-named policy NEVER overrides the
            # operator's server-start policy — when one is
            # pinned, naming a policy is refused outright,
            # before anything runs.
            if self._operator_policy is not None:
                raise ToolError(
                    "run_gate: this server runs under an "
                    "operator policy set at server start "
                    "(codereview mcp serve --policy / "
                    "$CODEREVIEW_MCP_POLICY); a caller-named "
                    "policy cannot override it — omit "
                    "`policy` to run under the operator's "
                    "policy")
            # Fail-closed: a named policy that is not an
            # existing file is refused here, never silently
            # dropped or replaced downstream.
            if not os.path.isfile(args["policy"]):
                raise ToolError(
                    f"run_gate: policy {args['policy']!r} is "
                    f"not an existing file")
            # Item E: a caller-supplied policy path must
            # not point inside the reviewed repository. An
            # in-repo path would mark the repo's own policy
            # "explicit" and defeat the P3-01 trust
            # restriction (audit F2: policy trust delegated
            # to the tool caller) — the same file the
            # restriction strips is still discovered and
            # applied in restricted form, so refusing loses
            # nothing but the elevation.
            policy_path = os.path.realpath(args["policy"])
            repo_root = os.path.realpath(repo)
            if policy_path == repo_root or policy_path.startswith(
                    repo_root + os.sep):
                raise ToolError(
                    "run_gate: policy must live outside the "
                    "reviewed repository; a policy inside it "
                    "is applied in restricted form "
                    "(strengthening keys only) and cannot be "
                    "elevated through this tool — run the CLI "
                    "locally with --policy / "
                    "--trust-repo-policy to honour it in full")
            # Route (b): the caller-named policy is
            # forwarded with --policy-restricted and applied
            # exactly like a discovered policy (strengthening
            # keys only; dropped keys named in the record,
            # origin "mcp-caller").
            argv += ["--policy", args["policy"],
                     "--policy-restricted"]
        elif self._operator_policy is not None:
            # The operator's server-start policy: forwarded
            # plainly and honoured in full on every run that
            # does not (and, above, cannot) name its own.
            argv += ["--policy", self._operator_policy]
        if args.get("context"):
            # Security fix (0.13.2, audit C): MCP context is
            # literal text. It goes through the CLI's
            # --context-literal flag so a value starting with
            # @ is never expanded into a local file read —
            # an agent driving this tool must not be able to
            # make the server read arbitrary files (e.g. SSH
            # keys) into the reviewers' prompts.
            # The equals form is deliberate (0.13.2 delta):
            # forwarded as a separate argv word, a value
            # beginning with "-" (e.g. "--out=/x") is misread
            # by argparse as a flag of its own and the call
            # fails; "--context-literal=VALUE" is unambiguous
            # for any text.
            argv += ["--context-literal=" + args["context"]]
        patch_file = None
        if args.get("patch") is not None:
            fd, patch_file = tempfile.mkstemp(
                prefix="codereview-mcp-", suffix=".patch")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(args["patch"])
            argv += ["--patch", patch_file]
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), \
                    contextlib.redirect_stderr(stderr):
                rc = cli.main(
                    argv,
                    providers_override=self._providers_override,
                    seat_meta_override=self._seat_meta_override,
                    fallbacks_override=self._fallbacks_override)
        except SystemExit as exc:
            raise ToolError(
                "run_gate: the gate refused the request "
                f"(exit {exc.code}): "
                f"{_tail(stderr.getvalue())}") from exc
        except Exception as exc:  # noqa: BLE001 — fail closed
            raise ToolError(
                f"run_gate: the gate run failed: {exc}") from exc
        finally:
            if patch_file is not None:
                try:
                    os.unlink(patch_file)
                except OSError:
                    pass
        out_text, err_text = stdout.getvalue(), stderr.getvalue()
        jpath = _printed_path(out_text, "data")
        if jpath is None:
            if userconfig.NOT_SET_UP.splitlines()[0] in err_text:
                raise ToolError(err_text.strip())
            raise ToolError(
                f"run_gate: the gate run produced no record "
                f"(exit {rc}): {_tail(err_text) or _tail(out_text)}")
        try:
            with open(jpath, encoding="utf-8") as fh:
                record = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                f"run_gate: could not read the record the run "
                f"wrote ({jpath}): {exc}") from exc
        payload = _verdict_payload(record, jpath)
        payload["report_path"] = _printed_path(out_text, "report")
        payload["exit_code"] = rc
        return payload

    # -- get_verdict ------------------------------------------------

    def get_verdict(self, arguments):
        from . import cli
        args = self._checked_args("get_verdict", arguments)
        # Item E path root: the record (and the repo it
        # belongs to, when given) must sit inside the
        # operator's root when one is configured — checked
        # before the record is read.
        self._require_within_root(
            "get_verdict", "record", args["record"])
        if args.get("repo"):
            self._require_within_root(
                "get_verdict", "repo", args["repo"])
        try:
            record, _record_dir, jpath = cli._load_record_arg(
                args["record"], args.get("repo") or ".")
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                f"get_verdict: could not read the record: "
                f"{exc}") from exc
        payload = _verdict_payload(record, jpath)
        # Security fix (0.13.2, audit F): the summary is read
        # from a stored record without re-verifying it — the
        # output says so itself, so a client never mistakes a
        # read-back for a verified verdict.
        payload["verification"] = "unverified"
        return payload


def _printed_path(text, label):
    """The CLI prints '  report: <path>' / '  data:   <path>'
    lines at the end of a run; pull one back out."""
    matches = re.findall(rf"^  {label}:\s+(\S.*)$", text,
                         flags=re.MULTILINE)
    return matches[-1].strip() if matches else None


def _tail(text, limit=800):
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


# -- protocol handling --------------------------------------------


def _call_result(payload):
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False,
                               indent=2),
        }],
        "structuredContent": payload,
        "isError": False,
    }


def _error_result(message):
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def make_dispatch(tools):
    """Build the transport dispatch callable for a GateTools
    instance: MCP method handling (initialize / ping /
    tools/list / tools/call) on top of the wire layer."""

    def dispatch(method, params, notification):
        if notification:
            # notifications/initialized, notifications/
            # cancelled, anything else: notifications are
            # fire-and-forget and never answered.
            return None
        if method == "initialize":
            params = params if isinstance(params, dict) else {}
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS \
                else PROTOCOL_VERSIONS[0]
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVER_INFO),
                "instructions": (
                    "CodeReview gate. run_gate runs the "
                    "multi-model review gate on a diff and "
                    "returns the verdict + record path; "
                    "get_verdict reads a stored run record."),
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOL_DEFS}
        if method == "tools/call":
            if not isinstance(params, dict) \
                    or not isinstance(params.get("name"), str):
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "tools/call needs a params object with a "
                    "tool name")
            name = params["name"]
            handler = {"run_gate": tools.run_gate,
                       "get_verdict": tools.get_verdict}.get(name)
            if handler is None:
                raise JsonRpcError(
                    INVALID_PARAMS, f"unknown tool: {name}")
            try:
                payload = handler(params.get("arguments"))
            except ToolError as exc:
                return _error_result(str(exc))
            return _call_result(payload)
        raise JsonRpcError(
            METHOD_NOT_FOUND, f"method not found: {method}")

    return dispatch


def resolve_path_root(flag_root=None):
    """The operator's path root for this server process: the
    --root flag wins over $CODEREVIEW_MCP_ROOT; neither set
    means no restriction. A configured root that is not an
    existing directory is a startup error, not a silent
    no-op — the operator asked for a restriction and must not
    be served without it."""
    raw = flag_root or os.environ.get("CODEREVIEW_MCP_ROOT") \
        or None
    if raw is None:
        return None
    if not os.path.isdir(raw):
        raise ValueError(
            f"codereview mcp: path root {raw!r} is not an "
            f"existing directory")
    return os.path.realpath(raw)


def path_root_notice(root):
    """The stderr notice for a rootless server (pre-review
    condition, 2026-11-10): when no path root is configured
    the operator must be told, once, at startup, that
    caller-supplied paths are unrestricted and how to set a
    root. Returns None when a root IS configured (the serve
    banner already states the restriction then)."""
    if root is not None:
        return None
    return ("codereview mcp: notice: no path root "
            "configured — caller-supplied paths (repo, "
            "out, record) are unrestricted; restrict them "
            "with --root DIR or $CODEREVIEW_MCP_ROOT")


def resolve_operator_policy(flag_policy=None):
    """The operator's full-trust policy for this server
    process: the --policy flag wins over
    $CODEREVIEW_MCP_POLICY; neither set means no operator
    policy (runs fall back to discovery / defaults, exactly
    as before). A configured policy that is not an existing
    file is a startup error, not a silent no-op — same rule
    as the path root."""
    raw = flag_policy or os.environ.get(
        "CODEREVIEW_MCP_POLICY") or None
    if raw is None:
        return None
    if not os.path.isfile(raw):
        raise ValueError(
            f"codereview mcp: operator policy {raw!r} is not "
            f"an existing file")
    return os.path.realpath(raw)


def serve_stdio(tools=None, stdin=None, stdout=None, log=None,
                max_frame_bytes=None, path_root=None,
                operator_policy=None):
    """Assemble the server (transport + tools) and serve until
    EOF. Returns the StdioServer so callers (and tests) can
    inspect its error ledger."""
    # P3-04: the server process holds the operator's
    # environment (provider keys) and spawns gate runs; make
    # it non-dumpable before serving.
    hardening.make_non_dumpable()
    if tools is None:
        tools = GateTools(
            path_root=resolve_path_root(path_root),
            operator_policy=resolve_operator_policy(
                operator_policy))
    kwargs = {}
    if max_frame_bytes is not None:
        kwargs["max_frame_bytes"] = max_frame_bytes
    server = StdioServer(make_dispatch(tools), stdin=stdin,
                         stdout=stdout, log=log, **kwargs)
    server.serve_forever()
    return server
