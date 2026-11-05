#!/usr/bin/env python3
"""_finding_public adjudication-prompt probe — open-
refutations solution §3, for 4ce0212286e0 (bucket B #4,
HOLD-OUT): "Evidence is sliced before adjudication without
any truncation boundary."

§3's probe question: do the adjudication prompts pass
through _finding_public (which slices evidence to 2000
chars and evidence_quote to 1000, silently, mid-word), or
do they carry the full text? The solution text expected
the prompts might never call it. THEY DO — all three
adjudication prompt types are driven here with capturing
fakes and the actual prompts are measured:

  re-ground (_reground_call), cross-family confirmation
  (_xconfirm_call), Tech Lead (_tech_lead_call).

For each: does the full 2500-char evidence appear? Where
does the visible text end — mid-word? Is a truncation
marker present (post-hardening: '…[truncated, N chars,
sha256:…]')? Storage is NOT probed here as cut: sidecars
hold full text (that half was verified in the inventory
sweep); this probe is about what the ADJUDICATOR SEES.

Reports facts; exit 0 either way. The hardening's suite
tests assert the post-fix properties."""

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))

from codereview import core  # noqa: E402

RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

# Words of 9 chars + space: a cut at exactly 2000 lands
# mid-word (2000 = 200*10, boundary at multiples of 10 —
# offset by a 5-char prefix so 2000 falls inside a word).
EVIDENCE = "HEAD " + " ".join(["w%08d" % i for i in range(300)])
QUOTE = "HEAD " + " ".join(["q%08d" % i for i in range(200)])
FINDING = {"id": "probe000000001", "severity": "major",
           "category": "correctness", "file": "app.py",
           "line": 2, "title": "Probe finding",
           "evidence": EVIDENCE, "evidence_quote": QUOTE,
           "recommendation": "fix it"}
REGION = "app.py region text\n" * 5
DISPUTE = {"raiser_family": "famA", "family": "famB",
           "reason": "the refuter reason", "adequacy": "strong",
           "evidence_quote": "a quote from the diff"}


def capture(response):
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return json.dumps(response)
    return fake, prompts


def measure(name, prompt):
    full_sha = hashlib.sha256(EVIDENCE.encode()).hexdigest()
    in_prompt = EVIDENCE in prompt
    marker = "…[truncated" in prompt
    # The visible evidence fragment: from the first word to
    # the last complete marker/word we can find.
    idx = prompt.find("HEAD ")
    frag = prompt[idx:idx + 2100] if idx >= 0 else ""
    ends_mid_word = False
    if not in_prompt and idx >= 0:
        # find the longest prefix of EVIDENCE present; the cut
        # is mid-word only when BOTH neighbours of the cut
        # point are non-space (a trailing space in the visible
        # prefix means the cut fell on a boundary).
        n = 0
        while n < len(EVIDENCE) and prompt.find(
                EVIDENCE[:n + 1]) >= 0:
            n += 1
        ends_mid_word = (0 < n < len(EVIDENCE)
                         and EVIDENCE[n - 1] not in " \n\t"
                         and EVIDENCE[n] not in " \n\t")
        frag_len = n
    else:
        frag_len = len(EVIDENCE) if in_prompt else 0
    return {"prompt_type": name, "full_evidence_in_prompt":
            in_prompt, "visible_evidence_chars": frag_len,
            "ends_mid_word": ends_mid_word,
            "truncation_marker_present": marker,
            "full_sha256": full_sha}


def main():
    lines = ["_FINDING_PUBLIC PROMPT PROBE — 4ce0212286e0",
             f"Evidence: {len(EVIDENCE)} chars; quote: "
             f"{len(QUOTE)} chars (caps: 2000 / 1000).", ""]
    results = []
    fake, prompts = capture({"status": "withdrawn",
                             "reason": "probe"})
    core._reground_call(fake, FINDING, REGION)
    results.append(measure("re-ground", prompts[0]))
    fake, prompts = capture({"verdict": "confirm"})
    core._xconfirm_call(fake, FINDING, REGION)
    results.append(measure("cross-family confirmation",
                           prompts[0]))
    fake, prompts = capture({"decision": "invalid",
                             "evidence_quote": "",
                             "rationale": "probe"})
    core._tech_lead_call(fake, FINDING, REGION, DISPUTE)
    results.append(measure("Tech Lead adjudication",
                           prompts[0]))
    for r in results:
        lines.append(json.dumps(r, indent=1))
    silent = any(not r["full_evidence_in_prompt"]
                 and not r["truncation_marker_present"]
                 for r in results)
    midword = any(r["ends_mid_word"] for r in results)
    lines += ["",
              f"All three adjudication prompt types route the "
              f"finding through _finding_public: "
              f"{all(not r['full_evidence_in_prompt'] for r in results)}",
              f"Silent slice (no marker) somewhere: {silent}",
              f"Mid-word cut somewhere: {midword}",
              "",
              "Note (context, outside this item's fix scope):",
              "the Tech Lead prompt also caps the dispute",
              "positions inline (raiser_quote 400, refuter_reason",
              "300, refuter_quote 400 chars) from the live dispute",
              "object; storage keeps full text in sidecars.",
              "",
              "OUTCOME: " + (
                  "the slice at HEAD is silent and mid-word — "
                  "the claim's mechanism is confirmed for what "
                  "the adjudicator sees (storage is full-text; "
                  "the dispute is about the prompt). The "
                  "hardening adds the explicit marker."
                  if silent else
                  "prompts now carry the explicit truncation "
                  "marker — the hardening is in place; see the "
                  "suite tests for the boundary guarantees.")]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(
            RESULTS, "finding-public-4ce0212286e0.txt"),
            "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
