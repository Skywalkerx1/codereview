"""Generation/scoring separation for bench runs (void solution
§3.1–§3.3, finding S4).

The Baseline v2 confirmation voided six starts because run
validity was tied to environment health: one seat error anywhere
voided everything, and completed work was discarded. This module
is the GENERATION half of the split:

  * Seat responses are produced per case x seat through a
    record/replay cache keyed by (seat, model, params hash,
    prompt hash). Transport errors are never cached; the FIRST
    VALID response (valid = the product's own parser accepts it)
    is cached and never re-drawn.
  * Failure classes are exactly §3.2's: transport/infrastructure
    failures retry with backoff + jitter up to a per-job attempt
    cap and a wall-clock budget and are not degraded when a valid
    response eventually lands; content failures follow the
    product's own repair behaviour (core._call_and_parse, inside
    run_review) and then the pre-declared per-lens fallback seat —
    healthy when the fallback serves, with served_by /
    fallback_for on the record; a seat still unserved beyond its
    budget marks the case `unscored-infra` for that seat.
  * Generation is resumable: a run is complete when every case x
    configured seat has a valid response. Re-running replays the
    cache and only calls transports for what is missing.
  * Cost is metered honestly (S4): tokens are recorded per job
    and shadow-priced from the list-price table below — the
    generation path never writes the old `cost_per_call_usd: 0`
    convention into a record.

The SCORING half is untouched: `to_attempt_record` adapts a
generation case result into exactly the record shape
bench/scripts/score_confirmation_v2.py consumes, and that scorer
is used unchanged.

Budgets are two-level, one coherent model (the same model
Addendum A's retry-budget item states from the case side):

  * per-JOB: one (seat, prompt) job retries transport failures
    inside a 600 s wall-clock budget (and the per-job attempt
    cap) — `GenerationSeat.wall_clock_budget_s`,
    JOB_WALL_CLOCK_BUDGET_S;
  * per-CASE: all of a case's seat jobs, retries and waits share
    a 1,800 s (30-minute) wall-clock budget —
    `run_generation(case_budget_s=...)`,
    CASE_WALL_CLOCK_BUDGET_S — enforced by stamping each seat
    with a case deadline for the duration of the case's
    run_review call. A job that hits the case deadline exhausts
    exactly like a job that hits its own budget: the seat's
    record for the case lands unscored-infra.
"""

import hashlib
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(
    __file__)), "..", "src"))

from codereview import core  # noqa: E402

GENERATION_SCHEMA = "codereview.generation/1"

# The two-level budget model (module docstring): a per-job
# wall-clock cap nested inside a per-case wall-clock budget.
JOB_WALL_CLOCK_BUDGET_S = 600.0
CASE_WALL_CLOCK_BUDGET_S = 1800.0

# ------------------------------------------------------------------
# Shadow pricing (S4)
#
# List prices per 1M tokens (input, output), keyed by a substring
# of the model name. These are SHADOW prices: approximate public
# list prices used so a run's cost is measured in the right
# ballpark instead of declared as $0. They are NOT invoice data —
# verify against the provider's current price list before quoting
# a figure anywhere. Free-tier seats price at 0 cash but still
# record their tokens.
SHADOW_PRICES_USD_PER_1M = {
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek": (0.27, 1.10),
    "gpt-5": (1.25, 10.00),
    "gpt-4": (2.50, 10.00),
    "gemini": (1.25, 5.00),
    "nemotron": (0.00, 0.00),
    "nvidia": (0.00, 0.00),
}
SHADOW_PRICE_NOTE = ("shadow price: approximate list price per 1M "
                     "tokens, for cost metering only — not an "
                     "invoice figure")


def shadow_price(model, tokens_in, tokens_out):
    """(usd, price_known) for a model + token counts."""
    name = str(model or "").lower()
    for key, (pin, pout) in SHADOW_PRICES_USD_PER_1M.items():
        if key in name:
            return ((tokens_in or 0) * pin
                    + (tokens_out or 0) * pout) / 1_000_000.0, True
    return 0.0, False


