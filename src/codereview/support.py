"""Support bundle — release-gate row L18.

`codereview support-bundle` writes ONE zip a user can read and
attach to a bug report. It is built to be safe to read first and
safe to send:

  * every text file passes through the same `redact_secrets` the
    run records use;
  * environment variables appear by NAME only (a fixed list of the
    variables the product reads) and as set / not set — never a
    value;
  * nothing is sent anywhere by this module;
  * a file over the per-file cap, or one that would push the zip
    over the total cap, is left out and named in MANIFEST.txt —
    never silently truncated;
  * any step that fails (no records, a missing config, a doctor
    that crashes) is recorded in MANIFEST.txt and the bundle is
    still produced.

Run records hold excerpts of the code that was reviewed. Redaction
cannot recognise private code, so the bundle says so on screen and
offers --no-records.
"""

from __future__ import annotations

import contextlib
import datetime
import glob
import io
import json
import os
import platform
import sys
import zipfile

from .core import VERSION, redact_secrets

SCHEMA = "codereview.support-bundle/1"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024

WARNING = ("Read the bundle before you send it. Redaction removes "
           "secret-shaped text, but run records contain excerpts of "
           "the code you reviewed and redaction cannot recognise "
           "private code. Use --no-records to leave records out. "
           "Nothing is sent automatically.")

# Variables the product reads. Names only, ever.
_ENV_NAMES = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MOONSHOT_API_KEY",
    "NVIDIA_API_KEY", "XAI_API_KEY", "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY", "GITHUB_TOKEN")
_ENV_PREFIXES = ("CODEREVIEW_", "REVIEWLOOP_")
_SECRET_ENV_NAME_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


class _Bundle:
    def __init__(self):
        self.files = []     # (arcname, bytes, reason)
        self.skipped = []   # (name, reason)
        self.notes = []
        self._total = 0

    def add_text(self, arcname, text, reason, redact=True):
        if redact:
            try:
                text = redact_secrets(text)
            except Exception as exc:  # noqa: BLE001
                self.skipped.append(
                    (arcname, f"redaction failed ({type(exc).__name__});"
                              " file left out"))
                return
        data = text.encode("utf-8", "replace")
        if len(data) > MAX_FILE_BYTES:
            self.skipped.append(
                (arcname, f"{len(data)} bytes exceeds the "
                          f"{MAX_FILE_BYTES}-byte per-file cap"))
            return
        if self._total + len(data) > MAX_TOTAL_BYTES:
            self.skipped.append(
                (arcname, f"would exceed the {MAX_TOTAL_BYTES}-byte "
                          "bundle cap"))
            return
        self._total += len(data)
        self.files.append((arcname, data, reason))

    def add_file(self, arcname, path, reason):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            self.skipped.append((arcname, f"unreadable: {exc}"))
            return
        self.add_text(arcname, text, reason)


def _env_report(environ):
    lines = []
    for name in sorted(set(_ENV_NAMES) | {
            k for k in environ if k.startswith(_ENV_PREFIXES)}):
        is_set = bool(str(environ.get(name, "")).strip())
        lines.append(f"{name}: {'set' if is_set else 'not set'}")
    return "\n".join(lines) + "\n"


def _packages():
    try:
        from importlib import metadata
        rows = sorted(
            f"{d.metadata['Name']}=={d.version}"
            for d in metadata.distributions()
            if d.metadata and d.metadata["Name"])
        return "\n".join(rows) + "\n"
    except Exception as exc:  # noqa: BLE001
        return f"(package list unavailable: {type(exc).__name__})\n"


def _find_records(records_dir):
    dirs = []
    if records_dir:
        dirs.append(records_dir)
    else:
        dirs.extend(["codereview-out", "."])
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        found = [p for p in glob.glob(
            os.path.join(directory, "codereview-*.json"))
            if "crash" not in os.path.basename(p)
            and not p.endswith(".sidecar.json")]
        if found:
            found.sort(key=lambda p: os.path.getmtime(p))
            return directory, found[-1]
    return None, None


def _find_crash_notes(directories):
    seen, notes = set(), []
    for directory in directories:
        if not directory:
            continue
        for p in glob.glob(os.path.join(
                directory, "codereview-crash-*.json")):
            rp = os.path.realpath(p)
            if rp not in seen:
                seen.add(rp)
                notes.append(p)
    notes.sort(key=lambda p: os.path.getmtime(p))
    return notes[-3:]


def _run_doctor(bundle):
    from . import cli
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            rc = cli._doctor_main([])
        bundle.add_text("doctor.txt",
                        f"exit code: {rc}\n{out.getvalue()}\n"
                        f"{err.getvalue()}",
                        "output of 'codereview doctor'")
    except BaseException as exc:  # noqa: BLE001 — recorded, not raised
        bundle.add_text("doctor.txt",
                        f"doctor did not complete: "
                        f"{type(exc).__name__}: {exc}\n"
                        f"{out.getvalue()}{err.getvalue()}",
                        "doctor output (it failed)")
        bundle.notes.append(
            "doctor failed; its failure is recorded in doctor.txt")


