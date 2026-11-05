#!/usr/bin/env python3
"""Deterministic change-risk scorer — Epic E1 of the adopted
roadmap.

`risk.scorer` reads a change (the same diff sections the panel
reviews) and produces a risk score with reasons: which
sensitive patterns the change touches (auth, payments, crypto,
migrations, secrets, deserialization), whether dependency
manifests changed, and how large the change is. The result
lands in the run record's `risk` section when the project
policy enables it (the `[risk]` table of `.codereview.toml`,
validated by policy.py in the B1 style).

Determinism is the contract: the score is a pure function of
the diff sections and the resolved thresholds. No model calls,
no randomness, no clock, no environment reads — the same diff
under the same policy scores identically on every run, on
every machine. Every point of the score is explained by a
human-readable reason string, and the per-signal breakdown is
recorded alongside, so a consumer never has to re-derive why.

Scope of this ticket (E1): the scorer and the record section
only. The score is descriptive — it never changes a verdict, a
finding, or any gate input. Tiering (E2) and escalation (E4)
consume the section next; they read `score` / `band` /
`signals` from here rather than re-scoring.

What is scored:

  * Sections: the kept diff sections of the run (the ones the
    panel reviews — archived record artifacts are already
    excluded by the caller, exactly as for the panel).
  * Patterns: per class, a file matches when its PATH matches
    the class's path patterns or any of its ADDED lines matches
    the class's content patterns (removed lines are not
    scanned: the score describes what the change introduces
    and touches, and path matches already cover deletions of
    sensitive files). A class contributes its points once, no
    matter how many files match; the pattern subtotal is
    capped (PATTERN_CAP) so breadth alone cannot max the
    score.
  * Dependencies: any changed file whose basename is a known
    dependency manifest (or a requirements*.txt, or a .txt
    under a requirements/ directory) contributes
    DEPENDENCY_POINTS once.
  * Size: total added + removed lines across all sections,
    in fixed tiers up to SIZE_MAX_POINTS.

Bands: score >= high threshold is "high", >= medium is
"medium", otherwise "low". Thresholds default to
DEFAULT_MEDIUM_THRESHOLD / DEFAULT_HIGH_THRESHOLD and may be
overridden by the policy's [risk] table.
"""

from __future__ import annotations

import re

SCHEMA = "codereview.risk/1"

# Band thresholds (defaults; the policy's [risk] table may
# override either — policy.py mirrors these two constants
# under the import-free discipline and a test pins the pair).
DEFAULT_MEDIUM_THRESHOLD = 35
DEFAULT_HIGH_THRESHOLD = 70

# Points per touched pattern class (awarded once per class)
# and the cap on the pattern subtotal.
CLASS_POINTS = {
    "auth": 25,
    "payments": 25,
    "crypto": 20,
    "migrations": 20,
    "secrets": 25,
    "deserialization": 20,
}
PATTERN_CAP = 60

# Dependency-manifest changes.
DEPENDENCY_POINTS = 15

# Size tiers: (minimum changed lines, points), descending.
SIZE_TIERS = ((1000, 25), (400, 15), (150, 10), (50, 5))
SIZE_MAX_POINTS = 25

# How many matching files a reason names before summarising
# the rest ("+N more").
_REASON_FILE_LIMIT = 5

# ----------------------------------------------------------------
# Pattern classes, in the fixed order reasons are reported.
# Path patterns match the repo-relative path (lowercased);
# content patterns match added lines (case-insensitive).

_PATH_PATTERNS = {
    "auth": re.compile(
        r"(^|/)(auth|authn|authz|login|logout|signin|signup|"
        r"sessions?|oauth|oidc|rbac|acl|permissions?)([./_-]|$)"),
    "payments": re.compile(
        r"(^|/)(payments?|billing|checkout|invoices?|charges?|"
        r"refunds?|subscriptions?|stripe|paypal|pricing)"
        r"([./_-]|$)"),
    "crypto": re.compile(
        r"(^|/)(crypto|crypt|encryption|decrypt|ciphers?|"
        r"hashing)([./_-]|$)"),
    "migrations": re.compile(
        r"(^|/)migrations?(/|$)|(^|/)alembic(/|$)|"
        r"(^|/)flyway(/|$)|(^|/)liquibase(/|$)|migration"),
    "secrets": re.compile(
        r"(secrets?|credentials?)(\.|/|_|-|$)|(^|/)\.env(\.|$)"),
    "deserialization": re.compile(r"deserial"),
}

