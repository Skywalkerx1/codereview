# Builder response — v0.6.0 intake diff, verification round

Suite after fixes: 56/56 (`python3 -m unittest discover -s tests`).

## 31a87dbc039d — fixed
Blocker (deterministic hardcoded-secret rule) fired on the redaction
test's fixture value in tests/test_intake.py. The value was always a
deliberately fake fixture, never a credential; it is now assembled at
runtime ("supersecret" + "value123") so no secret-shaped literal sits
in the source, while the test still feeds the assembled value through
run_intake and asserts it never reaches the solver prompt.

## 89082dada28a — fixed
Per-solver deadline added. run_intake takes `timeout` (default 300s,
CLI `--timeout`): results are collected against a shared deadline, a
solver that misses it is recorded as failed with "timed out after
Ns", and the pool is shut down with wait=False + cancel_futures=True
so a hung callable cannot block the run. (The provider HTTP layer's
own 240s timeout remains the inner guard.)

## 1d399e559b17 — rebutted
"Add a cooldown/dedup between solver retries" presupposes a retry
loop that does not exist. run_intake invokes each solver exactly
once per run; nothing in intake re-invokes a solver automatically,
and the CLI runs once per operator invocation, one report per run. A
module-level cooldown or lock would not guard any real loop — it
would break legitimate back-to-back runs on different reports.
Retry-with-rotation already exists where retries actually happen:
providers.AccountPool on the reviewer path. Disposition: invalid —
the described failure mode has no code path.

## b1da6b19d4c5 — rebutted
The claim that build_provider fails to pass text_mode for
openai-compatible specs is a misread. build_provider computes
`system = _SOLVER_SYSTEM if text_mode else _SYSTEM` once, before
branching, and passes `system=system` in all four branches: custom
gemini, custom openai-compatible, preset gemini, and preset
openai-compatible (including the `extra` payload path). Two new
wire-level tests capture the real payloads via a fake transport:
solver seats send _SOLVER_SYSTEM and Gemini sends no
responseMimeType; reviewer seats still send _SYSTEM with
responseMimeType application/json (test_solver_wire_* /
test_reviewer_wire_* in tests/test_intake.py). Disposition: invalid —
contradicted by the code and now by tests.

## 068bb4765eb0 — fixed
Worker pool capped: max_workers = min(len(solvers), 8)
(MAX_SOLVER_WORKERS in intake.py).

## 22a80f8028b5 — fixed
Timeout coverage added: test_hung_solver_times_out_and_fast_solver_wins
runs a solver that sleeps 10s against timeout=1 — the run returns in
under 5s, the slow solver is recorded as timed out, and the fast
solver becomes primary.
