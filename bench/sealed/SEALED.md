# SEALED — Tech Lead evaluation set (do not open for tuning)

**Sealed:** 2026-11-05 · **Cases:** 75 · **Manifest:** `sealed-manifest.json`
(sha256 `ab5a895fc5b6392999a939a39487cc942d162f091d5c128ea34d40c3c46067a1`;
per-case sha256 in the manifest, truncated in the table below)

## Seal rules (solution §3.6, binding)

- This set is **evaluation-only**. No case in it may be used to tune prompts,
  rubrics, thresholds, routing, or the seat. Tuning happens on the 48-case
  acceptance corpus, which is dev data now.
- **Burn rule:** one final evaluation attempt per sealed set. If the attempt
  fails its thresholds, this set becomes dev data and a NEW sealed set must be
  assembled before any further attempt.
- The set's labels were fixed before the redesigned Tech Lead existed. Any
  change to a case file changes its hash and voids the seal.

## Construction — three routes

**(a) False-positive corpus (7 cases, S-F01…S-F07).** The step-3 blind,
probe-first adjudication of the 91 unmatched benchmark findings
(§2.3) produced exactly 7 speculative false positives. Each is recast as an
adjudication case: the finding as raised, the benchmark diff as the region,
and the adjudication basis as the refutation position (provenance field in
each case says `constructed-from-adjudication` — these are not recorded panel
refutations, and the set does not pretend otherwise). Expected decision for
all 7: `sustain_refutation`.

**(b) Untuned machinery hold-outs (3 cases, S-H66…S-H68).** The acceptance
corpus index names them itself: "The three queued v0.10.0 items
(4ce0212286e0, 6b29fe953939, bf4c451e8751) are the reserved hold-out for
changes tuned on this stratum: never tuned on, no corpus cases exist for
them." Their ruling packets carry the same designation ("Ruling it is not
tuning — the case is then frozen as an untuned evaluation item"). The M01–M04
machinery cases and their mutants were **excluded**: they were in the
acceptance run and informed the failure analysis, so they are dev data.
Labels: owner rulings with probe basis evidence (hashes verified against
`probes/results/` artifacts): `split`, `split`, `sustain_refutation`.

**(c) Owner dispositions, probe-grounded subset (65 cases, S-D01…S-D65).**
Qualification rule (applied strictly, per §3.6): the entry is a merits
decision (`sustain_refutation` / `sustain_finding` / `split` / `downgraded` /
`fixed`), AND its `basis_evidence` sha256 **verifies against the actual probe
artifact file on disk**. A probe-grounded label rests on executed evidence,
not on anyone's judgement of the shadow Tech Lead's output.

**The temporal route qualified zero entries — stated plainly.** §3.6 also
allows labels "ruled before shadow output existed". Every one of the 116
store entries is timestamped 2026-11-05T01:26:49Z or later; the first shadow
Tech Lead output (the acceptance run) began 01:14:59Z the same night
(progress.log, VM clock = UTC). Recording time is not ruling time, but the
store cannot establish any single ruling as pre-shadow, so no entry was
admitted on temporal grounds. 16 merits entries with no probe basis were
excluded for exactly this reason.

**All 116 dispositions are accounted for** in `sealed-manifest.json`
(`excluded_dispositions`, per-item reasons): 65 sealed via route (c),
3 via route (b), 29 non-merits types (retired/superseded — no decision on the
claim exists to evaluate against), 16 merits without probe basis, and 3 whose
basis hash is recorded but **unverifiable**: the shadow set's three real
defects (833912a09fa3, 4cf81c69d7cf, 633acb885291). Their probe artifacts at
the recorded paths now hash differently — the post-fix probe re-runs
overwrote the pre-fix outputs — and no copy matching the recorded hash exists
anywhere in the workspace. Excluded rather than admitted on trust.

Corpus-overlap note: 15 of the 116 are source findings of acceptance-corpus
cases. Overlap alone did not qualify or disqualify anyone: the sealed copies
here are independent case files, and every admitted one carries a verified
probe basis (the corpus labels themselves were inputs copied from these same
probe-backed rulings, so the direction of dependence runs from the probe to
both).

## Scoring

- `exact`: the seat's final decision must equal `expected.decision`
  (for `fixed`, expected is `sustain_finding` — the finding was real and a
  fix shipped; for `downgraded`, `sustain_finding` with
  `expected.severity_after` set where the packet states the reduced level).
- `sealed_split` (5 cases): the ruling was `split` — neither side wholly
  correct. Scored correct iff the adjudication sustains neither side wholly:
  operationally, a harness escalation whose recorded reason is a merits split,
  or a verdict whose reasoning assessment matches the recorded validity
  grades (claim partially valid, refutation partially valid). A clean
  sustain of either side scores incorrect.
