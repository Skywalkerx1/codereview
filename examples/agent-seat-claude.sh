#!/bin/sh
# Example agent seat: Claude Code as a CodeReview reviewer.
#
# Seat it with:
#   codereview --repo . \
#     --provider gemini \
#     --provider "agent:claude:sh examples/agent-seat-claude.sh"
#
# The seat contract: CodeReview writes the review prompt (diff +
# instructions) to the file named by $CODEREVIEW_PROMPT and also
# pipes it to stdin. The agent must print ONLY the verdict JSON
# object the prompt asks for — CodeReview parses stdout.
#
# The wrapper feeds the prompt file as Claude Code's input document
# and instructs it to answer with the JSON verdict alone. Adjust the
# instruction line to taste; keep the "only JSON" requirement.
#
# --tools "" disables ALL built-in tools for the run: the brief is
# self-contained, so a reviewer seat needs no file, shell, or web
# access at all — and the untrusted diff gets no tool surface to
# act through. (Flag verified against the Claude Code CLI docs;
# check `claude --help` on your version.)
exec claude -p --tools "" "You are a reviewer seat in a multi-model code review. The document on stdin is your complete brief: a diff plus instructions. Follow the instructions exactly and output ONLY the JSON verdict object they ask for — no prose, no markdown fences." < "$CODEREVIEW_PROMPT"
