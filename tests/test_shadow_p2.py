"""P2 machinery (four-disputed solution §2B + §3): raise-time
function keys, qualified-name precedent lookup with miss-cause
telemetry, and the shared Tech Lead eligibility predicate with
its fail-closed boundary assertion.

The precedent property tests follow the solution's acceptance
list: insert lines outside the function -> hit; edit inside ->
miss_hash_changed; rename -> miss_name_absent; never a hit on
a different function under any insertion pattern."""

import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import core  # noqa: E402

BASE = (
    "import os\n"
    "\n"
    "def helper(x):\n"
    "    return x + 1\n"
    "\n"
    "def target(items):\n"
    "    total = 0\n"
    "    for it in items:\n"
    "        total += helper(it)\n"
    "    return total\n"
    "\n"
    "def other():\n"
    "    return 42\n")


def _finding(source, line=9, fid="find1", stored=True):
    f = {"id": fid, "file": "app.py", "line": line,
         "title": "claim", "severity": "major"}
    if stored:
        key = core.function_key(source, line)
        assert key is not None and key["function"] == "target"
        f["function_key"] = key
    return f


def _entry(source, line=9, fid="find1"):
    f = _finding(source, line, fid, stored=False)
    entries = core.upsert_precedent(
        [], f, "blob-v1", "round-1", "disp.md", source=source)
    assert entries and entries[0].get("function") == "target"
    return entries


def _apply(finding, entries, source, blob="blob-v2"):
    telemetry = []
    remaining, standing = core.apply_precedents(
        [finding], entries, lambda _p: blob,
        lambda _p: source, telemetry=telemetry)
    return remaining, standing, telemetry


class FunctionKeyByNameTests(unittest.TestCase):
    def test_ok_absent_ambiguous_unparseable(self):
        key, status = core.function_key_by_name(BASE, "target")
        self.assertEqual(status, "ok")
        self.assertEqual(key["function"], "target")
        _k, status = core.function_key_by_name(BASE, "nope")
        self.assertEqual(status, "absent")
        dup = "def f():\n    return 1\n\ndef f():\n    return 2\n"
        _k, status = core.function_key_by_name(dup, "f")
        self.assertEqual(status, "ambiguous")
        _k, status = core.function_key_by_name("def (:", "f")
        self.assertEqual(status, "unparseable")

    def test_nested_and_method_qualified_names(self):
        src = ("class C:\n"
               "    def m(self):\n"
               "        def inner():\n"
               "            return 1\n"
               "        return inner()\n")
        key, status = core.function_key_by_name(src, "C.m.inner")
        self.assertEqual(status, "ok")
        self.assertEqual(key["function"], "C.m.inner")

    def test_attach_function_keys(self):
        findings = [{"file": "app.py", "line": 9},
                    {"file": "app.py", "line": 1},
                    {"file": "gone.py", "line": 3}]
        n = core.attach_function_keys(
            findings, lambda p: BASE if p == "app.py" else None)
        self.assertEqual(n, 1)
        self.assertEqual(
            findings[0]["function_key"]["function"], "target")
        self.assertNotIn("function_key", findings[1])


