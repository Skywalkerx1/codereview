#!/usr/bin/env python3
"""codereview intake — issue report in, solution plan out.

The front half of the workflow. Everything else in codereview
starts from a code change that already exists; intake starts from
the problem. An issue report (Markdown) plus optional context
files goes to one or more solver models, and each returns a
solution plan in the shape a builder can execute: what to check
first, ranked hypotheses — each with the test that settles it — a
concrete fix plan, prevention, risks and rollback, and closure
criteria a verifier can run.

The primary solver (the first configured seat that answers)
becomes solution.md; every other solver's plan is kept alongside
as an alternate for the builder to compare. Intake never writes
code and never gates anything: the builder reads the plan,
implements it, and the review loop gates the resulting change
exactly as before.

Report and context are secret-redacted before they leave the
machine and size-capped; every truncation is recorded in the
manifest (intake.json) and disclosed inside the prompt itself, so
a solver never mistakes a cut-off file for a complete one.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .core import VERSION, redact_secrets

MAX_REPORT_CHARS = 60000
MAX_CONTEXT_FILE_CHARS = 40000
MAX_TOTAL_CONTEXT_CHARS = 120000
MAX_SOLVER_WORKERS = 8
DEFAULT_SOLVER_TIMEOUT = 300

_INSTRUCTIONS = """You are the solver in a software-maintenance workflow. A coding agent (the builder) will execute your plan on the real system, and an independent multi-model review will gate the resulting change. Your plan is the only guidance the builder gets, so it must be executable as written.

Write the solution plan in Markdown with exactly these sections:

# Solution — <short title naming the problem>

## Diagnosis — what to check first, in order
## Hypotheses — ranked most likely first; for each: the evidence for it, and the concrete test or observation that would prove or disprove it
## Fix plan — numbered steps the builder can execute in order; name files, functions, and commands when the material supports it
## Prevention — the guard, alarm, or test that keeps this from recurring silently
## Risks and rollback
## Closure criteria — a checklist a verifier can run to confirm the issue is actually closed

