# Hermes Agent /goal_prompt_oneshot Checkpoint Goal

## Standing Goal

Finish the local Hermes Agent `/goal_prompt` and `/goal_prompt_oneshot` workflow recovery work so the CLI, TUI, and gateway can load `docs/runbooks/GOAL_PROMPT.md`, persist one-shot goal state, preserve Telegram delivery ordering, and resume cleanly after compaction or a Hermes restart.

## Current Definition of Done

The Definition of Done is **not satisfied** until all of the following are true:

- `/goal_prompt` and `/goal_prompt_oneshot` are registered and dispatch correctly in CLI, TUI, and gateway surfaces.
- Telegram/gateway one-shot delivery uses normal paginated final replies, queues post-delivery continuations after the visible command boundary, and suppresses internal reload notices.
- Goal state survives session split/compaction refresh and re-reads `GOAL_PROMPT.md` from disk for one-shot continuation.
- Focused regression tests for command registry, CLI/TUI/gateway dispatch, goal-state persistence, Telegram final-delivery policy, and post-delivery callback behavior pass.
- Disk-truth restart docs are current: `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, and `docs/runbooks/GOAL_PROMPT.md`.
- Intended local changes are committed. Push/publication requires a separate explicit operator instruction.

## Checkpoint Status

Current verified checkpoint: local implementation and regression fixes are present in the worktree, including the Telegram `/goal_prompt_oneshot` internal reload silence fix and targeted tests. The operator requested a graceful Hermes restart after checkpointing the current slice, so autonomous continuation must stop at this boundary and resume from `docs/runbooks/GOAL_PROMPT.md` after restart.

## Resume Boundary

After Hermes restarts, resume with:

```bash
/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent
```

The first post-restart action is to read `docs/status/NEXT_ACTIONS.md`, verify the checkpoint state against git status, then continue the next safe local verification/cleanup slice without pushing unless explicitly authorized.
