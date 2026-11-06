# Historical review records (test fixtures)

Verbatim copies of two run-output records from this repo's own
review history, kept as fixtures so the test suite is
self-contained in the sdist (D-003 closure, 2026-11-06). The
repo-root originals are untouched:

- `review-v096/codereview-20261104-233259.json` — a v0.9.6
  review record (2026-11-04). Original md5
  59218dad182d5a35f6392872b6854a37. Read by
  tests/test_sarif.py (RealRecordTests) and
  tests/test_v100_integration.py (legacy sidecar check).
- `review-v15-verify1/codereview-20261104-225424.json` — a
  v0.9.4 verify record (2026-11-04), byte-identical to the
  original (md5 ad3112075e7d1b7908ae050059a794b9). Read by
  tests/test_v111_dispute_probes.py
  (RegenerationAgreementTests).

One documented transformation in the v096 copy only: the
record quotes, inside an old finding's evidence, a mailer
assignment whose value was already a redaction marker in
square-bracket form. That marker form is not in the fixture
secret-hygiene scan's placeholder exemption (which recognises
the angle-bracket form), so the marker was rewritten in
angle-bracket form — 23 occurrences, all the same swap, no
other bytes changed. The value was a placeholder before the
swap and remains one after it; no real secret is involved.