def _canonical_sha(payload):
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True).encode("utf-8")).hexdigest()


def prompt_hash(prompt):
    return hashlib.sha256(
        (prompt or "").encode("utf-8")).hexdigest()


def params_hash(params):
    return _canonical_sha(params or {})


def estimate_tokens(text):
    """Deterministic fallback when a transport reports no usage:
    ~4 chars/token, marked as an estimate wherever recorded."""
    return int(math.ceil(len(text or "") / 4.0))


def normalize_usage(usage, prompt_text, response_text):
    """-> (tokens_in, tokens_out, estimated). Accepts the common
    spellings (llm_chain's prompt_tokens/completion_tokens,
    OpenAI-style, input/output); estimates when absent."""
    usage = usage or {}
    tin = usage.get("prompt_tokens", usage.get(
        "input_tokens", usage.get("tokens_in")))
    tout = usage.get("completion_tokens", usage.get(
        "output_tokens", usage.get("tokens_out")))
    if tin is None or tout is None:
        return (estimate_tokens(prompt_text),
                estimate_tokens(response_text), True)
    return int(tin), int(tout), False


# ------------------------------------------------------------------
# Record/replay cache

class ResponseCache:
    """One JSON file per cache key under `directory`. Only valid
    responses are ever put here (GenerationSeat enforces that);
    a corrupted or mismatched entry reads as a miss."""

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.directory, key + ".json")

    def get(self, key):
        try:
            with open(self._path(key), encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            return None
        if entry.get("key") != key or not entry.get("response"):
            return None
        return entry

    def put(self, key, entry):
        entry = dict(entry, key=key)
        tmp = self._path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entry, fh)
        os.replace(tmp, self._path(key))
        return entry


def cache_key(seat, model, params, prompt):
    """The §3.1 key: (seat, model, params hash, prompt hash)."""
    ph, qh = params_hash(params), prompt_hash(prompt)
    return _canonical_sha({"seat": seat, "model": model,
                           "params_hash": ph, "prompt_hash": qh}), ph, qh


# ------------------------------------------------------------------
# Failure classes (§3.2)
#
# core._classify_error kinds map onto the solution's classes:
# rate_limit / transient are retryable transport failures; quota /
# auth / provider / unknown are transport failures the product
# itself does not retry inside a run (daily quota and credentials
# do not heal in minutes) — they end the job and, unserved, mark
# the case unscored-infra. An empty body from the transport layer
# is a transport failure too (the solution names it explicitly).

RETRYABLE_KINDS = ("rate_limit", "transient")

# The exhaustion reason for the per-case deadline. Unlike the
# per-job budgets, a case deadline is stamped per case: tripping
# it must NOT latch the per-key exhausted state, or one case's
# blown budget would poison the same prompt in a later case
# (whose deadline is fresh). Within the case, re-entry still
# fails fast — the deadline check itself raises before any
# transport call.
CASE_DEADLINE_REASON = "per-case wall-clock budget exceeded"


class GenerationExhausted(Exception):
    """The per-job generation budget (attempts or wall clock) is
    spent for this prompt; raised fast so the product's own retry
    layer does not multiply calls against a dead seat."""


