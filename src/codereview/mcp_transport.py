"""MCP stdio transport (Epic L2): the wire layer only.

Newline-delimited JSON-RPC 2.0 over a pair of binary streams —
the Model Context Protocol's stdio transport. This module
knows nothing about CodeReview, the gate, or the tools served
on top of it (that layer is codereview.mcp_tools); it frames
messages, dispatches them to a caller-supplied handler, and
writes the responses.

Fail-closed contract (a bad frame can never kill the host
loop or take the server down with it):

- an unparseable line is answered with a JSON-RPC parse error
  (id null) and the loop continues with the next line;
- a frame larger than the size cap is discarded through its
  terminating newline, answered with an invalid-request error,
  and the loop continues — the stream stays in sync;
- a structurally invalid request (not an object, no method,
  a batch array — MCP does not batch) is answered with an
  invalid-request error;
- an exception escaping the handler becomes an internal-error
  response for that request; for a notification it is only
  recorded (notifications never get responses).

Every protocol-level failure is appended to the server's
`errors` ledger and mirrored to the diagnostic log (stderr in
production — stdout is the protocol), so a malformed or
oversized request is always recorded somewhere inspectable,
never silently swallowed. Stdlib only, like the rest of the
package.
"""

import json
import math
import re
import sys

# JSON-RPC 2.0 error codes used by this layer.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# One frame's ceiling. A gate request carries a diff; the
# review path's own per-batch budget is 80k chars, and even a
# monorepo-scale hand-off diff fits far under this — 16 MiB is
# generous headroom, not an invitation.
MAX_FRAME_BYTES = 16 * 1024 * 1024

# One frame's nesting ceiling (P3-05 follow-up). Relying on
# json.loads raising RecursionError is not portable: Python
# 3.14 bounds the decoder by actual C-stack use, so on some
# platforms (macOS) a 50,000-deep frame parses and is served.
# The depth is checked explicitly before parsing instead; no
# MCP request comes near 128 levels.
MAX_NESTING_DEPTH = 128

# A JSON string token (quotes and backslash are ASCII, so
# this is safe on raw UTF-8 bytes) or a structural bracket.
_DEPTH_TOKEN = re.compile(rb'"(?:[^"\\]+|\\.)*"|[\[\]{}]', re.DOTALL)


def _nesting_exceeds(raw, limit=MAX_NESTING_DEPTH):
    """True when the frame's brackets nest deeper than
    `limit`. Brackets inside strings do not count, and the
    scan stops at the first level past the limit. One linear
    pass over a frame already bounded by MAX_FRAME_BYTES."""
    depth = 0
    for match in _DEPTH_TOKEN.finditer(raw):
        tok = match.group()
        if tok in (b"[", b"{"):
            depth += 1
            if depth > limit:
                return True
        elif tok in (b"]", b"}"):
            depth -= 1
    return False


