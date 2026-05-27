# NEXT_ACTIONS

## Current Status

- Project root: `/home/shvdxw/.hermes/hermes-agent`.
- Current branch: `main`.
- Current checkpoint reason: operator requested a graceful Hermes restart at the next safe slice boundary.
- Current slice checkpointed: local Hermes `/goal_prompt` / `/goal_prompt_oneshot` workflow recovery and Telegram gateway ordering/noise fixes.
- Latest focused verification before this checkpoint:
  - `python -m pytest tests/gateway/test_goal_prompt_command.py tests/gateway/test_gateway_final_streaming_policy.py` → `8 passed`.
  - `python -m pytest tests/gateway/test_goal_prompt_command.py::test_gateway_goal_prompt_oneshot_continue_requeues_prompt_loader tests/gateway/test_goal_prompt_command.py::test_gateway_goal_prompt_oneshot_internal_reload_is_silent_but_queues tests/gateway/test_gateway_final_streaming_policy.py::test_gateway_keeps_tool_streaming_but_does_not_stream_final_text` → `3 passed`.
- Restart checkpoint docs refreshed: `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, and `docs/runbooks/GOAL_PROMPT.md`.
- Stable safety boundary reviewed for this checkpoint and captured in `docs/security/SAFETY.md`.
- Stable prompt contract reviewed and captured in `docs/runbooks/GOAL_PROMPT.md`.

## First Incomplete Goal

Stop the active `/goal_prompt_oneshot` loop for an operator-managed Hermes restart without starting another implementation-bearing slice. The Hermes project Definition of Done in `GOAL.md` remains **not satisfied**.

## Exact Next Safe Action

After Hermes restarts, run:

```text
/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent
```

The first post-restart autonomous slice is:

1. Re-read `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, `docs/runbooks/GOAL_PROMPT.md`, and `AGENTS.md`.
2. Inspect `git status --short --branch` and confirm the restart checkpoint commit/worktree state.
3. Continue with the narrowest safe local verification/cleanup slice for the `/goal_prompt_oneshot` workflow, preserving the no-push boundary unless the operator explicitly authorizes publication.

## Verification To Run Next

Minimum post-restart checks before further code changes:

```bash
git status --short --branch
git diff --check
python -m pytest tests/gateway/test_goal_prompt_command.py tests/gateway/test_gateway_final_streaming_policy.py
```

Run broader focused tests only if the post-restart diff indicates affected areas beyond gateway goal-prompt behavior.

## Blockers / Holds

- Operational hold: Hermes restart requested by operator. Stop after checkpoint and do not start the next autonomous slice in this pre-restart session.
- Push/publication hold: no push is authorized by the restart request. Commit locally if policy allows; push only after a separate explicit instruction.
- No live/funded/production/destructive action is authorized.

## Operator Input Needed

Restart Hermes, then run:

```text
/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent
```

## Notes For Resume

- This restart stop is operational, not a product safety gate. Safe local docs/tests/code cleanup can continue after restart from the prompt above.
- Do not emit `CONTINUE` from this checkpoint; the required controller signal is `STOP_FOR_OPERATOR` for restart.