class GenerationSeat:
    """A prompt->text seat wrapper implementing §3.1/§3.2 around
    a raw transport callable.

    The transport returns response text, or (text, usage). The
    wrapper is what run_review calls: it replays the cache,
    retries transport failures with backoff + jitter inside the
    per-job budget, never caches transport errors or content the
    product's parser rejects, and caches the first valid
    response. Every transport call is appended to `events` for
    the driver's per-case records; the driver drains the list
    after each case.
    """

    def __init__(self, name, model, transport, cache=None,
                 params=None, max_attempts=5,
                 wall_clock_budget_s=JOB_WALL_CLOCK_BUDGET_S,
                 base_delay_s=1.0,
                 max_delay_s=30.0, sleep=None, clock=None,
                 now_iso=None, rng=None):
        self.name = name
        self.model = model
        self.transport = transport
        self.cache = cache
        self.params = params or {}
        self.params_hash = params_hash(self.params)
        self.max_attempts = int(max_attempts)
        self.wall_clock_budget_s = float(wall_clock_budget_s)
        self.base_delay_s = float(base_delay_s)
        self.max_delay_s = float(max_delay_s)
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.now_iso = now_iso or core._now_iso
        self.rng = rng or random.random
        self.events = []
        self._keys = {}  # prompt_hash -> per-key budget state
        # Per-case deadline (absolute, on this seat's clock),
        # stamped by run_generation for the duration of one
        # case: the outer level of the two-level budget model.
        # None = no case in flight.
        self.case_deadline = None

    # -- internals ------------------------------------------------

    def _event(self, qh, outcome, started_iso, attempts=0,
               error_class=None, detail=None, tokens=(0, 0, False),
               cached=False):
        ev = {"seat": self.name, "prompt_hash": qh,
              "outcome": outcome, "error_class": error_class,
              "attempts": attempts,
              "tokens_in": tokens[0], "tokens_out": tokens[1],
              "tokens_estimated": tokens[2], "cached": cached,
              "started_at": started_iso,
              "finished_at": self.now_iso()}
        if detail:
            ev["detail"] = str(detail)[:200]
        self.events.append(ev)
        return ev

    def _backoff(self, attempt):
        delay = min(self.max_delay_s,
                    self.base_delay_s * (2 ** (attempt - 1)))
        self.sleep(delay * (0.5 + self.rng()))

    def _budget_reason(self, state):
        """Why this job's budget is spent, or None while budget
        remains: the per-job attempt cap, the per-job wall-clock
        budget, or the per-case deadline stamped on the seat."""
        if state["attempts"] >= self.max_attempts:
            return f"attempt cap {self.max_attempts} reached"
        if self.clock() - state["started"] \
                > self.wall_clock_budget_s:
            return (f"wall-clock budget "
                    f"{self.wall_clock_budget_s}s exceeded")
        if self.case_deadline is not None \
                and self.clock() > self.case_deadline:
            return CASE_DEADLINE_REASON
        return None

    def _within_budget(self, state):
        return self._budget_reason(state) is None

    def __call__(self, prompt):
        key, ph, qh = cache_key(self.name, self.model,
                                self.params, prompt)
        started_iso = self.now_iso()
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                self._event(qh, "cache_hit", started_iso,
                            tokens=(hit.get("tokens_in") or 0,
                                    hit.get("tokens_out") or 0,
                                    bool(hit.get(
                                        "tokens_estimated"))),
                            cached=True)
                return hit["response"]
        state = self._keys.setdefault(
            qh, {"attempts": 0, "started": self.clock(),
                 "exhausted": None})
        if state["exhausted"] is not None:
            raise GenerationExhausted(
                f"generation budget exhausted for seat "
                f"{self.name}: {state['exhausted']}")
        while True:
            reason = self._budget_reason(state)
            if reason is not None:
                if reason != CASE_DEADLINE_REASON:
                    state["exhausted"] = reason
                raise GenerationExhausted(
                    f"generation budget exhausted for seat "
                    f"{self.name}: {reason}")
            state["attempts"] += 1
            try:
                raw = self.transport(prompt)
            except Exception as exc:  # noqa: BLE001 — classified
                kind, _tries = core._classify_error(exc)
                self._event(qh, "transport_error", started_iso,
                            attempts=1, error_class=kind,
                            detail=exc)
                if kind in RETRYABLE_KINDS and \
                        self._within_budget(state):
                    self._backoff(state["attempts"])
                    continue
                if kind not in RETRYABLE_KINDS:
                    state["exhausted"] = f"{kind}: {exc}"[:200]
                raise
            text, usage = (raw if isinstance(raw, tuple)
                           else (raw, None))
            if text is None or not str(text).strip():
                # Empty body from the transport layer: a
                # transport failure (§3.2), never cached.
                self._event(qh, "transport_error", started_iso,
                            attempts=1, error_class="empty_body",
                            detail="transport returned an empty "
                                   "body")
                if self._within_budget(state):
                    self._backoff(state["attempts"])
                    continue
                if self._budget_reason(state) \
                        != CASE_DEADLINE_REASON:
                    state["exhausted"] = "empty_body"
                raise GenerationExhausted(
                    f"generation budget exhausted for seat "
                    f"{self.name}: empty body from transport")
            tokens = normalize_usage(usage, prompt, text)
            try:
                core.parse_json_object(text)
            except Exception:  # noqa: BLE001 — any parse failure
                # Content failure: the response arrived but the
                # product cannot use it. NOT cached and NOT
                # retried here — the product's own repair flow
                # (core._call_and_parse) issues its own calls,
                # and the per-lens fallback seat is the declared
                # next step (§3.2/§3.3). Returning the text lets
                # that machinery run exactly as in the product.
                self._event(qh, "content_invalid", started_iso,
                            attempts=1, tokens=tokens,
                            error_class="content")
                return text
            if self.cache is not None:
                self.cache.put(key, {
                    "seat": self.name, "model": self.model,
                    "params_hash": self.params_hash,
                    "prompt_hash": qh, "response": text,
                    "tokens_in": tokens[0],
                    "tokens_out": tokens[1],
                    "tokens_estimated": tokens[2],
                    "attempts": state["attempts"],
                    "stored_at": self.now_iso()})
            self._event(qh, "ok", started_iso, attempts=1,
                        tokens=tokens)
            return text