class JsonRpcError(Exception):
    """A protocol-level error: answered to the client with
    `code` and `message`, never raised out of the serve loop."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _sanitised_id(req_id):
    """A request id is echoed verbatim — except a non-finite
    float. Python's json accepts NaN/Infinity by default, so
    a frame can carry one as its id; echoing it would emit
    invalid JSON (P3-10). It is answered as null."""
    if isinstance(req_id, float) and not math.isfinite(req_id):
        return None
    return req_id


def result_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def error_response(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


class StdioServer:
    """Serve newline-delimited JSON-RPC over binary streams.

    `dispatch(method, params, notification)` returns the result
    for a request (its return value is ignored for a
    notification) and raises JsonRpcError for protocol-level
    refusals. Anything else it raises becomes an internal
    error. `max_frame_bytes` is injectable so tests can trip
    the cap without moving megabytes.
    """

    def __init__(self, dispatch, stdin=None, stdout=None,
                 log=None, max_frame_bytes=MAX_FRAME_BYTES):
        self._dispatch = dispatch
        self._stdin = stdin if stdin is not None \
            else sys.stdin.buffer
        self._stdout = stdout if stdout is not None \
            else sys.stdout.buffer
        self._log = log if log is not None else (
            lambda text: print(text, file=sys.stderr))
        self._max_frame_bytes = max_frame_bytes
        # The failure ledger: one entry per protocol-level
        # failure, in arrival order — the recorded half of the
        # fail-closed contract.
        self.errors = []

    # -- framing ------------------------------------------------

    def _read_frame(self):
        """Read one newline-terminated frame. Returns
        (raw_bytes, oversized): raw is None at EOF. An oversized
        frame's bytes are consumed through its newline (and
        dropped) so the next frame starts in sync."""
        chunk = self._stdin.readline(self._max_frame_bytes + 2)
        if chunk == b"":
            return None, False
        if len(chunk) <= self._max_frame_bytes + 1 \
                and chunk.endswith(b"\n"):
            return chunk, False
        if len(chunk) <= self._max_frame_bytes + 1:
            # Final line without a newline (EOF right after):
            # still a frame.
            return chunk, False
        # Oversized: discard through the terminating newline.
        while not chunk.endswith(b"\n"):
            chunk = self._stdin.readline(self._max_frame_bytes + 2)
            if chunk == b"":
                break
        return b"", True

    def _send(self, message):
        try:
            data = (json.dumps(message, ensure_ascii=False,
                               allow_nan=False)
                    + "\n").encode("utf-8")
        except (TypeError, ValueError):
            # allow_nan=False refuses a non-finite float
            # anywhere in the payload (P3-10): the wire must
            # never carry NaN/Infinity literals — they are
            # not JSON. Answer with a plain internal error
            # instead of killing the loop.
            data = (json.dumps(error_response(
                None, INTERNAL_ERROR,
                "response was not JSON-serialisable"))
                + "\n").encode("utf-8")
        self._stdout.write(data)
        self._stdout.flush()

    def _record(self, kind, detail):
        entry = {"kind": kind, "detail": str(detail)[:500]}
        self.errors.append(entry)
        self._log(f"codereview mcp: {kind}: {entry['detail']}")

    # -- the loop -------------------------------------------------

    def serve_forever(self):
        """Run until EOF on stdin. Never raises for a bad
        frame, a bad request, or a failing handler."""
        while True:
            raw, oversized = self._read_frame()
            if raw is None:
                return
            if oversized:
                self._record(
                    "oversized_frame",
                    f"frame exceeds {self._max_frame_bytes} bytes")
                self._send(error_response(
                    None, INVALID_REQUEST,
                    "request frame exceeds the size limit "
                    f"({self._max_frame_bytes} bytes)"))
                continue
            if not raw.strip():
                continue
            if _nesting_exceeds(raw):
                detail = ("frame nests deeper than "
                          f"{MAX_NESTING_DEPTH} levels")
                self._record("parse_error", detail)
                self._send(error_response(
                    None, PARSE_ERROR, f"parse error: {detail}"))
                continue
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError,
                    RecursionError) as exc:
                # RecursionError: a frame nested deeper than
                # the interpreter's limit is a parse failure
                # like any other (P3-05) — it must not kill
                # the loop or skip the ledger.
                self._record("parse_error", exc)
                self._send(error_response(
                    None, PARSE_ERROR, f"parse error: {exc}"))
                continue
            self._handle(message)

    def _handle(self, message):
        if not isinstance(message, dict):
            self._record("invalid_request",
                         "request is not a JSON object")
            self._send(error_response(
                None, INVALID_REQUEST,
                "request must be a JSON object"))
            return
        req_id = _sanitised_id(message.get("id"))
        if message.get("jsonrpc") != "2.0":
            # P3-10: the version field was never read — a
            # "1.0" frame, or one with no version at all, was
            # served as if it were 2.0. Fail closed with
            # -32600; a notification-shaped frame (no id)
            # keeps notification semantics — ledger only,
            # never a response.
            self._record("invalid_request",
                         "jsonrpc field is not \"2.0\"")
            if "id" in message:
                self._send(error_response(
                    req_id, INVALID_REQUEST,
                    "jsonrpc field must be \"2.0\""))
            return
        if "id" in message:
            # P5-05: a request id must be a string or an integer
            # (JSON-RPC 2.0). Bool (an int subclass — excluded
            # explicitly), float, null, object and array ids are
            # invalid requests, answered -32600 with a null id:
            # the offending id cannot be echoed as an identity.
            # An ABSENT id is a notification and never reaches
            # this check.
            raw_id = message["id"]
            # One carve-out, inherited from P3-10: a NON-FINITE
            # float (NaN/Infinity — not producible by a
            # conforming JSON encoder, and unemittable in a
            # strict-JSON response) is sanitised to a null id
            # by _sanitised_id and served, rather than refused.
            nonfinite = isinstance(raw_id, float) and not \
                math.isfinite(raw_id)
            if not nonfinite and (isinstance(raw_id, bool)
                                  or not isinstance(
                                      raw_id, (str, int))):
                self._record("invalid_request",
                             "request id is not a string or "
                             "an integer")
                self._send(error_response(
                    None, INVALID_REQUEST,
                    "request id must be a string or an integer"))
                return
        method = message.get("method")
        if not isinstance(method, str) or not method:
            self._record("invalid_request",
                         "request has no method")
            self._send(error_response(
                req_id, INVALID_REQUEST,
                "request has no method"))
            return
        notification = "id" not in message
        try:
            result = self._dispatch(
                method, message.get("params"), notification)
        except JsonRpcError as exc:
            if notification:
                self._record("notification_error",
                             f"{method}: {exc.message}")
                return
            self._record("request_error",
                         f"{method}: {exc.message}")
            self._send(error_response(
                req_id, exc.code, exc.message, exc.data))
            return
        except Exception as exc:  # noqa: BLE001 — fail closed
            if notification:
                self._record("notification_error",
                             f"{method}: {exc}")
                return
            self._record("internal_error", f"{method}: {exc}")
            self._send(error_response(
                req_id, INTERNAL_ERROR,
                f"internal error: {exc}"))
            return
        if not notification:
            self._send(result_response(req_id, result))
