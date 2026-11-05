#!/usr/bin/env python3
"""Stub `herdr` executable for the Epic K3a tests.

Implements the CLI-wrapper surface the adapter binds
(herdrhost.py) with the real binary's shapes — JSON envelopes
on stdout for reads, quiet success for `pane run`, a JSON
error on stderr + exit 1 for server errors, exit 2 for bad
syntax — and actually executes `pane run` command lines in a
shell, like a real pane does. State lives in $HERDR_STUB_DIR
(state.json + a calls.log the tests assert on: exactly which
CLI calls happened is how "no silent resume" is proven).

Chaos scenarios, driven by environment so a test arms them
with mock.patch.dict:

  HERDR_STUB_VERSION        --version string (default 0.9.5)
  HERDR_STUB_SCHEMA_MISSING comma list of method/event names
                            to omit from `api schema --json`
  HERDR_STUB_DIE_AFTER_RUN  after a pane run, the "server"
                            dies: every later call fails,
                            snapshot included
  HERDR_STUB_DROP_GETS      the first pane get after a run
                            fails (an event break); later
                            calls work — reconcile must save
                            the run
  HERDR_STUB_VANISH         after a run, the pane is gone
                            from get AND snapshot while its
                            process keeps running
  HERDR_STUB_RESTART        the pane's terminal_id changes
                            on the second get (herdr
                            restarted and restored layout)
  HERDR_STUB_STATUS         agent_status to report while the
                            pane's process is alive (default:
                            derived — working while alive,
                            idle once it exits)
"""

import json
import os
import subprocess
import sys

METHODS = [
    "workspace.create", "workspace.close", "workspace.list",
    "pane.get", "pane.close", "pane.split", "pane.send_input",
    "pane.send_text", "pane.wait_for_output", "pane.read",
    "agent.get", "agent.list", "agent.start", "agent.wait",
    "session.snapshot", "events.subscribe", "events.wait",
]
EVENTS = [
    "pane.created", "pane.closed", "pane.exited",
    "pane.agent_detected", "pane.agent_status_changed",
    "pane.output_matched",
]


def _dir():
    return os.environ["HERDR_STUB_DIR"]