def build_bundle(path, records_dir=None, include_records=True,
                 message="", environ=None, with_doctor=False):
    """Write the zip at `path` and return its manifest dict."""
    environ = os.environ if environ is None else environ
    bundle = _Bundle()
    now = datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    from .crash import build_identity
    identity = {"schema": SCHEMA, "created_at": now,
                **build_identity(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine()}
    bundle.add_text("identity.json",
                    json.dumps(identity, indent=2, sort_keys=True),
                    "build, Python and OS identity")
    bundle.add_text("packages.txt", _packages(),
                    "installed Python packages", redact=False)
    bundle.add_text("environment-names.txt", _env_report(environ),
                    "which variables the product reads are set "
                    "(names only, never values)", redact=False)
    if message.strip():
        bundle.add_text("MESSAGE.txt", message,
                        "your description of the problem")
    # user config and project policy
    from . import userconfig
    cfg = userconfig.config_path(environ)
    if os.path.isfile(cfg):
        bundle.add_file("user-config.toml", cfg,
                        "your saved provider setup (redacted)")
    else:
        bundle.notes.append("no saved user config found")
    policy_path = ".codereview.toml"
    if os.path.isfile(policy_path):
        bundle.add_file("policy.toml", policy_path,
                        "project policy (redacted)")
    else:
        bundle.notes.append("no .codereview.toml in the current "
                            "directory")
    # records and crash notes
    rec_dir = None
    if include_records:
        rec_dir, record = _find_records(records_dir)
        if record:
            bundle.add_file(os.path.join("records",
                                         os.path.basename(record)),
                            record, "latest run record (JSON)")
            md = os.path.splitext(record)[0] + ".md"
            if os.path.isfile(md):
                bundle.add_file(
                    os.path.join("records", os.path.basename(md)),
                    md, "latest run record (report)")
        else:
            bundle.notes.append("no run record found")
    else:
        bundle.notes.append("run records left out (--no-records)")
    if include_records:
        for note in _find_crash_notes([rec_dir or records_dir,
                                       "."]):
            bundle.add_file(
                os.path.join("crash", os.path.basename(note)),
                note, "crash note (redacted)")
    else:
        # PRIVACY.md promises --no-records leaves the crash
        # notes out too (security fix 0.13.2, audit D) — they
        # used to ride along unconditionally, outside the
        # include_records branch.
        bundle.notes.append("crash notes left out (--no-records)")
    if with_doctor:
        _run_doctor(bundle)
    else:
        bundle.notes.append(
            "doctor not run (it calls your providers); add "
            "--with-doctor to include it")
    manifest = {
        "entries": [{"name": n, "size": len(d), "reason": r}
                    for n, d, r in bundle.files],
        "skipped": [{"name": n, "reason": r}
                    for n, r in bundle.skipped],
        "notes": list(bundle.notes),
    }
    lines = [f"CodeReview support bundle ({SCHEMA})", f"created {now}",
             "", "Files:"]
    for e in manifest["entries"]:
        lines.append(f"  {e['name']}  ({e['size']} bytes) — "
                     f"{e['reason']}")
    lines.append("  MANIFEST.txt — this list")
    if manifest["skipped"]:
        lines += ["", "Left out:"]
        lines += [f"  {s['name']} — {s['reason']}"
                  for s in manifest["skipped"]]
    if manifest["notes"]:
        lines += ["", "Notes:"] + [f"  {n}" for n in manifest["notes"]]
    lines += ["", WARNING, ""]
    manifest_text = "\n".join(lines)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as raw:
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("MANIFEST.txt", manifest_text)
            for name, data, _reason in bundle.files:
                zf.writestr(name, data)
    manifest["text"] = manifest_text
    return manifest


def describe(manifest, show=False, path=None):
    parts = [manifest["text"].rstrip()]
    if show and path:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name == "MANIFEST.txt":
                    continue
                parts.append(f"\n===== {name} =====")
                parts.append(zf.read(name).decode("utf-8", "replace"))
    return "\n".join(parts)


def _unique_path(base):
    if not os.path.exists(base):
        return base
    stem, ext = os.path.splitext(base)
    n = 2
    while os.path.exists(f"{stem}-{n}{ext}"):
        n += 1
    return f"{stem}-{n}{ext}"


def support_main(argv, environ=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="codereview support-bundle",
        description="Write one redacted zip to attach to a bug "
                    "report. Nothing is sent.")
    ap.add_argument("--out", default=None,
                    help="zip path (default: "
                         "codereview-support-<time>.zip here)")
    ap.add_argument("--records", default=None,
                    help="directory holding the run records "
                         "(default: ./codereview-out, then .)")
    ap.add_argument("--no-records", action="store_true",
                    help="leave run records out of the bundle")
    ap.add_argument("--with-doctor", action="store_true",
                    help="also run 'codereview doctor' (calls your "
                         "providers)")
    ap.add_argument("--message", default="",
                    help="what went wrong, in your words")
    args = ap.parse_args(argv)
    stamp = datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y%m%d-%H%M%S")
    path = _unique_path(args.out or f"codereview-support-{stamp}.zip")
    try:
        manifest = build_bundle(
            path, records_dir=args.records,
            include_records=not args.no_records,
            message=args.message, environ=environ,
            with_doctor=args.with_doctor)
    except Exception as exc:  # noqa: BLE001
        print(f"codereview support-bundle: could not write the "
              f"bundle: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(describe(manifest))
    print(f"\nbundle written: {path}")
    return 0