# ------------------------------------------------------------------
# Per-case generation records

def _seat_case_record(case, seat_name, lens, model, ph, events,
                      reports, binding):
    """Fold one case's events + reviewer reports for one
    configured seat into its generation record (§3.2 logging:
    failure counts per case ride along for the post-hoc
    failure-vs-feature analysis)."""
    mine = [e for e in events if e["seat"] == seat_name]
    transport_calls = sum(1 for e in mine if e["outcome"] in
                          ("ok", "transport_error",
                           "content_invalid"))
    failures = sum(1 for e in mine if e["outcome"] in
                   ("transport_error", "content_invalid"))
    prompt_hashes = sorted({e["prompt_hash"] for e in mine})
    tokens_in = sum(e["tokens_in"] for e in mine
                    if e["outcome"] == "ok" and not e["cached"])
    tokens_out = sum(e["tokens_out"] for e in mine
                     if e["outcome"] == "ok" and not e["cached"])
    cached_tokens = sum(e["tokens_in"] + e["tokens_out"]
                        for e in mine if e["cached"])
    cost, price_known = shadow_price(model, tokens_in, tokens_out)
    error_classes = sorted({e["error_class"] for e in mine
                            if e.get("error_class")})
    # Serving outcome, from the product's own reports.
    status, served_by, fallback_for = None, None, None
    lens_reports = [r for r in reports if r.get("lens") == lens]
    for r in reports:
        if r.get("provider") != seat_name \
                or r.get("status") != "ok":
            continue
        if r.get("lens") == lens:
            status, served_by = "valid", seat_name
            if r.get("fallback_for"):
                fallback_for = r.get("fallback_for")
        elif status is None and r.get("fallback_for"):
            # This seat served as another lens's fallback.
            status, served_by = "valid", seat_name
            fallback_for = r.get("fallback_for")
    if status is None:
        for r in lens_reports:
            if r.get("fallback_for") == seat_name \
                    and r.get("status") == "ok":
                status, served_by = "valid", r.get("provider")
    if status is None:
        if any(e["outcome"] == "content_invalid" for e in mine) \
                and not any(
                    e["outcome"] == "transport_error"
                    for e in mine):
            status = "content_failed"
        elif mine:
            status = "unscored_infra"
        else:
            status = "unscored_infra"
    return {
        "schema": GENERATION_SCHEMA,
        "case_id": case["id"], "split": case.get("split"),
        "seat": seat_name, "lens": lens,
        "model": model, "params_hash": ph,
        "prompt_hashes": prompt_hashes,
        "status": status, "served_by": served_by,
        "fallback_for": fallback_for,
        "attempts": transport_calls,
        "retries": max(0, transport_calls - len(prompt_hashes)),
        "failure_count": failures,
        "error_classes": error_classes,
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "tokens_cached": cached_tokens,
        "tokens_estimated": any(
            e["tokens_estimated"] for e in mine
            if e["outcome"] == "ok"),
        "shadow_cost_usd": round(cost, 6),
        "shadow_price_known": price_known,
        "started_at": min((e["started_at"] for e in mine),
                          default=None),
        "finished_at": max((e["finished_at"] for e in mine),
                           default=None),
    }


