#!/usr/bin/env python3
"""verify-registration — recompute every hash registered in the
2026-11-05 pre-registration (and its §3 addenda) from committed files,
and report PASS / FAIL per item.

Implements solution finding S3 (codereview-baseline-v2-void-solution-
2026-11-05.md §6): run this before any run under the registration or
under Addendum A. Exit code is 0 only if every item verifies; an item
whose registered construction is documented as superseded (the A5 set
hash; the pre-append registration body hash, item 6) is reported
SUPERSEDED, not FAIL, and its replacement (the A5 per-file manifest,
Addendum A item 8; the post-append body hash) is verified instead.

Items checked:
  1. Expanded-clean manifest — SLOT-CLEANHASH (§3 addendum):
     sha256 of bench/expanded-clean/manifest.json at HEAD.
  2. Sealed-set manifest — pre-registration §2.2:
     sha256 of bench/sealed/sealed-manifest.json at HEAD, plus every
     per-case sha256 inside it against bench/sealed/cases/<id>.json.
  3. A5 holdout set hash — pre-registration §1.3: SUPERSEDED
     (construction not reproducible; bench/BASELINE-V2-2026-11-05.md
     §6). Replaced by item 4.
  4. A5 per-file manifest (Addendum A item 8): every file's sha256
     recomputed from the committed blob at the manifest's recorded
     source commit.
  5. SLOT-POLICY freeze identity (§3 addendum): sha256 of
     src/codereview/core.py and of bench/configs/
     panel-baseline-2026-11-04.json at the implementing commit
     recorded in the fill (736a55d).
  6. Pre-registration integrity: the FOOTER-HASH line still carries
     the registered value, and the body hash — sha256 of everything
     above the FOOTER-HASH line, the construction recorded in the
     registration and in Baseline v2 §6 — equals the documented
     current value. The body state after the two authorised §3
     fills (SLOT-CLEANHASH, then SLOT-POLICY) is SUPERSEDED by the
     §3 Addendum A append of 2026-11-05 (Addendum A signed the same
     day; addendum body hash d83c93977d66769c..., recorded in the
     registration's §3); the post-append state is the current value
     and is verified by strict equality. The §3 A1-A3 append of
     2026-11-05 (the three §2 protocol amendments, ratified by the
     owner that day before any §2 sealed attempt) supersedes the
     post-Addendum A state in turn; the post-A1-A3 body hash is the
     current value, verified by strict equality, with both earlier
     states reported SUPERSEDED.
  7. B2 confirmation registration (pre-registration-b2-2026-11-05
     §10): (a) sha256 of bench/generation-v3/SEALED-MANIFEST.json
     at HEAD; (b) every per-file sha256 in that manifest (176 case
     files + 105 validation files = 281) recomputed from the
     committed blob at the manifest's source commit 0e3bf46;
     (c) the B2 policy freeze — core.py and the bench panel
     config at freeze commit a88df64; (d) the B2 registration's
     integrity, pattern of item 6: the FOOTER-HASH line carries
     the drafting value, the drafting body state and the
     post-signature §13 state (signatures recorded 2026-11-06,
     JCL + CC e-sign by owner confirmation in chat — the
     Addendum A execution form) are SUPERSEDED, and the
     post-runner-pin §13 body state is the current value,
     verified by strict equality.

Stdlib only. No network, no seat calls, no scoring.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

GOAL_FILES = os.path.expanduser(
    "~/workspace/goals/reviewloop-multi-model-code-review-product/files")
DEFAULT_REGISTRATION = os.path.join(
    GOAL_FILES, "pre-registration-2026-11-05.md")
DEFAULT_A5_MANIFEST = os.path.join(GOAL_FILES, "a5-manifest-2026-11-05.json")

EXPANDED_CLEAN_SHA256 = \
    "4af817e51d6d766e985d0a411e78191a16b92e909afc7d168986fa1538f52441"
SEALED_MANIFEST_SHA256 = \
    "ab5a895fc5b6392999a939a39487cc942d162f091d5c128ea34d40c3c46067a1"
A5_SET_HASH_REGISTERED = \
    "7e160d3b35730d6b85f22841dec70fb37835fc4ad3f43c84c4315d808609f4b3"
POLICY_FREEZE_COMMIT = "736a55d9f52318b808a9ce203ef8d9116edf3b63"
CORE_PY_SHA256 = \
    "70f26767a8200bdf27d48510233fc15a0b1ba36697ac6d71bbbb740446663d1a"
PANEL_CONFIG_SHA256 = \
    "26ca5b303827a00f3c5684c4be18a0b1ce6debdd5e6db5688cf339227f4b0440"
REGISTRATION_FOOTER_HASH = \
    "258c7674f156cab4ddea0dda44f3faedff93646d8c9db523ed9eb974f766cd2d"
# Body hash after the two authorised section-3 fills, as documented in
# bench/BASELINE-V2-2026-11-05.md section 6 (the pre-fill body hashed
# 4bf3b4b1... immediately before the SLOT-POLICY fill). Superseded by
# the section-3 Addendum A append below; retained as the expected
# value of the SUPERSEDED row in check 6.
REGISTRATION_BODY_SHA256_SUPERSEDED = \
    "9e38217efbbd6d39a3513d06c200209d4355bddec3b07faaa146e2be0ece07ac"
# Body hash after the section-3 Addendum A append of 2026-11-05 —
# authorised by Addendum A itself (signed that day by the owner and
# one independent reviewer; addendum body hash
# d83c93977d66769c614f6510159c0713f3b2addf8ba3c7854a7d6b5bdeea528d,
# recorded in the registration's section 3 alongside this append).
# Superseded by the section-3 A1-A3 append below; retained as the
# expected value of the second SUPERSEDED row in check 6.
REGISTRATION_BODY_SHA256_POST_ADDENDUM_A = \
    "5d9bea160d9ee93f2aebd9a194cef41e602b0d79e63f95ae10780115b12a74df"
# Body hash after the section-3 A1-A3 append of 2026-11-05 —
# the three section-2 protocol amendments (deterministic-path
# scoring decision-only; the probe-settled set for M2; the
# dismissal veto across all strata), ratified by the owner that
# day adopting the settlement memo's recommendations
# (tl-sealed-protocol-settlement-2026-11-05.md) and appended to
# section 3 before any section-2 sealed attempt. This is the
# current authoritative body state.
REGISTRATION_BODY_SHA256_CURRENT = \
    "a98d93788e875a5525f8cf2d5475fabc6ec4598e9a4eb97a2daff6d2b513cd9f"

# Item 7 (B2 confirmation registration, pre-registration-b2-
# 2026-11-05 §10): generation-v3 seal + B2 policy freeze + the
# B2 registration's integrity.
DEFAULT_B2_REGISTRATION = os.path.join(
    GOAL_FILES, "pre-registration-b2-2026-11-05.md")
GENERATION_V3_SEALED_MANIFEST_SHA256 = \
    "35bea8029e94fbda7bf961f646325cab5b5baa5287634a07a6b6638852b40690"
GENERATION_V3_SOURCE_COMMIT = \
    "0e3bf464d930b48e4d89be64e90e2029b84a271d"
B2_FREEZE_COMMIT = "a88df64558aa58e4eea8e1288dfdf3c8d3fa8030"
B2_CORE_PY_SHA256 = \
    "afe6bc2e1557543e6cd05d6132063463de6dcd0be01ea99a91bc3478bb8d6543"
B2_PANEL_CONFIG_SHA256 = \
    "26ca5b303827a00f3c5684c4be18a0b1ce6debdd5e6db5688cf339227f4b0440"
# The B2 registration's FOOTER-HASH line carries the drafting
# body hash (the value §10's constant block names, filled at
# signing from the footer).
REGISTRATION_B2_FOOTER_HASH = \
    "58d7c5b120ffe9d37885ceb5f335542b7f7226f28c36ace92951635198baeea1"
# Body hash after the §13 signature fill of 2026-11-06
# (signatures recorded there: JCL + CC, e-sign by owner
# confirmation in chat — the Addendum A execution form).
# Superseded by the §13 runner/scorer hash-pin fill below.
REGISTRATION_B2_BODY_SHA256_POST_SIGNATURE = \
    "35620d5ee6f7cd457ad71b6bf24be6a500238deb51457a12136647b11295303d"
# Body hash after the §13 runner/scorer hash-pin fill of
# 2026-11-06 (§8 (a)–(e)) — the current authoritative state
# of the B2 registration, verified by strict equality.
REGISTRATION_B2_BODY_SHA256_CURRENT = \
    "368e5012654e5fffff3383678ff1179ac5af09fe3e330687a23c26ce644ef6ee"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Repo:
    def __init__(self, root):
        self.root = root

    def blob(self, rev, path):
        return subprocess.check_output(
            ["git", "-C", self.root, "cat-file", "blob", f"{rev}:{path}"])


def short(h):
    return h[:12] + "…" if h else "—"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registration", default=DEFAULT_REGISTRATION,
                    help="path to the pre-registration document")
    ap.add_argument("--a5-manifest", default=DEFAULT_A5_MANIFEST,
                    help="path to the A5 per-file manifest JSON "
                         "(Addendum A item 8)")
    ap.add_argument("--registration-b2",
                    default=DEFAULT_B2_REGISTRATION,
                    help="path to the B2 pre-registration document "
                         "(item 7)")
    ap.add_argument("--sets-rev", default="HEAD",
                    help="git revision the set manifests are verified "
                         "at (default: HEAD)")
    args = ap.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = subprocess.check_output(
        ["git", "-C", script_dir, "rev-parse", "--show-toplevel"],
        text=True).strip()
    repo = Repo(root)
    head = subprocess.check_output(
        ["git", "-C", root, "rev-parse", args.sets_rev],
        text=True).strip()

    rows = []  # (item, expected, recomputed, status)

    def check(item, expected, recomputed):
        rows.append((item, expected, recomputed,
                     "PASS" if expected == recomputed else "FAIL"))

    # 1. Expanded-clean manifest (SLOT-CLEANHASH).
    check("expanded-clean manifest (SLOT-CLEANHASH)",
          EXPANDED_CLEAN_SHA256,
          sha256(repo.blob(args.sets_rev,
                           "bench/expanded-clean/manifest.json")))

    # 2. Sealed-set manifest + per-case hashes.
    sealed_blob = repo.blob(args.sets_rev, "bench/sealed/sealed-manifest.json")
    check("sealed-set manifest (registration §2.2)",
          SEALED_MANIFEST_SHA256, sha256(sealed_blob))
    sealed = json.loads(sealed_blob)
    bad = []
    for case in sealed["cases"]:
        path = f"bench/sealed/cases/{case['case_id']}.json"
        if sha256(repo.blob(args.sets_rev, path)) != case["sha256"]:
            bad.append(case["case_id"])
    rows.append((f"sealed-set per-case hashes "
                 f"({len(sealed['cases'])} cases)",
                 "all match manifest",
                 "all match" if not bad else f"mismatch: {', '.join(bad)}",
                 "PASS" if not bad else "FAIL"))

    # 3. A5 set hash as originally registered — superseded, not a failure.
    rows.append(("A5 set hash (registration §1.3, original construction)",
                 A5_SET_HASH_REGISTERED, "construction not reproducible",
                 "SUPERSEDED"))

    # 4. A5 per-file manifest (Addendum A item 8).
    try:
        with open(args.a5_manifest, "rb") as fh:
            a5 = json.load(fh)
        src = a5["source_commit"]
        bad = []
        for entry in a5["files"]:
            if sha256(repo.blob(src, entry["path"])) != entry["sha256"]:
                bad.append(entry["path"])
        rows.append((f"A5 per-file manifest "
                     f"({len(a5['files'])} files @ {src[:7]})",
                     "all match manifest",
                     "all match" if not bad
                     else f"mismatch: {', '.join(bad)}",
                     "PASS" if not bad else "FAIL"))
        if a5["supersedes"]["registered_set_hash"] != A5_SET_HASH_REGISTERED:
            rows.append(("A5 manifest supersedes-pointer",
                         A5_SET_HASH_REGISTERED,
                         a5["supersedes"]["registered_set_hash"], "FAIL"))
    except (OSError, KeyError, ValueError) as exc:
        rows.append(("A5 per-file manifest", "readable manifest",
                     f"error: {exc}", "FAIL"))

    # 5. SLOT-POLICY freeze identity at the recorded implementing commit.
    check("SLOT-POLICY core.py @ 736a55d",
          CORE_PY_SHA256,
          sha256(repo.blob(POLICY_FREEZE_COMMIT, "src/codereview/core.py")))
    check("SLOT-POLICY panel config @ 736a55d",
          PANEL_CONFIG_SHA256,
          sha256(repo.blob(
              POLICY_FREEZE_COMMIT,
              "bench/configs/panel-baseline-2026-11-04.json")))

    # 6. Pre-registration integrity: footer value + body hash.
    try:
        with open(args.registration, "rb") as fh:
            data = fh.read()
        marker = b"\nFOOTER-HASH:"
        idx = data.find(marker)
        if idx < 0:
            raise ValueError("FOOTER-HASH line not found")
        body_hash = sha256(data[:idx])
        line_end = data.find(b"\n", idx + 1)
        footer_line = data[idx + 1:line_end].decode("utf-8", "replace")
        footer_value = footer_line.split("`")[1] \
            if "`" in footer_line else footer_line
        check("pre-registration FOOTER-HASH line",
              REGISTRATION_FOOTER_HASH, footer_value.strip())
        # The post-fill body state (Baseline v2 section 6) is
        # superseded by the section-3 Addendum A append of
        # 2026-11-05 — reported SUPERSEDED only when the body
        # actually recomputes to the current post-append state,
        # which the next check verifies by strict equality; any
        # other body state fails both rows (same pattern as the
        # A5 set hash in check 3).
        rows.append(("pre-registration body hash (post-fill state, "
                     "Baseline v2 §6)",
                     REGISTRATION_BODY_SHA256_SUPERSEDED,
                     "superseded by the §3 Addendum A append "
                     "(2026-11-05)",
                     "SUPERSEDED"
                     if body_hash == REGISTRATION_BODY_SHA256_CURRENT
                     else "FAIL"))
        rows.append(("pre-registration body hash (post-Addendum A "
                     "append, §3)",
                     REGISTRATION_BODY_SHA256_POST_ADDENDUM_A,
                     "superseded by the §3 A1-A3 append "
                     "(2026-11-05)",
                     "SUPERSEDED"
                     if body_hash == REGISTRATION_BODY_SHA256_CURRENT
                     else "FAIL"))
        check("pre-registration body hash (post-A1-A3 append, "
              "§3)", REGISTRATION_BODY_SHA256_CURRENT, body_hash)
    except (OSError, ValueError, IndexError) as exc:
        rows.append(("pre-registration integrity", "readable document",
                     f"error: {exc}", "FAIL"))

    # 7. B2 confirmation registration (§10 of
    # pre-registration-b2-2026-11-05).
    check("generation-v3 sealed manifest (B2 §10a)",
          GENERATION_V3_SEALED_MANIFEST_SHA256,
          sha256(repo.blob(args.sets_rev,
                           "bench/generation-v3/"
                           "SEALED-MANIFEST.json")))
    try:
        man = json.loads(repo.blob(
            args.sets_rev,
            "bench/generation-v3/SEALED-MANIFEST.json"))
        entries = list(man.get("files") or []) + list(
            (man.get("validation") or {}).get("files") or [])
        bad7 = []
        for entry in entries:
            if sha256(repo.blob(GENERATION_V3_SOURCE_COMMIT,
                                entry["path"])) != entry["sha256"]:
                bad7.append(entry["path"])
        rows.append((f"generation-v3 per-file manifest "
                     f"({len(entries)} files @ 0e3bf46) (B2 §10b)",
                     "all match manifest",
                     "all match" if not bad7
                     else f"mismatch: {', '.join(bad7[:3])}",
                     "PASS" if not bad7 else "FAIL"))
    except (KeyError, ValueError, subprocess.CalledProcessError) \
            as exc:
        rows.append(("generation-v3 per-file manifest (B2 §10b)",
                     "readable manifest", f"error: {exc}", "FAIL"))
    check("B2 freeze core.py @ a88df64 (§10c)",
          B2_CORE_PY_SHA256,
          sha256(repo.blob(B2_FREEZE_COMMIT,
                           "src/codereview/core.py")))
    check("B2 freeze panel config @ a88df64 (§10c)",
          B2_PANEL_CONFIG_SHA256,
          sha256(repo.blob(
              B2_FREEZE_COMMIT,
              "bench/configs/panel-baseline-2026-11-04.json")))
    try:
        with open(args.registration_b2, "rb") as fh:
            data7 = fh.read()
        marker7 = b"\nFOOTER-HASH:"
        idx7 = data7.find(marker7)
        if idx7 < 0:
            raise ValueError("FOOTER-HASH line not found")
        body7 = sha256(data7[:idx7])
        line_end7 = data7.find(b"\n", idx7 + 1)
        footer_line7 = data7[idx7 + 1:line_end7].decode(
            "utf-8", "replace")
        footer_value7 = footer_line7.split("`")[1] \
            if "`" in footer_line7 else footer_line7
        check("B2 registration FOOTER-HASH line (§10d)",
              REGISTRATION_B2_FOOTER_HASH, footer_value7.strip())
        rows.append(("B2 registration body hash (drafting state, "
                     "§13)",
                     REGISTRATION_B2_FOOTER_HASH,
                     "superseded by the §13 signature fill "
                     "(2026-11-06)",
                     "SUPERSEDED"
                     if body7 == REGISTRATION_B2_BODY_SHA256_CURRENT
                     else "FAIL"))
        rows.append(("B2 registration body hash (post-signature "
                     "fill, §13)",
                     REGISTRATION_B2_BODY_SHA256_POST_SIGNATURE,
                     "superseded by the §13 runner-pin fill "
                     "(2026-11-06)",
                     "SUPERSEDED"
                     if body7 == REGISTRATION_B2_BODY_SHA256_CURRENT
                     else "FAIL"))
        check("B2 registration body hash (post-runner-pin fill, "
              "§13)", REGISTRATION_B2_BODY_SHA256_CURRENT, body7)
    except (OSError, ValueError, IndexError) as exc:
        rows.append(("B2 registration integrity (§10d)",
                     "readable document", f"error: {exc}", "FAIL"))

    print(f"verify-registration — repo {root} @ {head[:12]}")
    print(f"{'item':<52} {'expected':<22} {'recomputed':<22} status")
    print("-" * 118)
    for item, expected, recomputed, status in rows:
        print(f"{item:<52} {short(expected):<22} "
              f"{short(recomputed):<22} {status}")
    failures = [r for r in rows if r[3] == "FAIL"]
    print("-" * 118)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} item(s) did not verify)")
        return 1
    print("RESULT: PASS (all registered hashes verify; superseded: "
          "A5 set hash, pre-Addendum-A body hash, post-Addendum-A "
          "body hash)")
    print("B2 registration (item 7): PASS — generation-v3 seal, "
          "B2 freeze, and body-hash chain verify; drafting and "
          "post-signature body states SUPERSEDED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