def _load():
    try:
        with open(os.path.join(_dir(), "state.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"seq": 0, "workspaces": {}, "panes": {}}


def _save(state):
    with open(os.path.join(_dir(), "state.json"), "w",
              encoding="utf-8") as fh:
        json.dump(state, fh)


def _log(argv):
    with open(os.path.join(_dir(), "calls.log"), "a",
              encoding="utf-8") as fh:
        fh.write(" ".join(argv) + "\n")


def _dead():
    return os.path.exists(os.path.join(_dir(), "dead"))


def _err(message):
    print(json.dumps({"error": {"code": "stub_error",
                                "message": message}}),
          file=sys.stderr)
    return 1


def _ok(result):
    print(json.dumps({"id": "cli:stub", "result": result}))
    return 0


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _status(pane):
    override = os.environ.get("HERDR_STUB_STATUS")
    if override and _alive(pane.get("pid")):
        return override
    return "working" if _alive(pane.get("pid")) else "idle"


def _pane_info(pane):
    return {"pane_id": pane["pane_id"],
            "terminal_id": pane["terminal_id"],
            "workspace_id": pane["workspace_id"],
            "tab_id": pane["tab_id"],
            "focused": False,
            "cwd": pane["cwd"],
            "agent_status": _status(pane)}


def _snapshot(state):
    panes = [_pane_info(p) for p in state["panes"].values()
             if not p.get("vanished")]
    return {"version": os.environ.get("HERDR_STUB_VERSION",
                                      "0.9.5"),
            "protocol": 22,
            "workspaces": [
                {"workspace_id": w["workspace_id"],
                 "label": w["label"]}
                for w in state["workspaces"].values()],
            "tabs": [], "panes": panes, "layouts": [],
            "agents": []}


def _kill(pane):
    pid = pane.get("pid")
    if pid and _alive(pid):
        try:
            os.killpg(os.getpgid(pid), 9)
        except OSError:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def main(argv):
    # One stub invocation at a time: hosted seats run
    # concurrently, and the real server serialises its state
    # the same way. The lock fd is opened per invocation and
    # Popen's close_fds default keeps it out of spawned pane
    # processes, so a long-lived seat never holds the lock.
    import fcntl
    lock_fd = os.open(os.path.join(_dir(), "lock"),
                      os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return _dispatch(argv)
    finally:
        os.close(lock_fd)


def _dispatch(argv):
    _log(argv)
    if argv[:1] == ["--version"]:
        print("herdr " + os.environ.get(
            "HERDR_STUB_VERSION", "0.9.5"))
        return 0
    if _dead():
        return _err("server not running (stub died)")
    state = _load()

    if argv[:2] == ["api", "schema"] and "--json" in argv:
        missing = {s.strip() for s in os.environ.get(
            "HERDR_STUB_SCHEMA_MISSING", "").split(",")
            if s.strip()}
        doc = {
            "protocol": 22, "schema_version": 1,
            "schemas": {
                "request": {"methods": [
                    m for m in METHODS if m not in missing]},
                "event": {"types": [
                    e for e in EVENTS if e not in missing]},
            },
        }
        print(json.dumps(doc))
        return 0
    if argv[:2] == ["api", "snapshot"]:
        return _ok({"snapshot": _snapshot(state)})

    if argv[:2] == ["workspace", "create"]:
        args = argv[2:]
        cwd, label = "", "codereview"
        env = {}
        i = 0
        while i < len(args):
            if args[i] == "--cwd":
                cwd = args[i + 1]
                i += 2
            elif args[i] == "--label":
                label = args[i + 1]
                i += 2
            elif args[i] == "--env":
                key, _, value = args[i + 1].partition("=")
                env[key] = value
                i += 2
            else:
                i += 1
        state["seq"] += 1
        n = state["seq"]
        ws_id, tab_id, pane_id = f"w{n}", f"w{n}:t1", f"w{n}:p1"
        pane = {"pane_id": pane_id, "terminal_id": f"term-{n}",
                "workspace_id": ws_id, "tab_id": tab_id,
                "cwd": cwd, "env": env, "pid": None, "gets": 0,
                "vanished": False}
        state["workspaces"][ws_id] = {
            "workspace_id": ws_id, "label": label}
        state["panes"][pane_id] = pane
        _save(state)
        return _ok({
            "workspace": {"workspace_id": ws_id, "label": label},
            "tab": {"tab_id": tab_id},
            "root_pane": _pane_info(pane)})

    if argv[:2] == ["workspace", "close"]:
        ws_id = argv[2]
        for pane_id, pane in list(state["panes"].items()):
            if pane["workspace_id"] == ws_id:
                _kill(pane)
                del state["panes"][pane_id]
        state["workspaces"].pop(ws_id, None)
        _save(state)
        return _ok({})

    if argv[:2] == ["pane", "run"]:
        pane = state["panes"].get(argv[2])
        if pane is None:
            return _err(f"no such pane {argv[2]}")
        command = " ".join(argv[3:])
        env = dict(os.environ)
        env.update(pane.get("env") or {})
        proc = subprocess.Popen(
            ["/bin/sh", "-c", command], cwd=pane["cwd"] or None,
            env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        pane["pid"] = proc.pid
        _save(state)
        if os.environ.get("HERDR_STUB_VANISH"):
            state = _load()
            state["panes"][argv[2]]["vanished"] = True
            _save(state)
        if os.environ.get("HERDR_STUB_DIE_AFTER_RUN"):
            with open(os.path.join(_dir(), "dead"), "w") as fh:
                fh.write("died\n")
        return 0  # quiet, like the real wrapper

    if argv[:2] == ["pane", "get"]:
        pane = state["panes"].get(argv[2])
        if pane is None or pane.get("vanished"):
            return _err(f"no such pane {argv[2]}")
        pane["gets"] = pane.get("gets", 0) + 1
        if os.environ.get("HERDR_STUB_DROP_GETS") \
                and pane.get("pid") and pane["gets"] == 1:
            _save(state)
            return _err("event stream broke (stub)")
        if os.environ.get("HERDR_STUB_RESTART") \
                and pane["gets"] == 2:
            pane["terminal_id"] += "-restarted"
        _save(state)
        return _ok({"pane": _pane_info(pane)})

    if argv[:2] == ["pane", "close"]:
        pane = state["panes"].pop(argv[2], None)
        if pane is not None:
            _kill(pane)
            _save(state)
        return _ok({})

    if argv[:2] == ["agent", "get"]:
        return _err("no recognised agent in that pane (stub)")

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
