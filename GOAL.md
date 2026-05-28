# Hermes Agent /goal_prompt_oneshot Checkpoint Goal

## Standing Goal

Finish the local Hermes Agent `/goal_prompt` and `/goal_prompt_oneshot` workflow recovery work so the CLI, TUI, and gateway can load `docs/runbooks/GOAL_PROMPT.md`, persist one-shot goal state, preserve Telegram delivery ordering, and resume cleanly after compaction or an operator-managed stop/restart.

## Current Definition of Done

The Definition of Done is **not satisfied** until all of the following are true:

- `/goal_prompt` and `/goal_prompt_oneshot` are registered and dispatch correctly in CLI, TUI, and gateway surfaces.
- Telegram/gateway one-shot delivery uses normal paginated final replies, queues post-delivery continuations after the visible command boundary, and suppresses internal reload notices.
- Goal state survives session split/compaction refresh and re-reads `GOAL_PROMPT.md` from disk for one-shot continuation.
- Focused regression tests for command registry, CLI/TUI/gateway dispatch, goal-state persistence, Telegram final-delivery policy, and post-delivery callback behavior pass.
- Disk-truth shutdown/resume docs are current: `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, and `docs/runbooks/GOAL_PROMPT.md`.
- Intended local changes are committed. Push/publication requires a separate explicit operator instruction.

## Checkpoint Status

Current verified checkpoint: local implementation and regression fixes are present in committed local history, including the Telegram `/goal_prompt_oneshot` internal reload silence fix and targeted tests. Latest recorded focused verification before this shutdown handoff: `python -m pytest tests/gateway/test_goal_prompt_command.py tests/gateway/test_gateway_final_streaming_policy.py` (`15 passed`), workflow-doc verifier PASS, and `git diff --check` PASS.

The latest operator instruction requested a graceful stop after the current action, so autonomous continuation must stop at this boundary. This is an operational hold only; it does not mean the Definition of Done is satisfied and it does not authorize push/publication.

## Resume Boundary

When the operator is ready to continue, resume with:

```bash
/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent
```

The first resumed action is to read `docs/status/NEXT_ACTIONS.md`, verify the checkpoint state against git status, run the minimum post-stop checks listed there, then continue the next safe local verification/cleanup slice without pushing unless explicitly authorized.
