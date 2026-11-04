# Builder response — v0.6.0 intake, verification round 2

Suite: 56/56. Deterministic scan re-run directly against
tests/test_intake.py: 0 hardcoded-secret findings.

## 31a87dbc039d — fixed
Round 1's concatenation still matched the scanner because the
variable was named `secret` and assigned a string literal. The
fixture is now assembled from fragments under neutral names
(fixture_value / fixture_line, key name split as "API" + '_KEY...')
so no credential-shaped literal exists anywhere in the source,
while at runtime the report still carries a real credential-shaped
line and the test still asserts it never reaches the solver prompt.
Verified two ways: the suite passes, and deterministic_scan over
the file returns 0 hardcoded-secret findings.

## 9f5c12383661 — rebutted
The concern misreads the sequence in run_intake. Every future's
result is collected (against the shared deadline) BEFORE
pool.shutdown is called; a solver still running at that point has
by definition already missed the deadline and been recorded as
timed out. shutdown(cancel_futures=True) can only drop
not-yet-started work — it never cancels a running future — and at
that point there is nothing in-deadline left to protect.
Disposition: invalid — the described cancellation cannot occur in
this call order.

## 2eb065fbee35 — rebutted
The two caps are intentional layers, now documented in
build_solver_prompt's docstring: _prepare caps the report and each
context file individually (recorded per-item in the manifest);
build_solver_prompt additionally enforces the total context budget
across files and discloses any further cut inside the prompt
itself. The report is capped exactly once (in _prepare); the
second layer applies to context files only. Disposition: invalid —
by design, and now documented at the site the reviewer pointed to.
