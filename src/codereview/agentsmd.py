#!/usr/bin/env python3
"""codereview AGENTS.md ingestion — project guidance as reviewer
context (Epic L1).

At run start the reviewer panel gets the repository's own
guidance: `AGENTS.md` at the repo root and nested along the
changed paths, loaded as context ALONGSIDE (never instead of)
`.codereview.toml`. Every target repo in the audience already
carries the file; before L1 the gate never read it, so project
rules a human reviewer would apply were invisible to the panel.

Trust model — the file is UNTRUSTED content, on exactly the
diff's terms:

  * It passes through the review path's own redaction
    (`core.redact_secrets`) before anything is sent to a
    provider.
  * It is delimited in the prompt as data (see core's
    `_AGENTS_CONTEXT_HEADER`), never as instructions to the
    harness: text inside it addressed to the reviewer or the
    harness is ignored by construction of the prompt, and —
    the load-bearing half — nothing in this module or in the
    prompt path lets the file touch a gate rule, the panel
    composition, or a record field. The TOML policy remains
    the only machine-enforced layer; AGENTS.md content can
    inform a finding, never change an outcome.
  * A `## Code Review Rules` section is surfaced at the head
    of the attached context as advisory review rules the panel
    may cite in findings (quoting the rule's text in the
    finding's evidence; the evidence_quote itself still comes
    from the diff, as always).

Bounds and provenance:

  * Size-capped per file (AGENTS_PER_FILE_CAP) and in total
    (AGENTS_TOTAL_CAP); truncation is marked inside the text
    and recorded per file — nothing is silently dropped: the
    collector returns a ledger entry for every discovered
    file, including skipped ones, with the reason.
  * Provenance is written to the run record by run_review:
    per ingested file, its repo-relative path and the sha256
    of the file's raw bytes as read from disk (pre-redaction,
    pre-cap — the hash identifies the source file, not the
    excerpt).

Ordering — nearest-wins: discovered files are ordered from
the repo root toward the changed code (directory depth, then
path). Where two files give conflicting guidance about a
changed file, the AGENTS.md NEAREST that file's directory
governs; the prompt states the rule and the order it is
shown. Discovery itself is deterministic: the root plus the
ancestor directories of the patch's changed paths — never a
whole-tree scan, so a file off every changed path is not
ingested.
"""

from __future__ import annotations

import hashlib
import os
import re

from .core import _archived_rule, redact_secrets, split_patch_sections

AGENTS_FILENAME = "AGENTS.md"
AGENTS_PER_FILE_CAP = 16000
AGENTS_TOTAL_CAP = 32000
# Below this much remaining budget a further file is skipped
# outright instead of sending a sliver (same floor the file
# context collector uses).
_MIN_BUDGET_ROOM = 1000

_RULES_HEADING = re.compile(r"^##\s+Code Review Rules\s*$",
                            re.IGNORECASE)
_SECTION_END = re.compile(r"^#{1,2}\s")