def case_complete(records, seat_lenses):
    """A case is complete when every configured seat has a valid
    record for each of its bound lenses (fallback-served counts
    as valid — product semantics, §3.3)."""
    valid = {(r["seat"], r["lens"]) for r in records
             if r["status"] == "valid"}
    return all((seat, lens) in valid
               for seat, lenses in seat_lenses.items()
               for lens in lenses)


# ------------------------------------------------------------------
# Adapter: generation result -> the scorer's record shape.
# Field-for-field the record bench/scripts/run_confirmation_v2.py
# writes (that driver stays untouched), with two honest changes:
# cost_usd carries the metered shadow cost instead of 0.0, and
# reviewer_reports keep the report's fallback_for when present.

def to_attempt_record(case, report, cfg_name, cfg_sha, attempt,
                      run_label, shadow_cost_usd, duration_ms,
                      created_at):
    calls = sum(int(r.get("attempts") or 1)
                for r in report["reviewer_reports"])
    reps = []
    for r in report["reviewer_reports"]:
        entry = {"provider": r["provider"], "lens": r["lens"],
                 "status": r["status"],
                 "attempts": r.get("attempts")}
        if r.get("fallback_for"):
            entry["fallback_for"] = r["fallback_for"]
        reps.append(entry)
    return {
        "schema": "codereview.benchresult/1",
        "run": run_label,
        "attempt": attempt,
        "config": cfg_name,
        "config_sha256": cfg_sha,
        "seat_lenses": report.get("seat_lenses"),
        "case_id": case["id"],
        "split": case["split"],
        "category": case["category"],
        "created_at": created_at,
        "gate": report["gate"],
        "degraded": report["degraded"],
        "degraded_causes": report.get("degraded_causes"),
        "gate_profile": report["gate_profile"],
        "duration_ms": duration_ms,
        "calls": calls,
        "cost_usd": round(float(shadow_cost_usd), 6),
        "patch_sha256": report["patch_sha256"],
        "findings": report["findings"],
        "reviewer_reports": reps,
    }


# ------------------------------------------------------------------
# Driver

