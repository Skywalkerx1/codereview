#!/usr/bin/env python3
"""Public-record exposure scan — open-refutations solution
§3, for a3a2d492b51a (bucket C #3): the gate-attempts log and
the committed review records may carry material that does
not belong in a PUBLIC record: local paths, hostnames,
connector names, account identifiers, key-shaped strings.

This scan supplies the evidence half of the decision (the
DECISION — the public record profile — is the owner's; the
companion draft lives in the ruling-packets directory).
Every committed record file is scanned: gate-attempts.jsonl,
gate-attempts.md, all review-*/ directories (json/md/txt and
evidence sidecars), and the top-level review response and
dispositions documents.

Categories (regex-driven, counted per file; samples are
scrubbed to the public-record profile before they are
written: key-shaped material is masked — shape and length
only — local paths are relativised, and account identifiers
are masked to their domain):
  local_path      /home/<user>/..., /opt/..., /root/...,
                  ~/workspace/... absolute paths
  hostname        internal hostnames / tunnel domains /
                  bare IPv4 addresses
  connector_name  connector identifiers (custom.*, gmail,
                  google_calendar, ...) appearing as text
  account_id      email addresses and account handles
  key_shaped      sk-/AKIA/ghp_/xox*-style tokens, Bearer
                  credentials, long hex/base64 runs in
                  key-ish contexts

Exit 0 = scan completed (findings are reported, not
asserted away)."""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

PATTERNS = {
    "local_path": re.compile(
        r"(?:/home/[A-Za-z0-9_.-]+|/root|/opt/[A-Za-z0-9_./-]+"
        r"|~/workspace)[^\s\"'<>]*"),
    "hostname": re.compile(
        r"\b(?:[A-Za-z0-9-]+\.(?:loca\.lt|local|internal|lan)\b"
        r"|\d{1,3}(?:\.\d{1,3}){3}\b"
        r"|[A-Za-z0-9-]*-prod\b)"),
    "connector_name": re.compile(
        r"\b(?:custom\.[a-z0-9-]+|gmail|google_calendar|"
        r"google_drive|google_docs|stripe|meta_ads|threads|"
        r"instagram|facebook_cli|messenger_read|onepassword|"
        r"shop-pay|shopify|spotify|duffel|flightaware|"
        r"ticketmaster|plaid|tailscale)\b"),
    "account_id": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "key_shaped": re.compile(
        r"(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}"
        r"|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
        r"|Bearer\s+[A-Za-z0-9._-]{16,}"
        r"|AIza[A-Za-z0-9_-]{20,})"),
}


_HOME_RX = re.compile(r"^/home/[^/]+")


def relativise(path):
    """Public-record profile (ratified for ec925437d0e3): a
    committed artifact carries repo-relative paths, never the
    operator's absolute layout — no username, no machine tree.
    Paths inside this repository become repo-relative; other
    home-anchored paths collapse to their ~/ form."""
    if path.startswith(REPO + os.sep):
        return os.path.relpath(path, REPO)
    if _HOME_RX.match(path):
        return "~" + _HOME_RX.sub("", path, count=1)
    if path == "/root":
        return "~root"
    if path.startswith("/root/"):
        return "~root" + path[len("/root"):]
    return path


def mask(category, value):
    if category == "key_shaped":
        return f"{value[:4]}…({len(value)} chars)"
    if category == "local_path":
        return relativise(value)
    if category == "account_id":
        # Ratified for 20e4194e5ed9: committed artifacts do not
        # republish account identifiers verbatim — the domain
        # keeps the evidentiary value, the local part does not
        # survive.
        local, at, domain = value.partition("@")
        if at:
            return f"{local[:1]}***@{domain}"
        return "***"
    return value


def targets():
    files = []
    for name in ("gate-attempts.jsonl", "gate-attempts.md"):
        p = os.path.join(REPO, name)
        if os.path.exists(p):
            files.append(p)
    files += sorted(glob.glob(os.path.join(REPO, "review-*.md")))
    for d in sorted(glob.glob(os.path.join(REPO, "review-*"))):
        if os.path.isdir(d):
            for root, _dirs, names in os.walk(d):
                for n in sorted(names):
                    files.append(os.path.join(root, n))
    return files


def main():
    lines = ["PUBLIC-RECORD EXPOSURE SCAN — a3a2d492b51a",
             "Scope: gate-attempts.* + all committed review "
             "records.", ""]
    grand = {c: 0 for c in PATTERNS}
    per_file = []
    scanned = 0
    for path in targets():
        try:
            with open(path, encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        scanned += 1
        hits = {}
        for cat, rx in PATTERNS.items():
            found = rx.findall(text)
            if found:
                hits[cat] = found
                grand[cat] += len(found)
        if hits:
            per_file.append((os.path.relpath(path, REPO), hits))
    lines.append(f"Files scanned: {scanned}")
    lines.append(f"Files with at least one hit: {len(per_file)}")
    lines.append("")
    lines.append("Totals by category:")
    for cat, n in grand.items():
        lines.append(f"  {cat}: {n}")
    lines.append("")
    lines.append("Per-file detail (samples capped at 3 per "
                 "category; key-shaped samples masked, paths "
                 "relativised, account ids masked):")
    for rel, hits in per_file:
        lines.append(f"\n{rel}")
        for cat, found in hits.items():
            samples = []
            for v in found:
                s = mask(cat, v)
                if s not in samples:
                    samples.append(s)
                if len(samples) == 3:
                    break
            lines.append(f"  {cat} x{len(found)}: "
                         + "; ".join(samples))
    # Telemetry inventory: the claim's actual subject is the
    # attempts log's per-seat operational telemetry, which the
    # regex categories do not capture. Inventory its fields
    # and distinct values so the profile decision has them.
    ga = os.path.join(REPO, "gate-attempts.jsonl")
    if os.path.exists(ga):
        import collections
        import json as _json
        rows = [_json.loads(ln) for ln in open(
            ga, encoding="utf-8") if ln.strip()]
        seat_fields = collections.Counter()
        distinct = collections.defaultdict(collections.Counter)
        for r in rows:
            for seat in r.get("seats") or []:
                seat_fields.update(seat.keys())
                for k, v in seat.items():
                    distinct[k][str(v)] += 1
        lines += ["",
                  "TELEMETRY INVENTORY — gate-attempts.jsonl "
                  f"({len(rows)} rows):",
                  "  row fields: " + ", ".join(sorted(
                      {k for r in rows for k in r})),
                  "  seat fields: " + ", ".join(
                      f"{k} x{n}" for k, n in
                      sorted(seat_fields.items()))]
        for k in ("provider", "family", "tier", "error_class",
                  "fallback_for", "status", "lens"):
            if k in distinct:
                vals = ", ".join(
                    f"{v} x{n}" for v, n in
                    distinct[k].most_common(10))
                lines.append(f"  distinct {k}: {vals}")
        lines.append(
            "  (patch_sha256 + commit range + timestamp per row "
            "link attempts to records and reveal cadence.)")
    lines += ["",
              "READING: local paths and internal hostnames are",
              "operational detail (machine layout, usernames,",
              "tunnel names) with no evidentiary value to a",
              "public reader; account identifiers name people/",
              "accounts; connector names reveal the operator's",
              "tooling; key-shaped hits must be triaged by a",
              "human — most are expected to be fixture strings",
              "and hashes, but the profile must not rely on",
              "'most'. Content hashes (sha256 of evidence) are",
              "NOT in these categories: they are the record's",
              "integrity mechanism and stay public by design.",
              "The decision and the profile draft are the",
              "owner's (see the companion draft document)."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "records-scan-a3a2d492b51a.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