_CONTENT_PATTERNS = {
    "auth": re.compile(
        r"\b(authenticate|authentication|authorization|"
        r"login_required|permission_required|check_password|"
        r"make_password|jwt|oauth|login_user|current_user|"
        r"set_cookie)\b", re.IGNORECASE),
    "payments": re.compile(
        r"\b(stripe|paypal|braintree|adyen|cvv|cvc|"
        r"card_number|payment_intent|paymentintent|"
        r"payment_method)\b", re.IGNORECASE),
    "crypto": re.compile(
        r"\b(hashlib|bcrypt|argon2|scrypt|pbkdf2|fernet|"
        r"createcipher|createdecipher|messagedigest|hmac|"
        r"encrypt|decrypt)\b", re.IGNORECASE),
    "migrations": re.compile(
        r"\b(alter table|create table|drop table|add column|"
        r"drop column|create index|drop index)\b",
        re.IGNORECASE),
    "secrets": re.compile(
        r"(api[_-]?key|secret|password|passwd|private[_-]?key|"
        r"aws_secret_access_key)\s*[:=]|"
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}",
        re.IGNORECASE),
    "deserialization": re.compile(
        r"\b(pickle\.loads?|marshal\.loads?|dill\.loads?|"
        r"yaml\.load\(|unserialize\s?\(|objectinputstream|"
        r"readobject\s?\(|binaryformatter)\b", re.IGNORECASE),
}

# Class order for reasons and the signals ledger: the ticket's
# order, fixed so output never depends on dict iteration.
CLASS_ORDER = tuple(CLASS_POINTS)

# Dependency manifests by basename (plus the requirements
# rule in _is_dependency_manifest).
DEPENDENCY_MANIFESTS = frozenset({
    "package.json", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "requirements.txt", "pipfile", "pipfile.lock",
    "pyproject.toml", "setup.py", "setup.cfg", "poetry.lock",
    "uv.lock", "gemfile", "gemfile.lock", "go.mod", "go.sum",
    "cargo.toml", "cargo.lock", "composer.json",
    "composer.lock", "pom.xml", "build.gradle",
    "build.gradle.kts", "packages.lock.json",
})

_REQUIREMENTS_RE = re.compile(r"requirements[^/]*\.txt$")


def _is_dependency_manifest(path):
    lowered = (path or "").lower()
    base = lowered.rsplit("/", 1)[-1]
    if base in DEPENDENCY_MANIFESTS \
            or _REQUIREMENTS_RE.match(base):
        return True
    # The requirements/<env>.txt layout: a .txt inside a
    # requirements directory is a manifest whatever its name.
    parts = lowered.split("/")
    return "requirements" in parts[:-1] \
        and base.endswith(".txt")


def _section_lines(section_text):
    """(added_texts, added_count, removed_count) for one diff
    section, using the same line convention as core.added_lines:
    a line starting with '+' is an addition unless it starts
    with '+++' (the +++ header), likewise '-' / '---'."""
    added_texts = []
    removed = 0
    for raw in (section_text or "").splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            added_texts.append(raw[1:])
        elif raw.startswith("-") and not raw.startswith("---"):
            removed += 1
    return added_texts, len(added_texts), removed


def _name_files(files):
    """A deterministic file list for a reason string: sorted,
    capped at _REASON_FILE_LIMIT names plus a '+N more' tail."""
    names = sorted(files)
    if len(names) <= _REASON_FILE_LIMIT:
        return ", ".join(names)
    return ", ".join(names[:_REASON_FILE_LIMIT]) \
        + f", +{len(names) - _REASON_FILE_LIMIT} more"


def risk_config(policy):
    """The resolved scorer config carried by a loaded policy
    dict, or None when risk scoring is not enabled (no policy,
    no [risk] table, or enabled = false) — the caller then
    leaves the record exactly as it was before Epic E1.

    Defensive by construction, mirroring hooks_from_policy:
    a hand-built policy dict with missing or mistyped values
    resolves to the defaults rather than raising mid-run; the
    validating layer is policy.load_policy."""
    if not isinstance(policy, dict):
        return None
    risk = policy.get("risk") or {}
    if not isinstance(risk, dict) or not risk.get("enabled"):
        return None

    def _threshold(key, default):
        value = risk.get(key)
        if isinstance(value, bool) \
                or not isinstance(value, int) \
                or not 0 <= value <= 100:
            return default
        return value

    return {
        "medium_threshold": _threshold(
            "medium_threshold", DEFAULT_MEDIUM_THRESHOLD),
        "high_threshold": _threshold(
            "high_threshold", DEFAULT_HIGH_THRESHOLD),
    }


