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
"""

import contextlib
import io
import json
import os
import re
import tempfile

from . import __version__
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
                                   "directory)",
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
                    "description": "project policy file (TOML); "
                                   "default: .codereview.toml "
                                   "at the repo root, when "
                                   "present",
                },
                "out": {
                    "type": "string",
                    "description": "output directory for the "
                                   "run record (default: "
                                   "<repo>/codereview-out)",
                },
                "context": {
                    "type": "string",
                    "description": "builder's change "
                                   "description, shown to the "
                                   "reviewers",
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
                                   "record directory",
                },
                "repo": {
                    "type": "string",
                    "description": "repository the record "
                                   "belongs to (default: the "
                                   "server's working "
                                   "directory)",
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
    stays on disk at record_path), and severity counts."""
    findings = [_finding_summary(f)
                for f in record.get("findings") or []]
    by_severity = {}
    for finding in findings:
        sev = finding["severity"] or "unknown"
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "gate": record.get("gate"),
        "gate_reasons": record.get("gate_reasons") or [],
        "mode": record.get("mode"),
        "degraded": bool(record.get("degraded")),
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
                 seat_meta_override=None, fallbacks_override=None):
        self._providers_override = providers_override
        self._seat_meta_override = seat_meta_override
        self._fallbacks_override = fallbacks_override

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
            if not isinstance(value, str):
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
        repo = args.get("repo") or "."
        out = args.get("out") or os.path.join(
            repo, "codereview-out")
        argv = ["--repo", repo, "--out", out]
        if args.get("range"):
            argv += ["--range", args["range"]]
        if args.get("policy"):
            argv += ["--policy", args["policy"]]
        if args.get("context"):
            argv += ["--context", args["context"]]
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
        try:
            record, _record_dir, jpath = cli._load_record_arg(
                args["record"], args.get("repo") or ".")
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                f"get_verdict: could not read the record: "
                f"{exc}") from exc
        return _verdict_payload(record, jpath)


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


def serve_stdio(tools=None, stdin=None, stdout=None, log=None,
                max_frame_bytes=None):
    """Assemble the server (transport + tools) and serve until
    EOF. Returns the StdioServer so callers (and tests) can
    inspect its error ledger."""
    tools = tools if tools is not None else GateTools()
    kwargs = {}
    if max_frame_bytes is not None:
        kwargs["max_frame_bytes"] = max_frame_bytes
    server = StdioServer(make_dispatch(tools), stdin=stdin,
                         stdout=stdout, log=log, **kwargs)
    server.serve_forever()
    return server
