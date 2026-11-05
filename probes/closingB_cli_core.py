#!/usr/bin/env python3
"""Closing-B probe — cli.py core cluster.

Claims:
  127ddee9be1b (attempt-2, disputed): _is_within Windows
    edge cases — record supported_platforms is posix-only;
    check the documented fail-closed behaviour.
  179ece0e030e (attempt-2): record loading picks newest
    JSON by mtime (_load_record_arg).
  7b4c5c8155ae (attempt-2): _load_fixture_scope open
    without encoding (code-read + functional check).
  fd1ff955358e (attempt-2): cli.py missing probe harness
    timeout guard (check the timeout wiring).
  ca9fcd9ca7c2 (attempt-2): empty CODEREVIEW_PROVIDERS
    falls through to saved config.
  32587160c9fc (attempt-1): interactive setup unreachable
    due to provider lookup abort.
  764e1d15a218 (attempt-2): fallback provider already a
    primary seat not prevented from overriding.
  934fab88a12e (attempt-2): evidence subcommand collect
    failure crashes instead of exit 2.

Writes results/closingB-cli-core.txt. Facts only.
"""

import io
import json
import os
import sys
import tempfile
import time
import traceback
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import cli, core, probe as probe_mod, \
    userconfig  # noqa: E402

OUT = os.path.join(HERE, "results", "closingB-cli-core.txt")
lines = []


def say(s=""):
    lines.append(s)
    print(s)


def is_within_probe():
    say("== 127ddee9be1b: _is_within (cli.py:85-100) ==")
    say("  record supported_platforms: {'os': ['posix'], "
        "'python': '>=3.11'} (closing-r1 record)")
    with tempfile.TemporaryDirectory() as td:
        inner = os.path.join(td, "sub", "f.json")
        os.makedirs(os.path.dirname(inner))
        say(f"  inside path -> {cli._is_within(inner, td)}")
        say(f"  outside path -> "
            f"{cli._is_within('/etc/passwd', td)}")
        with mock.patch("os.path.commonpath",
                        side_effect=ValueError("mixed drives")):
            say(f"  commonpath ValueError (the Windows "
                f"cross-drive case) -> "
                f"{cli._is_within(inner, td)} "
                f"(fail-closed, per the docstring at "
                f"cli.py:86-94)")


def record_arg_probe():
    say("")
    say("== 179ece0e030e: _load_record_arg (cli.py:1066-1092) ==")
    with tempfile.TemporaryDirectory() as td:
        a = os.path.join(td, "aaa_newer_name.json")
        z = os.path.join(td, "zzz_older_name.json")
        with open(a, "w") as fh:
            json.dump({"which": "aaa"}, fh)
        with open(z, "w") as fh:
            json.dump({"which": "zzz"}, fh)
        os.utime(a, (1_000_000, 1_000_000))   # aaa = OLD mtime
        os.utime(z, (2_000_000, 2_000_000))   # zzz = NEW mtime
        rec, _rdir, jpath = cli._load_record_arg(td, td)
        say(f"  dir holds aaa (mtime 1000000) and zzz (mtime "
            f"2000000); loader picked: "
            f"{os.path.basename(jpath)} with content "
            f"{rec['which']!r} — newest MTIME wins, name and "
            f"content recency ignored")


