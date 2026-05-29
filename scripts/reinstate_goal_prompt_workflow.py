#!/usr/bin/env python3
"""Reinstate the local /goal_prompt workflow after an official Hermes update.

This script is intentionally local and patch-based. It assumes you update
Hermes from the official NousResearch/hermes-agent repo first, then run this
script if /goal_prompt or /goal_prompt_oneshot regresses.

Default target repo: ~/.hermes/hermes-agent
Default patch bundle: ~/.hermes/local-overlays/hermes-goal-prompt-workflow/patches/goal-prompt-workflow-with-telegram-doc-ordering.patch

Safety behavior:
- refuses to run outside a git checkout
- refuses dirty working trees unless --allow-dirty is supplied
- creates a local recovery branch by default
- exits without applying if the workflow already appears complete
- applies the local patch bundle with git apply -3 --index, so conflicts stop visibly
- optionally runs the focused Hermes goal-prompt tests after applying
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_REPO = Path.home() / ".hermes" / "hermes-agent"
DEFAULT_PATCH = (
    Path.home()
    / ".hermes"
    / "local-overlays"
    / "hermes-goal-prompt-workflow"
    / "patches"
    / "goal-prompt-workflow-with-telegram-doc-ordering.patch"
)
FOCUSED_TESTS = [
    "tests/hermes_cli/test_goals.py",
    "tests/hermes_cli/test_goal_prompt.py",
    "tests/hermes_cli/test_commands.py",
    "tests/cli/test_cli_new_session.py",
    "tests/gateway/test_goal_prompt_command.py",
    "tests/gateway/test_goal_verdict_send.py",
    "tests/gateway/test_post_delivery_callback_chaining.py",
    "tests/gateway/test_gateway_final_streaming_policy.py",
    "tests/tui_gateway/test_goal_command.py",
    "tests/run_agent/test_streaming.py::TestHasStreamConsumers",
]


@dataclass
class CheckResult:
    complete: bool
    missing: list[str]


class ReinstateError(RuntimeError):
    pass


def run(cmd: Sequence[str], cwd: Path, *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if check and proc.returncode != 0:
        out = (proc.stdout or "").strip()
        raise ReinstateError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{out}")
    return proc


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return (run(["git", *args], cwd, check=check).stdout or "").strip()


def repo_root(path: Path) -> Path:
    if not path.exists():
        raise ReinstateError(f"repo path does not exist: {path}")
    root = git(path, "rev-parse", "--show-toplevel")
    return Path(root)


def is_dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--short", "--untracked-files=all"))


def read_text(repo: Path, rel: str) -> str:
    p = repo / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def contains_all(text: str, needles: Iterable[str]) -> bool:
    return all(n in text for n in needles)


def workflow_check(repo: Path) -> CheckResult:
    """Conservative end-to-end marker check for our local workflow."""
    checks: list[tuple[str, bool]] = []

    checks.append((
        "hermes_cli/goal_prompt.py shared parser/resolver",
        contains_all(
            read_text(repo, "hermes_cli/goal_prompt.py"),
            ["resolve_goal_prompt_path", "extract_goal_prompt_text", "GOAL_PROMPT.md", "Judge reasoning:"],
        ),
    ))
    checks.append((
        "slash command registry aliases",
        contains_all(
            read_text(repo, "hermes_cli/commands.py"),
            ["goal_prompt", "goal-prompt", "goal_prompt_oneshot", "goal-prompt-oneshot"],
        ),
    ))
    checks.append((
        "GoalState oneshot metadata, deterministic verdict parsing, and slice judge gate",
        contains_all(
            read_text(repo, "hermes_cli/goals.py"),
            [
                "goal_prompt_oneshot",
                "parse_oneshot_continuation_decision",
                "ONESHOT_CONTINUATION_PROMPT_TEMPLATE",
                "Judge reasoning",
                "_oneshot_judge_verdict_summary",
                "ONESHOT_SLICE_JUDGE_SYSTEM_PROMPT",
                "judge_goal_slice",
                "goal_slice_judge",
                "pass_continue",
                "pass_complete",
            ],
        ) and contains_all(
            read_text(repo, "gateway/run.py"),
            [
                'decision.get("oneshot_repair")',
            ],
        ),
    ))
    checks.append((
        "CLI /goal_prompt and /goal_prompt_oneshot handlers",
        contains_all(
            read_text(repo, "cli.py"),
            ["_handle_goal_prompt_command", "goal-prompt-oneshot", "_maybe_refresh_oneshot_goal_after_compactions"],
        ),
    ))
    checks.append((
        "gateway /goal_prompt and /goal_prompt_oneshot handlers",
        contains_all(
            read_text(repo, "gateway/run.py"),
            ["_handle_goal_prompt_command", "goal-prompt-oneshot", "_maybe_refresh_oneshot_goal_after_compactions"],
        ),
    ))
    checks.append((
        "gateway Telegram docs-before-kickoff ordering and captionless file dumps",
        contains_all(
            read_text(repo, "gateway/run.py"),
            [
                "goal_prompt_document_paths",
                "_send_goal_prompt_documents",
                "_register_goal_prompt_oneshot_post_delivery",
                "register_post_delivery_callback",
                "generation=generation",
                "send_document",
                "caption=None",
                "_enqueue_goal_kickoff_event",
                "_hermes_goal_prompt_oneshot",
                "missing /goal_prompt_oneshot continuation verdict",
                "context compactions; ",
                "goal oneshot compaction refresh notice failed",
                "internal=False",
            ],
        ),
    ))
    checks.append((
        "TUI gateway command.dispatch support",
        contains_all(
            read_text(repo, "tui_gateway/server.py"),
            ["goal_prompt_oneshot", "resolve_goal_prompt_path", "command_name = \"/goal_prompt_oneshot\""],
        ),
    ))
    checks.append((
        "focused regression tests present",
        contains_all(
            read_text(repo, "tests/hermes_cli/test_goals.py"),
            [
                "test_oneshot_continue_status_line",
                "test_oneshot_continue_sentinel_uses_slice_judge_before_advancing",
                "test_judge_goal_slice_uses_goal_slice_judge_auxiliary_task",
                "test_oneshot_slice_judge_repair_queues_repair_prompt_not_next_slice",
                "STOP_FOR_OPERATOR",
                "Judge reasoning",
            ],
        ) and contains_all(
            read_text(repo, "tests/hermes_cli/test_goal_prompt.py"),
            ["goal_prompt", "oneshot"],
        ) and contains_all(
            read_text(repo, "tests/gateway/test_goal_prompt_command.py"),
            [
                "post_delivery_sends_docs_before_kickoff",
                '("doc", "GOAL_PROMPT.md", None',
                '("doc", "GOAL.md", None',
                "registered_generation",
                "plain_message_does_not_restart_without_verdict",
                "continue_requeues_visible_prompt_loader",
                "compaction_refresh_sends_visible_notice_before_reload",
                "reload_returns_notice_and_queues",
                "pause_clears_stale_oneshot_loader_when_no_goal_state",
                "pause_clears_stale_oneshot_post_delivery_callback_without_goal_state",
                "status_clears_stale_oneshot_post_delivery_callback",
                "goal_continuation_event_recognizes_bare_oneshot_loader",
            ],
        ) and contains_all(
            read_text(repo, "tests/gateway/test_goal_verdict_send.py"),
            [
                "test_goal_verdict_continue_enqueues_continuation_without_regular_goal_banner",
                "test_goal_verdict_continue_runs_for_already_sent_streamed_response",
            ],
        ) and contains_all(
            read_text(repo, "tests/gateway/test_post_delivery_callback_chaining.py"),
            ["test_async_callbacks_chain_and_are_awaitable"],
        ) and contains_all(
            read_text(repo, "tests/gateway/test_gateway_final_streaming_policy.py"),
            ["test_gateway_keeps_tool_streaming_but_does_not_stream_final_text"],
        ) and contains_all(
            read_text(repo, "tests/run_agent/test_streaming.py"),
            ["test_delta_callback_return_false_does_not_record_text_as_delivered"],
        ),
    ))

    missing = [name for name, ok in checks if not ok]
    return CheckResult(complete=not missing, missing=missing)


def choose_python(repo: Path) -> str:
    for candidate in [repo / ".venv" / "bin" / "python", repo / "venv" / "bin" / "python"]:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def create_recovery_branch(repo: Path, name: str | None) -> str:
    current = git(repo, "branch", "--show-current") or "detached"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch = name or f"local/reinstate-goal-prompt-workflow-{stamp}"
    existing = git(repo, "branch", "--list", branch)
    if existing:
        raise ReinstateError(f"branch already exists: {branch}")
    git(repo, "switch", "-c", branch)
    return f"created branch {branch} from {current}"


def run_verification(repo: Path) -> None:
    py = choose_python(repo)
    compile_targets = [
        "cli.py",
        "gateway/run.py",
        "gateway/platforms/base.py",
        "hermes_cli/commands.py",
        "hermes_cli/config.py",
        "hermes_cli/goals.py",
        "hermes_cli/goal_prompt.py",
        "run_agent.py",
        "tui_gateway/server.py",
    ]
    run([py, "-m", "py_compile", *compile_targets], repo, check=True)
    run([py, "-m", "pytest", *FOCUSED_TESTS, "-q", "-o", "addopts="], repo, check=True, capture=False)


def apply_patch_bundle(repo: Path, patch: Path) -> None:
    if not patch.exists():
        raise ReinstateError(f"patch bundle not found: {patch}")
    if patch.stat().st_size == 0:
        raise ReinstateError(f"patch bundle is empty: {patch}")
    try:
        # The recovery bundle is a plain git diff captured from the local overlay.
        # Use --index so successful application stages exactly the restored files;
        # --3way keeps upstream-drift conflicts visible instead of silently fuzzing.
        run(["git", "apply", "-3", "--index", str(patch)], repo, check=True, capture=True)
    except ReinstateError as exc:
        raise ReinstateError(
            f"patch application stopped. Inspect conflicts in {repo}; use 'git apply --abort' if available "
            f"or reset/stash the conflicted files before retrying.\n{exc}"
        ) from exc


def self_test() -> None:
    # Lightweight tests for marker detection without needing a real Hermes checkout.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel in [
            "hermes_cli/goal_prompt.py",
            "hermes_cli/commands.py",
            "hermes_cli/goals.py",
            "cli.py",
            "gateway/run.py",
            "tui_gateway/server.py",
            "tests/hermes_cli/test_goals.py",
            "tests/hermes_cli/test_goal_prompt.py",
            "tests/gateway/test_goal_prompt_command.py",
            "tests/gateway/test_goal_verdict_send.py",
            "tests/gateway/test_post_delivery_callback_chaining.py",
            "tests/gateway/test_gateway_final_streaming_policy.py",
            "tests/run_agent/test_streaming.py",
        ]:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("", encoding="utf-8")
        assert not workflow_check(root).complete
        (root / "hermes_cli/goal_prompt.py").write_text("resolve_goal_prompt_path extract_goal_prompt_text GOAL_PROMPT.md Judge reasoning:", encoding="utf-8")
        (root / "hermes_cli/commands.py").write_text("goal_prompt goal-prompt goal_prompt_oneshot goal-prompt-oneshot", encoding="utf-8")
        (root / "hermes_cli/goals.py").write_text("goal_prompt_oneshot parse_oneshot_continuation_decision ONESHOT_CONTINUATION_PROMPT_TEMPLATE Judge reasoning _oneshot_judge_verdict_summary ONESHOT_SLICE_JUDGE_SYSTEM_PROMPT judge_goal_slice goal_slice_judge pass_continue pass_complete", encoding="utf-8")
        (root / "cli.py").write_text("_handle_goal_prompt_command goal-prompt-oneshot _maybe_refresh_oneshot_goal_after_compactions", encoding="utf-8")
        (root / "gateway/run.py").write_text("_handle_goal_prompt_command goal-prompt-oneshot _maybe_refresh_oneshot_goal_after_compactions goal_prompt_document_paths _send_goal_prompt_documents _register_goal_prompt_oneshot_post_delivery register_post_delivery_callback generation=generation send_document caption=None _enqueue_goal_kickoff_event _hermes_goal_prompt_oneshot missing /goal_prompt_oneshot continuation verdict context compactions; goal oneshot compaction refresh notice failed internal=False decision.get(\"oneshot_repair\")", encoding="utf-8")
        (root / "tui_gateway/server.py").write_text("goal_prompt_oneshot resolve_goal_prompt_path command_name = \"/goal_prompt_oneshot\"", encoding="utf-8")
        (root / "tests/hermes_cli/test_goals.py").write_text("test_oneshot_continue_status_line test_oneshot_continue_sentinel_uses_slice_judge_before_advancing test_judge_goal_slice_uses_goal_slice_judge_auxiliary_task test_oneshot_slice_judge_repair_queues_repair_prompt_not_next_slice STOP_FOR_OPERATOR Judge reasoning", encoding="utf-8")
        (root / "tests/hermes_cli/test_goal_prompt.py").write_text("goal_prompt oneshot", encoding="utf-8")
        (root / "tests/gateway/test_goal_prompt_command.py").write_text("post_delivery_sends_docs_before_kickoff (\"doc\", \"GOAL_PROMPT.md\", None (\"doc\", \"GOAL.md\", None registered_generation plain_message_does_not_restart_without_verdict continue_requeues_visible_prompt_loader compaction_refresh_sends_visible_notice_before_reload reload_returns_notice_and_queues pause_clears_stale_oneshot_loader_when_no_goal_state pause_clears_stale_oneshot_post_delivery_callback_without_goal_state status_clears_stale_oneshot_post_delivery_callback goal_continuation_event_recognizes_bare_oneshot_loader", encoding="utf-8")
        (root / "tests/gateway/test_goal_verdict_send.py").write_text("test_goal_verdict_continue_enqueues_continuation_without_regular_goal_banner test_goal_verdict_continue_runs_for_already_sent_streamed_response", encoding="utf-8")
        (root / "tests/gateway/test_post_delivery_callback_chaining.py").write_text("test_async_callbacks_chain_and_are_awaitable", encoding="utf-8")
        (root / "tests/gateway/test_gateway_final_streaming_policy.py").write_text("test_gateway_keeps_tool_streaming_but_does_not_stream_final_text", encoding="utf-8")
        (root / "tests/run_agent/test_streaming.py").write_text("test_delta_callback_return_false_does_not_record_text_as_delivered", encoding="utf-8")
        assert workflow_check(root).complete
    print("self-test passed")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help=f"Hermes checkout to patch (default: {DEFAULT_REPO})")
    parser.add_argument("--patch", type=Path, default=DEFAULT_PATCH, help=f"format-patch bundle to apply (default: {DEFAULT_PATCH})")
    parser.add_argument("--check-only", action="store_true", help="only report whether the local workflow is present")
    parser.add_argument("--allow-dirty", action="store_true", help="allow applying on a dirty working tree (not recommended)")
    parser.add_argument("--no-branch", action="store_true", help="apply on the current branch instead of creating a recovery branch")
    parser.add_argument("--branch-name", help="custom branch name when creating a recovery branch")
    parser.add_argument("--skip-tests", action="store_true", help="skip focused pytest verification after applying")
    parser.add_argument("--force", action="store_true", help="apply patch even if marker checks say workflow is already present")
    parser.add_argument("--self-test", action="store_true", help="run script helper self-tests and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    repo = repo_root(args.repo.expanduser())
    print(f"Hermes repo: {repo}")
    print(f"Current branch: {git(repo, 'branch', '--show-current') or 'detached'}")
    print(f"Patch bundle: {args.patch.expanduser()}")

    check = workflow_check(repo)
    if check.complete and not args.force:
        print("/goal_prompt workflow appears complete; no patch needed.")
        if not args.skip_tests and not args.check_only:
            print("Running focused verification anyway...")
            run_verification(repo)
        return 0

    if check.missing:
        print("Missing/incomplete workflow markers:")
        for item in check.missing:
            print(f"  - {item}")

    if args.check_only:
        return 1 if check.missing else 0

    if is_dirty(repo) and not args.allow_dirty:
        raise ReinstateError(
            "working tree is dirty; commit/stash/inspect first, or pass --allow-dirty if you intentionally want this"
        )

    if not args.no_branch:
        print(create_recovery_branch(repo, args.branch_name))

    apply_patch_bundle(repo, args.patch.expanduser())
    print("patch bundle applied")

    post = workflow_check(repo)
    if not post.complete:
        raise ReinstateError("patch applied, but workflow markers are still missing: " + ", ".join(post.missing))

    if not args.skip_tests:
        run_verification(repo)
        print("focused verification passed")
    else:
        print("focused verification skipped")

    print("Reinstated /goal_prompt and /goal_prompt_oneshot workflow. Restart Hermes CLI/gateway to load code changes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReinstateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
