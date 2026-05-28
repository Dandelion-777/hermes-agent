# NEXT_ACTIONS

## Current Status

- Project root: `/home/shvdxw/.hermes/hermes-agent`.
- Current branch: `main`.
- Repository publication state at shutdown handoff: local `main` is ahead of `origin/main` by 7 commits after the docs-only stop refresh commit; push/publication remains unauthorized.
- Current checkpoint reason: operator requested a graceful stop/shutdown after the current action. Do not start another implementation-bearing slice in this session.
- Last completed committed slice: local Hermes `/goal_prompt` / `/goal_prompt_oneshot` workflow recovery and Telegram gateway ordering/noise fixes, including the internal reload silence and post-delivery continuation fixes in recent local commits.
- Dirty/in-progress slice at stop request: none known before this docs-only handoff refresh. This handoff refresh updates only disk continuation docs.
- Latest focused verification recorded before this checkpoint:
  - `python -m pytest tests/gateway/test_goal_prompt_command.py tests/gateway/test_gateway_final_streaming_policy.py` → `15 passed` (post-handoff rerun).
  - `python3 ~/.hermes/skills/software-development/goal-driven-project-execution/scripts/verify_goal_prompt_workflow_docs.py /home/shvdxw/.hermes/hermes-agent` → PASS, checked 6 files.
  - `git diff --check` → PASS.
- Shutdown handoff docs refreshed: `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, and `docs/runbooks/GOAL_PROMPT.md`.
- Stable safety boundary reviewed for this checkpoint and captured in `docs/security/SAFETY.md`.
- Stable prompt contract reviewed and captured in `docs/runbooks/GOAL_PROMPT.md`.

## First Incomplete Goal

Stop the active `/goal_prompt_oneshot` loop for the operator-requested graceful shutdown without starting another implementation-bearing slice. The Hermes project Definition of Done in `GOAL.md` remains **not satisfied**.

## Exact Next Safe Action

After the operator is ready to resume, run:

```text
/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent
```

The first resumed autonomous slice is:

1. Re-read `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, `docs/runbooks/GOAL_PROMPT.md`, and `AGENTS.md`.
2. Inspect `git status --short --branch` and confirm whether the docs-only shutdown handoff commit is present or the docs refresh remains dirty.
3. Run the minimum post-stop checks listed below.
4. Continue with the narrowest safe local verification/cleanup slice for the `/goal_prompt_oneshot` workflow, preserving the no-push boundary unless the operator explicitly authorizes publication.

## Verification To Run Next

Minimum post-stop checks before further code changes:

```bash
git status --short --branch
git diff --check
python -m pytest tests/gateway/test_goal_prompt_command.py tests/gateway/test_gateway_final_streaming_policy.py
```

Run broader focused tests only if the resumed diff indicates affected areas beyond gateway goal-prompt behavior.

## Blockers / Holds

- Operational hold: graceful stop/shutdown requested by operator. Stop after this handoff and do not start the next autonomous slice in this session.
- Push/publication hold: no push is authorized by the stop request. Commit locally only if policy allows; push only after a separate explicit instruction.
- No live/funded/production/destructive action is authorized.

## Operator Input Needed

When ready, restart or resume Hermes if needed, then run:

```text
/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent
```

## Notes For Resume

- This stop is operational, not a product safety gate. Safe local docs/tests/code cleanup can continue after the operator resumes from the prompt above.
- Do not emit `CONTINUE` from this shutdown handoff; the required controller signal is `STOP_FOR_OPERATOR` for the operator stop request.
- The exact next safe slice is verification/cleanup, not live/funded/production/destructive work and not push/publication.
