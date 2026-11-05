"""Live acceptance run driver (PT track 3, execution step):
shadow Tech Lead = DeepSeek via the swarm llm_chain connector
surrogate path — the standing third family. Runs the full
protocol (48 baselines + 4x48 mutations) and writes the run
record into this directory as committed evidence.

Note: the first launch (2026-11-05 ~01:00 ET) died when the
sandbox wiped /tmp mid-run after 16 baselines; this is the
single complete run the scorecard is measured from."""
import json
import os
import sys
import time

sys.path.insert(0, "/home/hatch/workspace/codereview-shadow/src")
sys.path.insert(0, "/home/hatch/workspace/mitbbs-ai-swarm/agents")

import llm_chain  # noqa: E402
from codereview import acceptance  # noqa: E402

OUT = "/home/hatch/workspace/codereview-shadow/acceptance-run-2026-11-04"
LOG = os.path.join(OUT, "progress.log")


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


assert llm_chain.deepseek_configured(), "deepseek not configured"


def seat(prompt):
    json_mode = not prompt.startswith("Paraphrase the following")
    text, _usage = llm_chain.call_deepseek(
        prompt, json_mode=json_mode, timeout=240)
    return text


result = acceptance.run_acceptance(
    "/home/hatch/workspace/codereview-acceptance", seat,
    seat_family="deepseek", seat_name="deepseek-acceptance",
    do_mutations=True, timeout=240, log=log)

with open(os.path.join(OUT, "acceptance-run.json"), "w",
          encoding="utf-8") as fh:
    json.dump(result, fh, indent=1, default=str)
for mid, m in result["metrics"].items():
    log(f"{mid}: measured={m['measured']} "
        f"threshold={m['threshold']} pass={m['pass']}")
log(f"UNLOCK: {result['unlock_all_gates_pass']}")
