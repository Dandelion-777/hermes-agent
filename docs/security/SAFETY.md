# SAFETY

## Scope

This file records the safety boundary for the local Hermes Agent `/goal_prompt` and `/goal_prompt_oneshot` workflow recovery work in `/home/shvdxw/.hermes/hermes-agent`.

## Allowed Without Additional Approval

- Local source edits inside the Hermes Agent checkout.
- Local documentation updates for `GOAL.md`, `docs/status/NEXT_ACTIONS.md`, `docs/security/SAFETY.md`, and `docs/runbooks/GOAL_PROMPT.md`.
- Focused local tests for changed CLI/TUI/gateway/goal-prompt behavior.
- Local `git status`, `git diff`, `git diff --check`, and scoped local commits when project policy allows.
- Restart-checkpoint documentation required to resume after an operator-managed Hermes restart.

## Requires Explicit Operator Approval

- Pushing to any remote branch or publishing a PR.
- Destructive git history changes such as `reset --hard`, force-push, branch deletion, or broad cleanup of unrelated dirty files.
- Editing secrets, credential stores, `.env`, auth tokens, OAuth state, or private keys.
- Changing production/system service configuration beyond the operator-requested Hermes restart boundary.
- External side effects, production deploys, live/funded actions, or any action outside the local Hermes Agent development checkout.

## Restart Checkpoint Boundary

The latest operator instruction requests a graceful stop at the next safe slice boundary for a Hermes restart. The correct behavior is:

1. Finish or safely checkpoint the current coherent slice.
2. Refresh disk truth for restart.
3. Run the narrowest relevant verification or document why it is not run.
4. Commit locally if policy allows.
5. Stop with `STOP_FOR_OPERATOR` and do not begin the next autonomous slice before restart.

This is an operational hold only. It does not authorize push/publication and does not mean the product Definition of Done is satisfied.

## Secret Handling

Do not print, store, or commit credential values. If credential-like strings appear in logs or tests, treat them as placeholders only and redact real values as `[REDACTED]` in summaries.