class PrecedentPropertyTests(unittest.TestCase):
    def test_insert_outside_function_is_a_hit(self):
        entries = _entry(BASE)
        for pad in (1, 3, 17):
            drifted = ("# padding comment\n" * pad) + BASE
            f = _finding(BASE)  # stored key from the ORIGINAL
            remaining, standing, tel = _apply(f, entries, drifted)
            self.assertEqual(len(standing), 1, f"pad={pad}")
            self.assertEqual(remaining, [])
            self.assertEqual(tel[0]["outcome"], "hit")
            self.assertEqual(
                standing[0]["precedent"]["function"], "target")

    def test_insert_below_function_is_a_hit(self):
        entries = _entry(BASE)
        drifted = BASE + "\n# trailing comment\n" * 5
        _r, standing, tel = _apply(_finding(BASE), entries,
                                   drifted)
        self.assertEqual(len(standing), 1)
        self.assertEqual(tel[0]["outcome"], "hit")

    def test_edit_inside_function_is_miss_hash_changed(self):
        entries = _entry(BASE)
        edited = BASE.replace("total += helper(it)",
                              "total += helper(it) * 2")
        remaining, standing, tel = _apply(
            _finding(BASE), entries, edited)
        self.assertEqual(standing, [])
        self.assertEqual(len(remaining), 1)
        self.assertEqual(tel[0]["outcome"], "miss_hash_changed")

    def test_edit_inside_callee_is_miss_hash_changed(self):
        entries = _entry(BASE)
        edited = BASE.replace("return x + 1", "return x + 2")
        _r, standing, tel = _apply(_finding(BASE), entries,
                                   edited)
        self.assertEqual(standing, [])
        self.assertEqual(tel[0]["outcome"], "miss_hash_changed")

    def test_rename_is_miss_name_absent(self):
        entries = _entry(BASE)
        renamed = BASE.replace("def target(items):",
                               "def retarget(items):")
        _r, standing, tel = _apply(_finding(BASE), entries,
                                   renamed)
        self.assertEqual(standing, [])
        self.assertEqual(tel[0]["outcome"], "miss_name_absent")

    def test_duplicate_qualified_name_is_miss_ambiguous(self):
        entries = _entry(BASE)
        dup = BASE + "\n\ndef target(items):\n    return 0\n"
        _r, standing, tel = _apply(_finding(BASE), entries, dup)
        self.assertEqual(standing, [])
        self.assertEqual(tel[0]["outcome"], "miss_ambiguous")

    def test_never_a_hit_on_a_different_function(self):
        entries = _entry(BASE)
        rng = random.Random(20261104)
        for trial in range(60):
            lines = BASE.splitlines()
            # random insertions of comments / other functions
            # OUTSIDE target's span (lines 6..11, 1-based)
            inserts = []
            for _ in range(rng.randint(0, 6)):
                pos = rng.choice(
                    [i for i in range(0, 5)]
                    + [i for i in range(11, len(lines))])
                inserts.append((pos, rng.choice([
                    "# filler", "", "def extra_%d():" % trial,
                    "    return 0"])))
            for pos, text in sorted(inserts, reverse=True):
                lines.insert(pos, text)
            src = "\n".join(lines) + "\n"
            _r, standing, _t = _apply(_finding(BASE), entries,
                                      src)
            for s in standing:
                self.assertEqual(
                    s["precedent"]["function"], "target")
                self.assertEqual(
                    s["precedent"]["function_hash"],
                    entries[0]["function_hash"])

    def test_legacy_line_drift_is_classified(self):
        entries = _entry(BASE)
        drifted = ("# pad\n" * 4) + BASE
        # Legacy finding: NO stored key; its line (9) was the
        # target's body in the original — after +4 lines it
        # resolves elsewhere (or nowhere).
        f = _finding(BASE, stored=False)
        _r, standing, tel = _apply(f, entries, drifted)
        self.assertEqual(standing, [])
        self.assertEqual(tel[0]["outcome"], "miss_line_drift")

    def test_legacy_unchanged_still_hits_by_line(self):
        entries = _entry(BASE)
        f = _finding(BASE, stored=False)
        _r, standing, tel = _apply(f, entries, BASE,
                                   blob="blob-v1")
        self.assertEqual(len(standing), 1)
        self.assertEqual(tel[0]["outcome"], "hit")

    def test_blob_fallback_when_function_unresolvable(self):
        entries = _entry(BASE)
        f = _finding(BASE, stored=False)
        _r, standing, tel = _apply(
            f, entries, "this is not python at all ((", 
            blob="blob-v1")
        self.assertEqual(len(standing), 1)
        self.assertEqual(standing[0]["precedent"]["scope"],
                         "file")
        self.assertEqual(tel[0]["outcome"], "fallback_blob")


# ---------------- boundary assertion ----------------

PATCH = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,4 @@\n"
    " import os\n"
    "+VALUE = compute_total(items)\n"
    "+print(VALUE)\n"
    "+RESULT = VALUE * 2\n")
CITED = "VALUE = compute_total(items)"
META3 = {"seatA": {"family": "famA", "tier": "paid"},
         "seatB": {"family": "famB", "tier": "paid"},
         "seatC": {"family": "famC", "tier": "paid"}}


