#!/usr/bin/env python3
"""Tiny OpenAI health probe for the registered run's resume
watch: one preflight call set via run_panel_baseline.preflight;
prints openai's ok flag. Used to time resume passes to the
quota window without burning a full generation pass."""
import json
import os
import sys

WORKTREE = "/home/hatch/workspace/codereview"
sys.path.insert(0, os.path.join(WORKTREE, "bench", "scripts"))
sys.path.insert(0, os.path.join(WORKTREE, "src"))
sys.path.insert(0, "/home/hatch/workspace/mitbbs-ai-swarm/agents")
os.environ.setdefault("CODEREVIEW_DEEPSEEK_CONNECTOR",
                      "custom.deepseek-bench")

import run_panel_baseline as panel_driver  # noqa: E402

health = panel_driver.preflight()
print(json.dumps({k: {"ok": v.get("ok"),
                      "error": str(v.get("error") or "")[:100]}
                  for k, v in health.items()}, indent=1))
