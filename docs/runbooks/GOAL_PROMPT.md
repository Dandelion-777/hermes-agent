# GOAL_PROMPT

This file is the restart-safe executable prompt for continuing the Hermes Agent `/goal_prompt` and `/goal_prompt_oneshot` workflow recovery work.

```text
/goal Work autonomously to continue the Hermes Agent /goal_prompt and /goal_prompt_oneshot workflow recovery from /home/shvdxw/.hermes/hermes-agent.

Read these files first:
- /home/shvdxw/.hermes/hermes-agent/AGENTS.md
- /home/shvdxw/.hermes/hermes-agent/GOAL.md
- /home/shvdxw/.hermes/hermes-agent/docs/status/NEXT_ACTIONS.md
- /home/shvdxw/.hermes/hermes-agent/docs/security/SAFETY.md
- /home/shvdxw/.hermes/hermes-agent/docs/runbooks/GOAL_PROMPT.md

Source priority:
1. Latest explicit operator instruction in the active session.
2. docs/status/NEXT_ACTIONS.md for volatile frontier and restart state.
3. docs/security/SAFETY.md and AGENTS.md for safety and repo policy.
4. GOAL.md for standing Definition of Done.
5. Other repository docs and code.

Current restart boundary:
- If this prompt is being loaded after the operator-requested Hermes restart, first verify the checkpoint state against git status and NEXT_ACTIONS.md.
- Do not push unless the operator explicitly authorizes publication.
- Continue only local safe source/docs/tests work. No secrets, production deploys, destructive git history operations, or external side effects.

Loop discipline:
- Select the first incomplete safe slice from docs/status/NEXT_ACTIONS.md.
- Prefer the narrowest coherent verification-bearing slice.
- Run focused verification for changed behavior.
- Use the slice-quality judge/controller expectations encoded in `GOAL.md` and `docs/status/NEXT_ACTIONS.md` before deciding whether to continue, stop, or complete.
- Refresh docs/status/NEXT_ACTIONS.md after each meaningful slice.
- Refresh GOAL.md, docs/security/SAFETY.md, and this file only when their durable contract changes.
- Commit intended verified files locally when policy allows; do not push without explicit approval.

Required non-final verdict block:
/goal_prompt_oneshot continuation decision: CONTINUE
GOAL.md definition of done: NOT SATISFIED
Completed slice: <one-line summary>
Verification evidence: <commands/tests/docs/git status evidence>
Files changed: <short list or none>
Docs refreshed: <yes/no + paths>
Known risks: <none or exact risk>
Next safe autonomous slice: <exact next action from docs/status/NEXT_ACTIONS.md>
Operator input needed before next slice: None
Hard stop: No

Required restart/operator-stop block:
/goal_prompt_oneshot continuation decision: STOP_FOR_OPERATOR
GOAL.md definition of done: NOT SATISFIED
Reason: <exact operator or non-bypassable gate>
No safe autonomous slice remains because: <why>
Operator decision needed: <specific bounded input>

Required completion block:
/goal_prompt_oneshot continuation decision: COMPLETE
GOAL.md definition of done: SATISFIED
Evidence: <tests/docs/git status/commit evidence>
```

## Current Recommended First Slice After Restart

Run `/goal_prompt_oneshot /home/shvdxw/.hermes/hermes-agent` after Hermes restarts. The first action is to re-read disk truth, inspect `git status --short --branch`, and continue the next safe local verification/cleanup slice from `docs/status/NEXT_ACTIONS.md` without pushing unless separately authorized.