class _Seat:
    def __init__(self, review=None, xconfirm=None,
                 tech_lead=None):
        self.review = review or {"verdict": "pass",
                                 "findings": []}
        self.xconfirm = xconfirm or {"verdict": "confirm"}
        self.tech_lead = tech_lead or {
            "decision": "sustain_refutation",
            "evidence_quote": "print(VALUE)",
            "rationale": "the refutation is correct"}

    def __call__(self, prompt):
        if "TECH LEAD ADJUDICATION pass" in prompt:
            payload = self.tech_lead
        elif "CROSS-FAMILY CONFIRMATION pass" in prompt:
            payload = self.xconfirm
        elif "RE-GROUND pass" in prompt:
            payload = {"status": "withdrawn", "reason": "x"}
        else:
            payload = self.review
        return payload if isinstance(payload, str) \
            else json.dumps(payload)


def _panel():
    finding = {"severity": "major", "category": "correctness",
               "file": "app.py", "line": 2,
               "title": "Total computed without a guard",
               "evidence": CITED, "evidence_quote": CITED,
               "recommendation": "guard it", "confidence": 0.9}
    raiser = _Seat(review={"verdict": "changes_requested",
                           "findings": [finding]})
    refuter = _Seat(xconfirm={
        "verdict": "refute", "evidence_quote": "print(VALUE)",
        "reason": "the claim is wrong"})
    lead = _Seat()
    return {"seatA": raiser, "seatB": refuter, "seatC": lead}


class BoundaryAssertionTests(unittest.TestCase):
    def _run(self, **kw):
        kw.setdefault("seat_meta", META3)
        kw.setdefault("sleep", lambda *_a: None)
        return core.run_review(PATCH, _panel(), **kw)

    def test_selection_property_random_pools(self):
        rng = random.Random(4102)
        fams = ["famA", "famB", "famC", "unknown", None]
        for _ in range(300):
            names = [f"s{i}" for i in range(rng.randint(1, 5))]
            fam_by = {n: rng.choice(fams) for n in names}
            ok = {n for n in names if rng.random() < 0.8}
            raiser, refuter = rng.choice(fams), rng.choice(fams)
            name, _fn, fam, _sub, _un = core._select_tech_lead(
                {n: (lambda p: "") for n in names}, ok, fam_by,
                None, raiser, refuter)
            if name is not None:
                self.assertTrue(
                    core._tech_lead_eligible(
                        fam, name in ok, raiser, refuter),
                    f"ineligible selection: {name} {fam}")

    def test_normal_path_adjudicates(self):
        rec = self._run()
        self.assertEqual(
            len(rec.get("adjudicated_refuted_findings") or []),
            1)
        self.assertNotIn("tech_lead_assertion_failures", rec)

    def test_mutant_selection_is_caught_at_the_boundary(self):
        # The Case-3 mutant: the independence check is removed
        # from selection, which now hands back the REFUTER's
        # own seat. The boundary assertion must fail closed.
        original = core._select_tech_lead

        def broken(seat_fns, ok_seats, fam_by_seat, designated,
                   raiser_fam, refuter_fam):
            return ("seatB", seat_fns["seatB"], "famB", None,
                    None)

        core._select_tech_lead = broken
        try:
            rec = self._run()
        finally:
            core._select_tech_lead = original
        self.assertEqual(
            rec.get("adjudicated_refuted_findings") or [], [])
        failures = rec.get("tech_lead_assertion_failures") or []
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["seat"], "seatB")
        disputed = rec.get("disputed_findings") or []
        self.assertEqual(len(disputed), 1)
        self.assertEqual(
            disputed[0]["tech_lead"]["status"], "unavailable")
        self.assertIn("assertion_failure",
                      disputed[0]["tech_lead"])


class DeepNestingKeyTests(unittest.TestCase):
    def test_deeply_nested_source_is_unkeyable_not_fatal(self):
        # cc0e75a507fd: pathologically nested source must fail
        # safe (no key, legacy path) — never raise out of the
        # keying path and crash a run.
        # A flat operator chain parses to a left-deep AST —
        # the shape the closing-A probe blew the recursion
        # limit with (parenthesised nesting does not).
        src = "def f():\n    return 1" + "+1" * 5000 + "\n"
        self.assertIsNone(core.function_key(src, 2))
        key, status = core.function_key_by_name(src, "f")
        self.assertIsNone(key)
        self.assertEqual(status, "unparseable")
        findings = [{"id": "z1", "file": "a.py", "line": 2}]
        self.assertEqual(
            core.attach_function_keys(findings, lambda p: src), 0)
        self.assertNotIn("function_key", findings[0])


if __name__ == "__main__":
    unittest.main()