- Report the **deterministic path** (probe-settled cases) and the **model
  path** separately, per §3.3.2 — never blended. 72 of 75 cases are
  probe-settled; the model path is the residue and is small by construction
  of this set — that asymmetry is a property of the label-independence rule,
  and any unlock claim must state it.
- 6 cases (S-D60…S-D65) had **no recorded panel refutation**; their
  refutation field says so (`provenance: none-recorded`) and carries the
  workup probe as the only counter-position. They are flagged so the
  evaluation can report results with and without them.
- Code regions were re-located at the source record's head commit for
  68 of 75 cases; the other 7 carry the finding's validated evidence quote
  as the region text with `located: false`, per case.

## Case inventory

| Case | Route | Source finding | Expected | Sev | sha256 |
|---|---|---|---|---|---|
| S-D01 | disposition | `09c536d15270` | sustain_refutation | major | `91b40c11a1788abc…` |
| S-D02 | disposition | `0ad4ed7db98e` | sustain_refutation | major | `de74c091f1d1e9d3…` |
| S-D03 | disposition | `0e57186e8be8` | sustain_refutation | major | `6749efa09d19faa4…` |
| S-D04 | disposition | `19a537eb386b` | sustain_finding | major | `945cc5f35ff463bf…` |
| S-D05 | disposition | `1aec997aaec4` | sustain_refutation | major | `1471dda6707af871…` |
| S-D06 | disposition | `20e4194e5ed9` | sustain_finding | major | `99ca0c1e68081b06…` |
| S-D07 | disposition | `2242edbba9c9` | sustain_refutation | major | `87d7d4a8c79133ec…` |
| S-D08 | disposition | `290d549f2809` | sustain_finding | major | `f0b67c7f29ddb246…` |
| S-D09 | disposition | `35dbb7d20941` | sustain_refutation | major | `3dd951ef1d5cfbd8…` |
| S-D10 | disposition | `3cecf66f6ce5` | sustain_finding | major | `d0e808788138ebef…` |
| S-D11 | disposition | `3d9645200bc5` | sustain_refutation | major | `02e99aeee4d270a4…` |
| S-D12 | disposition | `3f50bf6b3349` | sustain_finding | major | `c8a797c48e6f3ae9…` |
| S-D13 | disposition | `3fc4862824c9` | sustain_finding | major | `c890307068fbc2ef…` |
| S-D14 | disposition | `474297e6ffdc` | sustain_refutation | major | `fc52b9c35dde2821…` |
| S-D15 | disposition | `6219e04d4c00` | sustain_refutation | major | `c1e294d6629a99f8…` |
| S-D16 | disposition | `78ddf4d5ea27` | sustain_finding | major | `a6c3338c1248a655…` |
| S-D17 | disposition | `931ea3882b76` | sustain_finding | major | `69fd08b55b0965db…` |
| S-D18 | disposition | `9a4415ddafa6` | sustain_finding | major | `e546960e3c6aeb4a…` |
| S-D19 | disposition | `ae9e58378eee` | sustain_finding | major | `7c86932dcf7aee52…` |
| S-D20 | disposition | `bca4074a632c` | sustain_refutation | major | `3e5109e230e7968b…` |
| S-D21 | disposition | `c5f02551d077` | sustain_refutation | major | `307f4b12aa7f85cf…` |
| S-D22 | disposition | `d93089253022` | sustain_refutation | major | `712579dda5526778…` |
| S-D23 | disposition | `e1e22d48db4d` | sustain_refutation | major | `4a8bd611ae2e01b2…` |
| S-D24 | disposition | `eae8137a6db3` | sustain_finding | major | `db6f4400a4003fe7…` |
| S-D25 | disposition | `ec925437d0e3` | sustain_finding | major | `763cd88e59c5b3f3…` |
| S-D26 | disposition | `f56cd4a0b6c9` | sustain_finding | major | `49115cc1a5c0aa75…` |
| S-D27 | disposition | `4cba208656d3` | sustain_refutation | major | `7492d00285f07404…` |
| S-D28 | disposition | `97feb799979e` | sustain_refutation | major | `7677fbb95709c2cb…` |
| S-D29 | disposition | `60eb09183ee5` | sustain_refutation | major | `87048c8768af4689…` |
| S-D30 | disposition | `127ddee9be1b` | sustain_refutation | major | `bedeabc542c205ca…` |
| S-D31 | disposition | `7514429a36b2` | sustain_refutation | major | `0d37d7de43b78d45…` |
| S-D32 | disposition | `99fe18f50ec3` | sustain_finding | major | `4ade3efb199ecfdf…` |
| S-D33 | disposition | `e1570280c036` | sustain_refutation | major | `48550b36f3139cf2…` |
| S-D34 | disposition | `55752b0dc5b7` | sustain_refutation | major | `2e6dc5f56851817a…` |
| S-D35 | disposition | `934fab88a12e` | sustain_finding | major | `1afcf2e5c4c46146…` |
| S-D36 | disposition | `179ece0e030e` | sustain_finding | major | `42f3e48f14b6c793…` |
| S-D37 | disposition | `b2b1f776d566` | sustain_finding | major | `f95fe6c60fc676a1…` |
| S-D38 | disposition | `30b316c77b43` | sustain_finding | major | `5a66b9da0f2403e0…` |
| S-D39 | disposition | `2eb60efeeace` | sustain_refutation | major | `64e37bac8651b94a…` |
| S-D40 | disposition | `ba2479886886` | sustain_refutation | major | `1f431143e310b4c7…` |
| S-D41 | disposition | `07a9a2646925` | sustain_refutation | major | `be63ce161eb416c8…` |
| S-D42 | disposition | `55c815ff5fbe` | sustain_finding | major | `57d245f24a50eea7…` |
| S-D43 | disposition | `8479293e76ed` | sustain_refutation | major | `872c6a968ffa653c…` |
| S-D44 | disposition | `f46397a84121` | sustain_finding | major | `608688f3e93e85d8…` |
| S-D45 | disposition | `e8c5d3fd8a25` | split | major | `29e7c9407f331b49…` |
| S-D46 | disposition | `8f77565b56a4` | sustain_refutation | major | `96bfdf2620a73337…` |
| S-D47 | disposition | `536112b7d4dd` | sustain_refutation | major | `b706c217faec0171…` |
| S-D48 | disposition | `610a06422389` | sustain_refutation | major | `ac5b2ae14adcad65…` |
| S-D49 | disposition | `44ace5079160` | sustain_refutation | major | `fb4fac79987818fa…` |
| S-D50 | disposition | `42011b7abf72` | sustain_refutation | major | `1e44d942cb218238…` |
| S-D51 | disposition | `b7d613672e71` | split | major | `d664f3990f8614e9…` |
| S-D52 | disposition | `5e89ea2d985b` | sustain_refutation | major | `fbb46c49b2346b4d…` |
| S-D53 | disposition | `ad6e36800a86` | sustain_refutation | major | `6b718ec5cbfcf5e8…` |
| S-D54 | disposition | `69a23ebb9f27` | sustain_refutation | major | `325775430d895f61…` |
| S-D55 | disposition | `32587160c9fc` | sustain_refutation | major | `354d52239c2276d6…` |
| S-D56 | disposition | `f43f2968433d` | sustain_refutation | major | `fc60e6f7678a0ed9…` |
| S-D57 | disposition | `9489ee49db6f` | sustain_finding | major | `5f0822b311a926c6…` |
| S-D58 | disposition | `21bb4af17e22` | sustain_finding | major | `9a2591952c17e9c1…` |
| S-D59 | disposition | `b9e2819976fe` | split | major | `db4e9180dd718b30…` |
| S-D60 | disposition | `afe66da23121` | sustain_finding | major | `931f6b4916df5704…` |
| S-D61 | disposition | `887c490bd9eb` | sustain_finding | major | `03c23ccbb44a323b…` |
| S-D62 | disposition | `ca9fcd9ca7c2` | sustain_finding | minor | `0506a90dec0e57b8…` |
| S-D63 | disposition | `6508525840b4` | sustain_finding | minor | `59bfe4285446b234…` |
| S-D64 | disposition | `531bd4e5a458` | sustain_refutation | major | `81f076c39b554bee…` |
| S-D65 | disposition | `dd391599588d` | sustain_refutation | major | `3bccf9668152afc7…` |
| S-H66 | machinery_holdout | `4ce0212286e0` | split | major | `0333952d43a5ca98…` |
| S-H67 | machinery_holdout | `6b29fe953939` | split | major | `5192809c21de8fd2…` |
| S-H68 | machinery_holdout | `bf4c451e8751` | sustain_refutation | major | `58f7eb5f03b762d0…` |
| S-F01 | fp_corpus | `7c5396bfde36` | sustain_refutation | minor | `5f0cbc6720c382db…` |
| S-F02 | fp_corpus | `f6869eb188d5` | sustain_refutation | minor | `4dafcb1d8947f393…` |
| S-F03 | fp_corpus | `d39a517bc276` | sustain_refutation | minor | `1fd578b38de8660f…` |
| S-F04 | fp_corpus | `82a44ce5e721` | sustain_refutation | major | `484036d9986c38df…` |
| S-F05 | fp_corpus | `f0e6f4c3a44a` | sustain_refutation | minor | `f382d855cd2f41fa…` |
| S-F06 | fp_corpus | `74798f3ab150` | sustain_refutation | minor | `8e57e5a8a0e9e3c6…` |
| S-F07 | fp_corpus | `07ac0287263a` | sustain_refutation | minor | `c5f154cbb3ad94a5…` |