def extract_rules_section(text):
    """The body of the `## Code Review Rules` section, or None.

    The section runs from its heading to the next level-1 or
    level-2 heading (or end of file); deeper sub-headings stay
    part of the section. The heading line itself is not part
    of the returned body — the prompt attributes the quote to
    its file explicitly.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _RULES_HEADING.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if _SECTION_END.match(line.strip()):
            break
        body.append(line)
    out = "\n".join(body).strip("\n")
    return out if out.strip() else None


def _ancestor_dirs(changed_paths):
    """Repo-relative directories to look for AGENTS.md in: the
    root plus every ancestor directory of every changed path."""
    dirs = {""}
    for path in changed_paths:
        parts = [p for p in str(path).split("/")
                 if p not in ("", ".")]
        for i in range(len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs


def discover_agents_files(repo, changed_paths):
    """The deterministic discovery list: repo-relative paths of
    the AGENTS.md files that exist at the root or nested along
    `changed_paths`, ordered nearest-wins (root first, then by
    directory depth, then path — later in the list is nearer
    the changed code and governs on conflict)."""
    found = []
    for d in _ancestor_dirs(changed_paths):
        rel = f"{d}/{AGENTS_FILENAME}" if d else AGENTS_FILENAME
        if os.path.isfile(os.path.join(repo, *rel.split("/"))):
            found.append(rel)
    found.sort(key=lambda p: (p.count("/"), p))
    return found


def collect_agents_context(repo, patch,
                           per_file_cap=AGENTS_PER_FILE_CAP,
                           total_cap=AGENTS_TOTAL_CAP):
    """Collect the AGENTS.md context for a review of `patch`.

    Returns (payload, entries). `entries` is the ledger — one
    dict per discovered file stating its provenance (sha256 of
    the raw bytes), size, how much was sent, and any truncation
    or skip reason. `payload` is None when no file was ingested
    (no AGENTS.md on any changed path, or every discovered file
    skipped): the caller then passes nothing and the run is
    byte-identical to the pre-L1 behaviour. Otherwise payload
    is {"files": [ledger entries of the ingested files, in
    prompt order], "total_chars": chars of file text sent,
    "truncated": bool, "prompt_text": the delimited section
    run_review appends to each reviewer prompt}.

    Assembly under the total cap: the surfaced `## Code Review
    Rules` blocks are the highest-value part, so they are
    charged against the budget first; full file texts fill the
    remaining budget in discovery order. A file whose text no
    longer fits is sent truncated to the remaining room, or —
    below the room floor — not sent at all; either way its
    ledger entry records truncated="budget" and the file still
    appears in `entries` (and its rules block, if any, has
    already been charged).
    """
    changed = [name for name, _text in split_patch_sections(patch)
               if name and name != "unknown"]
    entries = []
    candidates = []  # (entry, redacted_text, rules_body)
    for rel in discover_agents_files(repo, changed):
        entry = {"path": rel, "sha256": None, "chars": 0,
                 "sent_chars": 0, "truncated": None,
                 "skipped": None, "rules_section": False}
        entries.append(entry)
        if _archived_rule(rel):
            entry["skipped"] = "archived"
            continue
        full = os.path.realpath(
            os.path.join(repo, *rel.split("/")))
        root = os.path.realpath(repo)
        if os.path.commonpath([full, root]) != root:
            entry["skipped"] = "outside_repo"
            continue
        try:
            with open(full, "rb") as fh:
                raw = fh.read()
        except OSError:
            entry["skipped"] = "unreadable"
            continue
        entry["sha256"] = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8", "replace")
        if "\x00" in text:
            entry["skipped"] = "binary"
            continue
        entry["chars"] = len(text)
        clean = redact_secrets(text)
        rules = extract_rules_section(clean)
        entry["rules_section"] = rules is not None
        candidates.append((entry, clean, rules))

    used = 0
    contributed = set()  # ids of entries that reached the prompt
    rules_blocks = []
    for entry, _clean, rules in candidates:
        if not rules:
            continue
        block = f"From {entry['path']}:\n{rules}"
        room = total_cap - used
        if len(block) > room:
            if room < _MIN_BUDGET_ROOM:
                entry["truncated"] = "budget"
                continue
            block = (rules[:room] + "\n[codereview: advisory "
                     "rules truncated — showing the first "
                     f"{room} chars]")
            entry["truncated"] = "budget"
        rules_blocks.append(block)
        contributed.add(id(entry))
        used += len(block) + 2  # joiner slack

    file_blocks = []
    for entry, clean, _rules in candidates:
        sent = clean
        if len(sent) > per_file_cap:
            sent = sent[:per_file_cap] + (
                "\n[codereview: AGENTS.md context truncated — "
                f"showing the first {per_file_cap} of "
                f"{len(clean)} chars]")
            entry["truncated"] = "file_cap"
        room = total_cap - used
        if len(sent) > room:
            if room < _MIN_BUDGET_ROOM:
                entry["truncated"] = "budget"
                entry["sent_chars"] = 0
                continue
            sent = clean[:room] + (
                "\n[codereview: AGENTS.md context truncated — "
                f"showing the first {room} of {len(clean)} "
                "chars]")
            entry["truncated"] = "budget"
        used += len(sent) + 2  # joiner slack
        file_blocks.append(f"===== {entry['path']} =====\n{sent}")
        entry["sent_chars"] = len(sent)
        contributed.add(id(entry))

    if not contributed:
        return None, entries
    parts = []
    if rules_blocks:
        parts.append(
            "Advisory review rules (## Code Review Rules "
            "sections, quoted verbatim):\n\n"
            + "\n\n".join(rules_blocks))
    parts.extend(file_blocks)
    # Provenance covers every file that reached the prompt —
    # via its full text, its rules block, or both — in
    # discovery (nearest-wins) order.
    ingested = [e for e, _c, _r in candidates
                if id(e) in contributed]
    payload = {
        "files": ingested,
        "total_chars": sum(e["sent_chars"] for e in ingested),
        "truncated": any(e["truncated"] for e in entries),
        "prompt_text": "\n\n".join(parts),
    }
    return payload, entries