Rules:
- Ground every claim in the issue report and context below. Label inferences as inferences; if you are guessing, say so.
- Do not invent file names, function names, line numbers, or log lines that are not in the material. Where the material is silent, make the missing check a diagnosis step instead of assuming its result.
- Prefer the smallest fix that addresses the root cause. Where two hypotheses imply different fixes, order the plan so the builder tests before committing to one.
- If the report shows this issue was already "fixed" before and recurred, treat the recurrence itself as the primary defect: the plan must explain why the earlier fix failed or was incomplete, not just repeat it."""


def _cap(text, limit):
    """(sent_text, truncated) — cut with a disclosed marker."""
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n\n[truncated by codereview intake: " \
        f"{len(text) - limit} chars omitted]", True


def build_solver_prompt(report, contexts=(), repo_tree=""):
    """Assemble the solver prompt from already-redacted material.

    Two cap layers, by design: _prepare caps the report and each
    context file individually (and records it in the manifest);
    this builder additionally enforces the total context budget
    across files, disclosing any further cut in the prompt.

    contexts: [(label, text)] — texts are per-file capped here; the
    running total is capped as well and later files disclose it."""
    parts = [_INSTRUCTIONS, "", "## Issue report", "", report]
    if repo_tree:
        parts += ["", "## Repository layout", "", repo_tree]
    total = 0
    for label, text in contexts:
        sent, truncated = _cap(text, MAX_CONTEXT_FILE_CHARS)
        if total + len(sent) > MAX_TOTAL_CONTEXT_CHARS:
            sent, truncated = _cap(
                text, max(0, MAX_TOTAL_CONTEXT_CHARS - total))
        total += len(sent)
        parts += ["", f"## Context: {label}", "", sent]
        if truncated:
            parts.append(f"[note: context {label} was truncated "
                         "to fit the prompt budget]")
    return "\n".join(parts)


def _prepare(report, contexts, repo_tree=""):
    """Redact + cap the raw inputs; return (prompt, meta)."""
    clean_report, rep_trunc = _cap(redact_secrets(report),
                                   MAX_REPORT_CHARS)
    clean_contexts = []
    ctx_meta = []
    for label, text in contexts:
        clean = redact_secrets(text)
        sent, truncated = _cap(clean, MAX_CONTEXT_FILE_CHARS)
        clean_contexts.append((label, sent))
        ctx_meta.append({"label": label, "chars": len(text),
                         "sent_chars": len(sent),
                         "truncated": truncated})
    prompt = build_solver_prompt(clean_report, clean_contexts,
                                 repo_tree=repo_tree)
    meta = {
        "report": {"chars": len(report), "sent_chars": len(clean_report),
                   "truncated": rep_trunc,
                   "sha256": hashlib.sha256(
                       report.encode("utf-8")).hexdigest()},
        "contexts": ctx_meta,
        "prompt_chars": len(prompt),
    }
    return prompt, meta


def run_intake(report, solvers, contexts=(), repo_tree="",
               timeout=DEFAULT_SOLVER_TIMEOUT):
    """Run every solver over the report in parallel.

    solvers: {seat name: callable(prompt) -> markdown text}; dict
    order is the configuration order and decides the primary.
    A solver that has not answered within `timeout` seconds is
    recorded as failed ("timed out") instead of blocking the run:
    the provider HTTP layer already times out at 240s, and this
    deadline is the outer guard for callables that ignore theirs.
    Returns the intake result dict (see write_intake)."""
    prompt, meta = _prepare(report, contexts, repo_tree=repo_tree)

    def call(name, fn):
        started = time.monotonic()
        try:
            text = fn(prompt)
            return {"name": name, "ok": True,
                    "seconds": round(time.monotonic() - started, 1),
                    "chars": len(text or ""), "text": text or "",
                    "error": ""}
        except Exception as exc:  # noqa: BLE001 - solver failure is data
            return {"name": name, "ok": False,
                    "seconds": round(time.monotonic() - started, 1),
                    "chars": 0, "text": "",
                    "error": str(exc)[:300]}

    solutions = []
    if solvers:
        workers = max(1, min(len(solvers), MAX_SOLVER_WORKERS))
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {name: pool.submit(call, name, fn)
                       for name, fn in solvers.items()}
            deadline = time.monotonic() + timeout
            by_name = {}
            for name, fut in futures.items():
                try:
                    by_name[name] = fut.result(
                        timeout=max(0.0, deadline - time.monotonic()))
                except TimeoutError:
                    by_name[name] = {
                        "name": name, "ok": False, "seconds": timeout,
                        "chars": 0, "text": "",
                        "error": f"timed out after {timeout}s"}
            solutions = [by_name[name] for name in solvers]
        finally:
            # Never block the run on a hung solver thread; a stray
            # thread may outlive the call but holds no shared state.
            pool.shutdown(wait=False, cancel_futures=True)
    primary = next((s["name"] for s in solutions if s["ok"]), None)
    return {"tool": "codereview", "version": VERSION, "kind": "intake",
            "created": datetime.now(timezone.utc).isoformat(),
            "ok": primary is not None, "primary": primary,
            "solutions": solutions, **meta}


def write_intake(result, out_dir, report_name=""):
    """Write solution.md (primary), alternates, and intake.json.

    Returns (solution_path or None, manifest_path)."""
    os.makedirs(out_dir, exist_ok=True)
    manifest = {k: v for k, v in result.items() if k != "solutions"}
    manifest["report"] = {**result["report"], "name": report_name}
    manifest["solvers"] = [
        {k: s[k] for k in ("name", "ok", "seconds", "chars", "error")}
        for s in result["solutions"]]
    solution_path = None
    for s in result["solutions"]:
        if not s["ok"]:
            continue
        header = (f"<!-- codereview intake {result['version']} · "
                  f"solver: {s['name']} · report: {report_name} · "
                  f"{result['created']} -->\n\n")
        if s["name"] == result["primary"]:
            solution_path = os.path.join(out_dir, "solution.md")
            path = solution_path
        else:
            path = os.path.join(out_dir, f"solution-{s['name']}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(header + s["text"].strip() + "\n")
    manifest_path = os.path.join(out_dir, "intake.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return solution_path, manifest_path