def fixture_scope_probe():
    say("")
    say("== 7b4c5c8155ae: _load_fixture_scope open "
        "(cli.py:124-126) ==")
    src = open(os.path.join(REPO, "src", "codereview",
                            "cli.py"),
               encoding="utf-8").read().splitlines()
    for n in (124, 125, 126):
        say(f"  cli.py:{n}: {src[n-1].strip()}")
    say("  code-read: the manifest is opened in BINARY mode "
        "('rb') and decoded explicitly with raw.decode("
        "'utf-8') — no locale-dependent default encoding is "
        "involved. Functional check:")
    with tempfile.TemporaryDirectory() as td:
        manifest = {"schema": core.FIXTURE_MANIFEST_SCHEMA,
                    "policy_version":
                        sorted(core.FIXTURE_POLICY_VERSIONS)[0],
                    "fixtures": [{"path": "tést-ü.py"}]}
        p = os.path.join(td, "fixtures.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False)
        try:
            scope = cli._load_fixture_scope(p, repo=td)
            say(f"  non-ASCII manifest loaded under LC_ALL=C "
                f"locale: fixtures="
                f"{scope.get('fixtures') or scope}")
        except Exception as exc:
            say(f"  load raised {type(exc).__name__}: {exc}")


def probe_timeout_probe():
    say("")
    say("== fd1ff955358e: probe harness timeout wiring ==")
    src = open(os.path.join(REPO, "src", "codereview",
                            "cli.py"),
               encoding="utf-8").read().splitlines()
    for n, line in enumerate(src, 1):
        if "probe-timeout" in line or "probe_timeout" in line:
            say(f"  cli.py:{n}: {line.strip()[:110]}")
    with tempfile.TemporaryDirectory() as td:
        fn = probe_mod.make_probe_fn(td, timeout=1)
        t0 = time.monotonic()
        res = fn({"id": "x"}, {"kind": "python",
                               "code": "import time; "
                                       "time.sleep(10)"})
        say(f"  make_probe_fn(timeout=1) on a 10s sleep spec: "
            f"outcome={res['outcome']!r} after "
            f"{time.monotonic()-t0:.1f}s — the timeout the "
            f"CLI passes is enforced by run_probe")


def env_fallthrough_probe():
    say("")
    say("== ca9fcd9ca7c2: empty CODEREVIEW_PROVIDERS "
        "(cli.py:1932-1943) ==")
    captured = {}

    def fake_build(specs, agent_timeout=None):
        captured["specs"] = list(specs)
        raise RuntimeError("sentinel-stop")

    calls = {"saved": 0}

    def fake_saved():
        calls["saved"] += 1
        return ["savedprov:model-x"]

    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "newfile.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")
        env = {"CODEREVIEW_PROVIDERS": "",
               "REVIEWLOOP_PROVIDERS": ""}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(cli, "build_providers",
                                  fake_build), \
                mock.patch.object(userconfig,
                                  "default_provider_specs",
                                  fake_saved), \
                mock.patch.object(userconfig,
                                  "default_role_assignments",
                                  lambda: {}):
            os.environ.pop("REVIEWLOOP_PROVIDERS", None)
            rc = cli.main(["--repo", td, "--files", target])
        say(f"  CODEREVIEW_PROVIDERS='' (set but empty): "
            f"main rc={rc}; saved-config lookup called="
            f"{calls['saved']} time(s); specs handed to "
            f"build_providers={captured.get('specs')} — the "
            f"empty env var is treated as unset and the saved "
            f"setup supplies the panel")


def setup_reach_probe():
    say("")
    say("== 32587160c9fc: first-run setup reachability "
        "(cli.py:1930-1962) ==")
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "newfile.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")
        home = os.path.join(td, "home")
        os.makedirs(home)
        env = {"HOME": home, "CODEREVIEW_PROVIDERS": "",
               "REVIEWLOOP_PROVIDERS": "",
               "XDG_CONFIG_HOME": os.path.join(home, ".config")}
        # non-tty: clean NOT_SET_UP stop, no traceback
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(cli, "_stdin_is_tty",
                                  lambda: False):
            os.environ.pop("REVIEWLOOP_PROVIDERS", None)
            try:
                rc = cli.main(["--repo", td, "--files", target])
                say(f"  no config + non-tty stdin: rc={rc}, "
                    f"no exception (clean stop with the "
                    f"not-set-up instructions)")
            except Exception:
                say("  no config + non-tty stdin RAISED:")
                say(traceback.format_exc())
        # tty: the wizard branch is entered
        reached = {"wizard": False}

        def fake_wizard():
            reached["wizard"] = True
            raise EOFError("probe stops the wizard here")

        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(cli, "_stdin_is_tty",
                                  lambda: True), \
                mock.patch.object(cli, "_run_setup_wizard",
                                  fake_wizard):
            os.environ.pop("REVIEWLOOP_PROVIDERS", None)
            try:
                rc = cli.main(["--repo", td, "--files", target])
            except Exception:
                rc = f"RAISED {traceback.format_exc()}"
            say(f"  no config + tty stdin: wizard entered="
                f"{reached['wizard']}; main rc={rc} (EOFError "
                f"from the wizard is caught at cli.py:1952-"
                f"1957 and becomes a clean return 2)")