def _read_jsonl(path):
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def run_generation(cases, seats, seat_lenses, *, cache_dir,
                   out_dir, config_name, config_sha256, attempt=1,
                   run_label="baseline-v2-confirmation",
                   fallbacks=None, gate_profile="balanced",
                   allow_major=False, strict=False,
                   seat_meta=None, log=print,
                   case_budget_s=CASE_WALL_CLOCK_BUDGET_S):
    """Generate (or resume generating) every case x seat, writing
    per-case generation records and scorer-format attempt records.

    `seats`: {name: GenerationSeat}. `seat_lenses`: the explicit
    binding (S1). `fallbacks`: {lens: seat name} — the pre-declared
    fallback seats (§3.3), resolved against `seats`. An unknown
    lens or a fallback seat that is not in the panel is a loud
    ValueError, never a silent drop: what serves must be what was
    declared. The effective fallbacks join the run's identity —
    the manifest records them and a run identity hash over
    (config hash, binding, fallbacks); a resume whose fallbacks
    differ from the manifest's is a hard error, like a config
    hash mismatch.

    `case_budget_s`: the per-case wall-clock budget (the outer
    level of the two-level budget model, module docstring).
    Each seat is stamped with a case deadline on its own clock
    for the duration of the case's run_review call.

    Resume semantics: a (case, seat, lens) generation record
    already valid on disk is kept and never re-recorded; every
    case is still passed through run_review (the cache makes
    served calls free), and its attempt record is written only
    once the case is complete. A config hash mismatch with the
    existing manifest is a hard error — records from a different
    panel are never mixed into a run.
    """
    os.makedirs(out_dir, exist_ok=True)
    cache = ResponseCache(cache_dir)
    for seat in seats.values():
        if seat.cache is None:
            seat.cache = cache
    binding = core.normalize_seat_lenses(seat_lenses)
    fb = {}
    for lens, seat_name in (fallbacks or {}).items():
        if lens not in core.LENSES:
            raise ValueError(
                f"fallbacks: unknown lens {lens!r} (known: "
                f"{', '.join(core.LENSES)})")
        if seat_name not in seats:
            raise ValueError(
                f"fallbacks: lens {lens!r} names seat "
                f"{seat_name!r}, which is not in the panel "
                f"{sorted(seats)} — a fallback must name a "
                f"declared panel seat")
        fb[lens] = (seat_name, seats[seat_name])
    fb_map = {lens: name for lens, (name, _s) in fb.items()}
    run_identity = _canonical_sha({
        "config_sha256": config_sha256, "seat_lenses": binding,
        "fallbacks": fb_map})
    gen_path = os.path.join(
        out_dir, f"generation-attempt-{attempt}.jsonl")
    att_path = os.path.join(out_dir, f"attempt-{attempt}.jsonl")
    man_path = os.path.join(
        out_dir, f"generation-manifest-attempt-{attempt}.json")
    if os.path.isfile(man_path):
        with open(man_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        if manifest.get("config_sha256") != config_sha256:
            raise ValueError(
                "generation manifest config hash mismatch: "
                f"{manifest.get('config_sha256')} != "
                f"{config_sha256} — refusing to mix panels")
        if "fallbacks" in manifest \
                and manifest["fallbacks"] != fb_map:
            raise ValueError(
                "generation manifest fallbacks mismatch: "
                f"{manifest['fallbacks']} != {fb_map} — "
                f"refusing to mix serving configurations")
        manifest["fallbacks"] = fb_map
        manifest["run_identity_sha256"] = run_identity
    else:
        manifest = {"run": run_label, "attempt": attempt,
                    "config": config_name,
                    "config_sha256": config_sha256,
                    "fallbacks": fb_map,
                    "run_identity_sha256": run_identity,
                    "created_at": core._now_iso(), "cases": {}}
    prior = _read_jsonl(gen_path)
    # Resume granularity is the (case, seat, lens) record: a pair
    # already valid is never re-recorded, and a pair that failed
    # is recorded again when a later resume serves it.
    prior_valid = {(r["case_id"], r["seat"], r["lens"])
                   for r in prior if r["status"] == "valid"}
    att_done = {r["case_id"] for r in _read_jsonl(att_path)}

    gen_fh = open(gen_path, "a", encoding="utf-8")
    att_fh = open(att_path, "a", encoding="utf-8")
    summary = {"complete": [], "incomplete": {},
               "shadow_cost_usd": 0.0, "tokens_in": 0,
               "tokens_out": 0}
    try:
        for case in cases:
            context = (f"[bench-case: {case['id']}]\n"
                       f"{case['title']}\n"
                       f"{case.get('context') or ''}").strip()
            for seat in seats.values():
                seat.events = []
                # Per-case budget: stamp the deadline on the
                # seat's own clock for this case's calls.
                seat.case_deadline = seat.clock() + case_budget_s
            started = time.monotonic()
            try:
                report = core.run_review(
                    case["diff"], dict(seats), context=context,
                    allow_major=allow_major, strict=strict,
                    seat_meta=seat_meta or None,
                    seat_lenses=binding, fallbacks=fb or None,
                    gate_profile=gate_profile)
            finally:
                for seat in seats.values():
                    seat.case_deadline = None
            duration_ms = int(
                (time.monotonic() - started) * 1000)
            events = [e for seat in seats.values()
                      for e in seat.events]
            records = []
            for seat_name, lenses in binding.items():
                seat = seats.get(seat_name)
                for lens in lenses:
                    records.append(_seat_case_record(
                        case, seat_name, lens,
                        seat.model if seat else None,
                        seat.params_hash if seat else None,
                        events, report["reviewer_reports"],
                        binding))
            # Fallback seats outside the binding (or bound to a
            # different lens) get their own record when they
            # served — the substitution is on the record (§3.3).
            recorded = {(r["seat"], r["lens"]) for r in records}
            for r in report["reviewer_reports"]:
                key = (r["provider"], r["lens"])
                if r.get("fallback_for") and key not in recorded:
                    seat = seats.get(r["provider"])
                    records.append(_seat_case_record(
                        case, r["provider"], r["lens"],
                        seat.model if seat else None,
                        seat.params_hash if seat else None,
                        events, report["reviewer_reports"],
                        binding))
                    recorded.add(key)
            case_cost = sum(r["shadow_cost_usd"] for r in records)
            for r in records:
                if (case["id"], r["seat"], r["lens"]) \
                        not in prior_valid:
                    gen_fh.write(json.dumps(r) + "\n")
            gen_fh.flush()
            complete = case_complete(records, binding)
            # The frozen set holds COMPLETE cases only: an
            # incomplete case's attempt record is written by the
            # resume that completes it, never by a failed pass —
            # otherwise the scorer would consume a degraded
            # record for a case generation later served.
            if complete and case["id"] not in att_done:
                att_fh.write(json.dumps(to_attempt_record(
                    case, report, config_name, config_sha256,
                    attempt, run_label, case_cost, duration_ms,
                    core._now_iso())) + "\n")
                att_fh.flush()
            manifest["cases"][case["id"]] = {
                "complete": complete,
                "unscored_infra": sorted(
                    {r["seat"] for r in records
                     if r["status"] == "unscored_infra"}),
                "content_failed": sorted(
                    {r["seat"] for r in records
                     if r["status"] == "content_failed"}),
                "shadow_cost_usd": round(case_cost, 6)}
            if complete:
                summary["complete"].append(case["id"])
            else:
                summary["incomplete"][case["id"]] = sorted(
                    {r["seat"] for r in records
                     if r["status"] != "valid"})
            summary["shadow_cost_usd"] += case_cost
            summary["tokens_in"] += sum(
                r["tokens_in"] for r in records)
            summary["tokens_out"] += sum(
                r["tokens_out"] for r in records)
            log(f"[{case.get('split')}] {case['id']}: "
                f"complete={complete} gate={report['gate']} "
                f"shadow=${case_cost:.4f}")
    finally:
        gen_fh.close()
        att_fh.close()
    manifest["summary"] = {
        "complete_cases": len(summary["complete"]),
        "incomplete_cases": summary["incomplete"],
        "shadow_cost_usd": round(summary["shadow_cost_usd"], 6),
        "tokens_in": summary["tokens_in"],
        "tokens_out": summary["tokens_out"],
        "budgets": {
            "per_job_wall_clock_s": sorted(
                {seat.wall_clock_budget_s
                 for seat in seats.values()}),
            "per_case_wall_clock_s": case_budget_s},
        "shadow_price_note": SHADOW_PRICE_NOTE}
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    summary["generation_records"] = gen_path
    summary["attempt_records"] = att_path
    summary["manifest"] = man_path
    return summary
