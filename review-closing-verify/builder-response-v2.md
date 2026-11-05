Verification of closing round 1 (span 3013656..2fbf94f, gate BLOCKED, 20 blocking findings), verification delta 2fbf94f..61e137d. All round-1 fixes are merged and the full suite passes on this exact tree (682 tests; the run's test command records it). The delta's bulk is the committed round-1 record directories (archived artifacts under the §5.4 rule) plus probes and dispositions.jsonl; the product-source changes are small and their decisive lines are quoted verbatim below.

HOW TO RESOLVE: use ONLY the resolution statuses fixed, invalid, still_present, unclear. Disposition-store types (retired_out_of_scope, downgraded) are NOT resolution statuses — a resolution submitted with one is machine-downgraded to unclear. For a finding the owner has dispositioned in dispositions.jsonl, the ruled outcome is recorded there: resolve it invalid and cite the store entry as your evidence. The prior-findings JSON in this prompt is truncated by the harness after the 14th finding; the COMPLETE list of all 20 finding ids appears below — resolve every one of them.

FIXED in this delta (resolve fixed):
- 78d6c78b3865 — commit 6fa83f6. acceptance.py now reads: m3 = (sum(1 for c in scores.values() if c["correct"]) / len(scores)) if scores else 0.0 — the empty-corpus denominator is guarded, and metric sets are restricted to cases actually present. (The claim named bench.py; bench guards every denominator it divides by.)
- 0bb1b939ab67 — commit 564e054. The disputes inventory deduplicates across records: "if row["id"] in seen: continue" / "seen.add(row["id"])" — one dispute counts once however many record files serialize it.
- e9ef62daa1a0 — commit 99fe588. records_touching_span caches range resolutions ("cache = {span: span_commits}"; "cache[spec] = _commit_set(repo, spec)") and degenerate X..X ranges fall back to the recorded head instead of being dropped.
- 764e1d15a218 — commit dee84d0. The cli.py doctor path refuses a fallback duplicating a primary: "if fb_name in providers:" it reports "fallback seat ... is already a primary seat" and returns 2 — the same guard the review path already had.

REBUTTED by executable probe (resolve invalid):
- 531bd4e5a458 — evidence-sidecar validation fails closed. core.py builds path = os.path.join(evidence_dir, digest); "if not os.path.isfile(path)" records the problem "sidecar file missing", and content is accepted only when hashlib.sha256 of the file equals the recorded digest and the lengths match. Empty, malformed, and traversal digests all end in a recorded problem — the workup probe exercised all three shapes and none was accepted.
- dd391599588d — normalized findings record serving_name, the provider actually called: _normalize_finding(raw_f, serving_name). Naming the serving seat is the record-fidelity requirement; the opposite behaviour was itself defect 78ddf4d5ea27, fixed and ratified.

OWNER-DISPOSITIONED in dispositions.jsonl (resolve invalid; cite the store entry):
- 887c490bd9eb — downgraded (packet #47: five subcommand seams lacked functional tests; two now covered).
- afe66da23121 — downgraded (packet #46: archived-text classification coupling is designed; its failure direction is conservative — a finding stays kept, never hidden).
- retired_out_of_scope, artifact class (claims cite committed evidence/record text, not executable product behaviour; group packets #51–55): f62ebf2dc0e3, b55a82da564b, 3208f6f6f185, 3fc43145aad1, efae60d4f419, df160cd55adb, ccf336248731, 5809b43af807, 1608bc89b954, e48b43201f50, e58a7a210be7.
- 19abd575191e — standing, already dispositioned in the earlier process-tooling packet set (packet #50).

The nine deterministic findings in this list do not re-fire on product source anywhere in this delta; the only deterministic scan hits cite the archived round-1 record directories themselves (quoted historical text), which the §5.4 rule classifies as archived-text.