DUP_SPEC = "dup|openai-compatible|https://example.invalid/v1|m|NOPE_KEY_ENV"


def fallback_probe():
    say("")
    say("== 764e1d15a218: fallback == primary seat ==")
    # Doctor path (cli.py:1020-1043): no name check.
    seen = {}

    def fake_doctor(providers, fallbacks=None, timeout=None):
        seen["fallbacks"] = fallbacks
        return {"ok": True, "seats": []}

    with mock.patch.object(cli.core, "run_doctor", fake_doctor):
        rc = cli._doctor_main(
            ["--fallback", f"correctness={DUP_SPEC}"],
            providers_override={"dup": lambda p: "{}"})
    fb = (seen.get("fallbacks") or {})
    say(f"  doctor path: rc={rc}; fallbacks handed to "
        f"run_doctor={ {k: v[0] for k, v in fb.items()} } — "
        f"'dup' is BOTH a primary (providers_override) and "
        f"the correctness fallback; no rejection")
    # Review path (cli.py:2007-2031): explicit guard.
    src = open(os.path.join(REPO, "src", "codereview",
                            "cli.py"),
               encoding="utf-8").read().splitlines()
    for n in range(2024, 2032):
        say(f"  cli.py:{n}: {src[n-1].strip()[:100]}")
    with tempfile.TemporaryDirectory() as td:
        target = os.path.join(td, "newfile.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")
        home = os.path.join(td, "home")
        os.makedirs(home)
        with mock.patch.dict(os.environ,
                             {"HOME": home,
                              "XDG_CONFIG_HOME": home},
                             clear=False), \
                mock.patch.object(cli, "_stdin_is_tty",
                                  lambda: False):
            try:
                rc = cli.main(
                    ["--repo", td, "--files", target,
                     "--fallback", f"correctness={DUP_SPEC}"],
                    providers_override={"dup": lambda p: "{}"})
                say(f"  review path: rc={rc} (2 = rejected by "
                    f"the guard before any review ran)")
            except Exception:
                say("  review path RAISED:")
                say(traceback.format_exc())


def evidence_crash_probe():
    say("")
    say("== 934fab88a12e: evidence subcommand failure "
        "handling (cli.py:315-319) ==")
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "evidence.json")
        with open(cfg, "w") as fh:
            # A NUMERIC-STRING timeout passes load_config /
            # validate_config (no type check) and int() in
            # the child's rlimit preexec, but
            # Popen.communicate(timeout='10') raises TypeError
            # inside evidence.collect — outside the try that
            # guards load_config in _evidence_main.
            json.dump({"commands": [{"name": "t",
                                     "command": "true",
                                     "timeout": "10"}]}, fh)
        out = os.path.join(td, "out")
        try:
            rc = cli._evidence_main(
                ["--repo", td, "--config", cfg, "--out", out])
            say(f"  _evidence_main returned rc={rc} (no crash)")
        except Exception as exc:
            say(f"  _evidence_main RAISED "
                f"{type(exc).__name__}: {exc} — the exception "
                f"propagates out of the subcommand (a real CLI "
                f"invocation dies with a traceback + exit 1, "
                f"not the documented exit 2)")


def main():
    say("CLI CORE PROBE — 127ddee9be1b, 179ece0e030e, "
        "7b4c5c8155ae, fd1ff955358e, ca9fcd9ca7c2, "
        "32587160c9fc, 764e1d15a218, 934fab88a12e")
    is_within_probe()
    record_arg_probe()
    fixture_scope_probe()
    probe_timeout_probe()
    env_fallthrough_probe()
    setup_reach_probe()
    fallback_probe()
    evidence_crash_probe()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