def band_for(score, config=None):
    """The band for a score under a resolved config (or the
    default thresholds)."""
    config = config or {}
    medium = config.get("medium_threshold",
                        DEFAULT_MEDIUM_THRESHOLD)
    high = config.get("high_threshold", DEFAULT_HIGH_THRESHOLD)
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def score_sections(sections, config=None):
    """Score a change from its diff sections.

    `sections` is a list of (path, section_text) pairs — the
    shape core.split_patch_sections returns and run_review
    already holds. `config` is a resolved config from
    risk_config (or None for the default thresholds).

    Returns the run record's `risk` section:
    {"schema", "score", "band", "reasons", "points",
     "signals", "thresholds"} — see the module docstring for
    the scoring rules. Pure: no I/O, no clock, no randomness.
    """
    config = config or {}
    medium = config.get("medium_threshold",
                        DEFAULT_MEDIUM_THRESHOLD)
    high = config.get("high_threshold", DEFAULT_HIGH_THRESHOLD)

    class_files = {name: [] for name in CLASS_ORDER}
    dependency_files = []
    files_changed = 0
    lines_added = 0
    lines_removed = 0
    for path, text in sections or []:
        files_changed += 1
        added_texts, n_added, n_removed = _section_lines(text)
        lines_added += n_added
        lines_removed += n_removed
        lowered = (path or "").lower()
        for name in CLASS_ORDER:
            if _PATH_PATTERNS[name].search(lowered):
                class_files[name].append(path)
                continue
            content_re = _CONTENT_PATTERNS[name]
            if any(content_re.search(line)
                   for line in added_texts):
                class_files[name].append(path)
        if _is_dependency_manifest(path):
            dependency_files.append(path)

    reasons = []
    pattern_signals = []
    pattern_points = 0
    for name in CLASS_ORDER:
        files = sorted(set(class_files[name]))
        if not files:
            continue
        points = CLASS_POINTS[name]
        pattern_points += points
        pattern_signals.append({
            "class": name, "points": points, "files": files})
        reasons.append(
            f"{name} patterns touched in {len(files)} file(s): "
            f"{_name_files(files)} (+{points})")
    if pattern_points > PATTERN_CAP:
        reasons.append(
            f"pattern subtotal capped at {PATTERN_CAP} "
            f"(uncapped {pattern_points})")
        pattern_points = PATTERN_CAP

    dependency_points = 0
    dependency_files = sorted(set(dependency_files))
    if dependency_files:
        dependency_points = DEPENDENCY_POINTS
        reasons.append(
            f"dependency manifests changed: "
            f"{_name_files(dependency_files)} "
            f"(+{dependency_points})")

    changed_lines = lines_added + lines_removed
    size_points = 0
    for minimum, points in SIZE_TIERS:
        if changed_lines >= minimum:
            size_points = points
            break
    if size_points:
        reasons.append(
            f"change size: {changed_lines} changed line(s) "
            f"(+{size_points})")

    score = min(100, pattern_points + dependency_points
                + size_points)
    if not reasons:
        reasons.append("no risk signals detected")
    return {
        "schema": SCHEMA,
        "score": score,
        "band": band_for(score, {"medium_threshold": medium,
                                 "high_threshold": high}),
        "reasons": reasons,
        "points": {"patterns": pattern_points,
                   "dependencies": dependency_points,
                   "size": size_points},
        "signals": {
            "files_changed": files_changed,
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "patterns": pattern_signals,
            "dependency_files": dependency_files,
        },
        "thresholds": {"medium": medium, "high": high},
    }


def score_patch(patch, config=None):
    """Score a raw unified-diff string — score_sections over
    core.split_patch_sections(patch). The import lives inside
    this function so the module stays importable on its own
    (core imports this module only at function level too, so
    the module graph stays one-directional)."""
    from .core import split_patch_sections
    return score_sections(split_patch_sections(patch), config)
