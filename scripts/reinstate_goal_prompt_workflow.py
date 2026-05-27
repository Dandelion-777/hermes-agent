#!/usr/bin/env python3
"""Reinstate the local /goal_prompt workflow after a Hermes update.

This script is intentionally local and patch/dump based. It assumes you update
Hermes from the official NousResearch/hermes-agent repo first, then run this
script if /goal_prompt or /goal_prompt_oneshot regresses.

Default target repo: ~/.hermes/hermes-agent
Default patch bundle: ~/.hermes/local-overlays/hermes-goal-prompt-workflow/patches/goal-prompt-workflow-from-pr-31234.patch
Default file dumps: ~/.hermes/local-overlays/hermes-goal-prompt-workflow/file-dumps/current

Safety behavior:
- refuses to run outside a git checkout
- refuses dirty working trees unless --allow-dirty is supplied
- creates a local recovery branch by default
- exits without applying if the workflow already appears complete
- applies the local patch bundle with git am -3, so conflicts stop visibly
- can restore exact file dumps when the local workflow is ahead of the patch
- optionally runs the focused Hermes goal-prompt tests after applying
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_REPO = Path.home() / ".hermes" / "hermes-agent"
OVERLAY_ROOT = Path.home() / ".hermes" / "local-overlays" / "hermes-goal-prompt-workflow"
DEFAULT_PATCH = OVERLAY_ROOT / "patches" / "goal-prompt-workflow-from-pr-31234.patch"
DEFAULT_DUMP_DIR = OVERLAY_ROOT / "file-dumps" / "current"

FOCUSED_TESTS = [
    "tests/hermes_cli/test_goals.py",
    "tests/hermes_cli/test_goal_prompt.py",
    "tests/hermes_cli/test_commands.py",
    "tests/cli/test_cli_new_session.py",
    "tests/gateway/test_goal_prompt_command.py",
    "tests/tui_gateway/test_goal_command.py",
]

WORKFLOW_FILES = [
    "hermes_cli/goal_prompt.py",
    "hermes_cli/commands.py",
    "hermes_cli/config.py",
    "hermes_cli/goals.py",
    "cli.py",
    "gateway/run.py",
    "tui_gateway/server.py",
    "tests/hermes_cli/test_goal_prompt.py",
    "tests/hermes_cli/test_goals.py",
    "tests/hermes_cli/test_commands.py",
    "tests/cli/test_cli_new_session.py",
    "tests/gateway/test_goal_prompt_command.py",
    "tests/tui_gateway/test_goal_command.py",
    "website/docs/reference/slash-commands.md",
    "website/docs/user-guide/features/goals.md",
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workflow_check(repo: Path) -> CheckResult:
    """Conservative end-to-end marker check for the local workflow."""
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
        "GoalState oneshot metadata and deterministic verdict parsing",
        contains_all(
            read_text(repo, "hermes_cli/goals.py"),
            [
                "goal_prompt_oneshot",
                "parse_oneshot_continuation_decision",
                "ONESHOT_CONTINUATION_PROMPT_TEMPLATE",
                "Judge reasoning",
                "_oneshot_judge_verdict_summary",
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
                "missing /goal_prompt_oneshot continuation verdict",
                "internal=False",
            ],
        ),
    ))
    checks.append((
        "TUI gateway command.dispatch support",
        contains_all(
            read_text(repo, "tui_gateway/server.py"),
            ["goal_prompt_oneshot", "resolve_goal_prompt_path", 'command_name = "/goal_prompt_oneshot"'],
        ),
    ))
    checks.append((
        "focused regression tests present",
        contains_all(
            read_text(repo, "tests/hermes_cli/test_goals.py"),
            ["test_oneshot_continue_status_line", "STOP_FOR_OPERATOR", "Judge reasoning"],
        ) and contains_all(
            read_text(repo, "tests/hermes_cli/test_goal_prompt.py"),
            ["goal_prompt", "oneshot"],
        ),
    ))

    missing = [name for name, ok in checks if not ok]
    return CheckResult(complete=not missing, missing=missing)


def write_file_dumps(repo: Path, dump_dir: Path) -> Path:
    """Copy exact local workflow files into an overlay dump directory."""
    dump_dir = dump_dir.expanduser()
    files_dir = dump_dir / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest_files: list[dict[str, object]] = []
    for rel in WORKFLOW_FILES:
        src = repo / rel
        entry: dict[str, object] = {"path": rel, "exists": src.exists()}
        if src.exists() and src.is_file():
            dst = files_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            entry.update({"size": src.stat().st_size, "sha256": sha256_file(src)})
        manifest_files.append(entry)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "branch": git(repo, "branch", "--show-current", check=False) or "detached",
        "head": git(repo, "rev-parse", "HEAD", check=False),
        "dirty_status": git(repo, "status", "--short", "--untracked-files=all", check=False),
        "purpose": "Exact local file dumps for /goal_prompt and /goal_prompt_oneshot workflow recovery.",
        "telegram_ordering": "For one-shot gateway runs, send loading notice, then associated markdown documents, then enqueue kickoff.",
        "files": manifest_files,
    }
    (dump_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dump_dir


def restore_file_dumps(repo: Path, dump_dir: Path) -> None:
    """Restore workflow files from a dump directory into the target repo."""
    dump_dir = dump_dir.expanduser()
    files_dir = dump_dir / "files"
    manifest_path = dump_dir / "manifest.json"
    if not files_dir.is_dir() or not manifest_path.exists():
        raise ReinstateError(f"file dump directory is incomplete: {dump_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        rel = str(entry.get("path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise ReinstateError(f"unsafe dump path: {rel!r}")
        src = files_dir / rel
        dst = repo / rel
        if not bool(entry.get("exists")):
            continue
        if not src.exists():
            raise ReinstateError(f"dump file missing: {src}")
        expected = str(entry.get("sha256") or "")
        if expected and sha256_file(src) != expected:
            raise ReinstateError(f"dump checksum mismatch: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


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
        "hermes_cli/commands.py",
        "hermes_cli/config.py",
        "hermes_cli/goals.py",
        "hermes_cli/goal_prompt.py",
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
        run(["git", "am", "-3", str(patch)], repo, check=True, capture=True)
    except ReinstateError as exc:
        raise ReinstateError(
            f"patch application stopped. Inspect conflicts in {repo}; use 'git am --abort' to cancel "
            f"or resolve conflicts and run 'git am --continue'.\n{exc}"
        ) from exc


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel in WORKFLOW_FILES:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("", encoding="utf-8")
        assert not workflow_check(root).complete
        (root / "hermes_cli/goal_prompt.py").write_text(
            "resolve_goal_prompt_path extract_goal_prompt_text GOAL_PROMPT.md Judge reasoning:",
            encoding="utf-8",
        )
        (root / "hermes_cli/commands.py").write_text(
            "goal_prompt goal-prompt goal_prompt_oneshot goal-prompt-oneshot",
            encoding="utf-8",
        )
        (root / "hermes_cli/goals.py").write_text(
            "goal_prompt_oneshot parse_oneshot_continuation_decision "
            "ONESHOT_CONTINUATION_PROMPT_TEMPLATE Judge reasoning _oneshot_judge_verdict_summary",
            encoding="utf-8",
        )
        (root / "cli.py").write_text(
            "_handle_goal_prompt_command goal-prompt-oneshot _maybe_refresh_oneshot_goal_after_compactions",
            encoding="utf-8",
        )
        (root / "gateway/run.py").write_text(
            "_handle_goal_prompt_command goal-prompt-oneshot "
            "_maybe_refresh_oneshot_goal_after_compactions goal_prompt_document_paths "
            "_send_goal_prompt_documents _register_goal_prompt_oneshot_post_delivery "
            "register_post_delivery_callback send_document _enqueue_goal_kickoff_event "
            "After the loading notice is delivered, send docs, then queue kickoff",
            encoding="utf-8",
        )
        (root / "tui_gateway/server.py").write_text(
            'goal_prompt_oneshot resolve_goal_prompt_path command_name = "/goal_prompt_oneshot"',
            encoding="utf-8",
        )
        (root / "tests/hermes_cli/test_goals.py").write_text(
            "test_oneshot_continue_status_line STOP_FOR_OPERATOR Judge reasoning",
            encoding="utf-8",
        )
        (root / "tests/hermes_cli/test_goal_prompt.py").write_text("goal_prompt oneshot", encoding="utf-8")
        (root / "tests/gateway/test_goal_prompt_command.py").write_text(
            'test_gateway_goal_prompt_oneshot_post_delivery_sends_docs_before_kickoff '
            '("doc", "GOAL_PROMPT.md" ("doc", "GOAL.md" ("kickoff", "Continue safely")',
            encoding="utf-8",
        )
        assert workflow_check(root).complete
        write_file_dumps(root, root / "dump")
        for rel in WORKFLOW_FILES:
            path = root / rel
            if path.exists():
                path.write_text("changed", encoding="utf-8")
        restore_file_dumps(root, root / "dump")
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
    parser.add_argument("--dump-current", action="store_true", help=f"write exact workflow file dumps to --dump-dir (default: {DEFAULT_DUMP_DIR})")
    parser.add_argument("--dump-dir", type=Path, default=DEFAULT_DUMP_DIR, help=f"workflow file dump directory (default: {DEFAULT_DUMP_DIR})")
    parser.add_argument("--restore-dumps", action="store_true", help="restore exact workflow files from --dump-dir instead of applying the patch bundle")
    parser.add_argument("--self-test", action="store_true", help="run script helper self-tests and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    repo = repo_root(args.repo.expanduser())
    print(f"Hermes repo: {repo}")
    print(f"Current branch: {git(repo, 'branch', '--show-current') or 'detached'}")
    print(f"Patch bundle: {args.patch.expanduser()}")

    if args.dump_current:
        dumped = write_file_dumps(repo, args.dump_dir)
        print(f"Wrote workflow file dumps: {dumped}")
        if args.check_only:
            return 0

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

    if args.restore_dumps:
        restore_file_dumps(repo, args.dump_dir)
        print(f"workflow file dumps restored from {args.dump_dir.expanduser()}")
    else:
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
