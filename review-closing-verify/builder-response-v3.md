Verification of closing round 1 (3013656..2fbf94f, BLOCKED, 20 blocking findings); delta 2fbf94f..61e137d. The full suite passes on this tree (682 tests; recorded in this round). A previous verification attempt left nine findings unresolved; their evidence is stated first. All 20 findings are listed below.

THE NINE OPEN ITEMS, with evidence:
- 531bd4e5a458 — rebutted by probe: sidecar validation in core.py records a problem whenever the digest's file is absent ("sidecar file missing") and whenever sha256(content) != digest or the lengths differ; empty, malformed, and traversal digests each end in a recorded problem (workup probe under probes/, results captured).
- dd391599588d — rebutted: findings are normalized as _normalize_finding(raw_f, serving_name), where serving_name is the provider actually called; naming the serving seat is the record-fidelity rule (the opposite was defect 78ddf4d5ea27, fixed and ratified).
- 0bb1b939ab67 — fixed by commit 564e054: the disputes inventory skips any row whose id is already counted ("if row["id"] in seen: continue"; "seen.add(row["id"])").
- e9ef62daa1a0 — fixed by commit 99fe588: span resolutions are cached ("cache[spec] = _commit_set(repo, spec)") and degenerate ranges fall back to the recorded head.
- 78d6c78b3865 — fixed by commit 6fa83f6: acceptance.py computes m3 = (sum(1 for c in scores.values() if c["correct"]) / len(scores)) if scores else 0.0 — no empty-corpus division.
- 764e1d15a218 — fixed by commit dee84d0: the doctor path refuses a fallback seat that is already a primary ("fallback seat ... is already a primary seat", return 2).
- 19abd575191e — dispositioned in dispositions.jsonl (standing item, packet #50).
- 887c490bd9eb — dispositioned in dispositions.jsonl as downgraded (packet #47).
- afe66da23121 — dispositioned in dispositions.jsonl as downgraded (packet #46).

THE ELEVEN BOTH SEATS CLEARED IN THE PREVIOUS ATTEMPT — each dispositioned in dispositions.jsonl as retired_out_of_scope (artifact class: the claims cite committed evidence/record text, not executable product behaviour; group packets #51–55): f62ebf2dc0e3, b55a82da564b, 3208f6f6f185, 3fc43145aad1, efae60d4f419, df160cd55adb, ccf336248731, 5809b43af807, 1608bc89b954, e48b43201f50, e58a7a210be7.

Delta composition: the fixes above with their regression tests, probes with captured results, dispositions.jsonl (114 entries), and the committed round-1 record directories (archived artifacts under the §5.4 rule). The deterministic patterns behind the retired findings do not re-fire on product source anywhere in this delta.
