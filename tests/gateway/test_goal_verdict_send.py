"""Tests for gateway /goal verdict-message delivery.

The judge verdict message ("✓ Goal achieved", "⏸ budget exhausted", etc.)
must reach the user after each turn. Before this fix the code checked
``hasattr(adapter, "send_message")`` — but adapters expose ``send()``,
never ``send_message``, so the check always evaluated False and users
never saw verdicts. This test locks in the fix.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionEntry, SessionSource, build_session_key


@pytest.fixture()
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli import goals

    goals._DB_CACHE.clear()
    yield home
    goals._DB_CACHE.clear()


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


class _RecordingAdapter:
    """Minimal adapter that records send() invocations."""

    def __init__(self) -> None:
        self._pending_messages: dict = {}
        self.sends: list[dict] = []

    async def send(self, chat_id: str, content: str, reply_to=None, metadata=None):
        self.sends.append({"chat_id": chat_id, "content": content, "metadata": metadata})

        class _R:
            success = True
            message_id = "mock-msg"

        return _R()


def _make_runner_with_adapter(session_id: str = None):
    from gateway.run import GatewayRunner
    import uuid

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")},
    )
    runner.adapters = {}
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._queued_events = {}

    src = _make_source()
    # Default to a unique session_id so xdist parallel runs on the same worker
    # don't see each other's GoalManager state (DEFAULT_DB_PATH gets frozen at
    # module-import time, defeating per-test HERMES_HOME monkeypatches).
    session_entry = SessionEntry(
        session_key=build_session_key(src),
        session_id=session_id or f"goal-sess-{uuid.uuid4().hex[:8]}",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )

    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store._generate_session_key.return_value = build_session_key(src)

    adapter = _RecordingAdapter()
    runner.adapters[Platform.TELEGRAM] = adapter
    return runner, adapter, session_entry, src


@pytest.mark.asyncio
async def test_goal_verdict_done_sent_via_adapter_send(hermes_home):
    """When the judge says done, the '✓ Goal achieved' message must reach
    the user through the adapter's ``send()`` method."""
    runner, adapter, session_entry, src = _make_runner_with_adapter()

    from hermes_cli.goals import GoalManager

    mgr = GoalManager(session_entry.session_id)
    mgr.set("ship the feature")

    with patch("hermes_cli.goals.judge_goal", return_value=("done", "the feature shipped", False)):
        await runner._post_turn_goal_continuation(
            session_entry=session_entry,
            source=src,
            final_response="I shipped the feature.",
        )
        # fire-and-forget create_task — give the loop a tick
        await asyncio.sleep(0.05)

    assert len(adapter.sends) == 1, f"expected 1 send, got {len(adapter.sends)}: {adapter.sends}"
    msg = adapter.sends[0]
    assert msg["chat_id"] == "c1"
    assert "Goal achieved" in msg["content"]
    assert "the feature shipped" in msg["content"]


@pytest.mark.asyncio
async def test_goal_verdict_continue_enqueues_continuation_without_regular_goal_banner(hermes_home):
    """Regular /goal and /goal_prompt CONTINUE verdicts should silently
    enqueue the next turn. The visible ``↻ Continuing toward goal`` status
    banner is reserved for /goal_prompt_oneshot controller loops.
    """
    runner, adapter, session_entry, src = _make_runner_with_adapter()

    from hermes_cli.goals import GoalManager

    mgr = GoalManager(session_entry.session_id)
    mgr.set("polish the docs")

    with patch("hermes_cli.goals.judge_goal", return_value=("continue", "still needs work", False)):
        await runner._post_turn_goal_continuation(
            session_entry=session_entry,
            source=src,
            final_response="here's a partial edit",
        )
        await asyncio.sleep(0.05)

    assert adapter.sends == []
    # Continuation prompt enqueued for next turn
    assert adapter._pending_messages, "continuation prompt must be enqueued in pending_messages"


@pytest.mark.asyncio
async def test_goal_verdict_budget_exhausted_sends_pause(hermes_home):
    """When the budget is exhausted, a '⏸ Goal paused' message must be sent
    and no further continuation enqueued."""
    runner, adapter, session_entry, src = _make_runner_with_adapter()

    from hermes_cli.goals import GoalManager, save_goal

    mgr = GoalManager(session_entry.session_id, default_max_turns=2)
    state = mgr.set("tiny goal", max_turns=2)
    state.turns_used = 2
    save_goal(session_entry.session_id, state)

    with patch("hermes_cli.goals.judge_goal", return_value=("continue", "keep going", False)):
        await runner._post_turn_goal_continuation(
            session_entry=session_entry,
            source=src,
            final_response="still partial",
        )
        await asyncio.sleep(0.05)

    assert len(adapter.sends) == 1
    content = adapter.sends[0]["content"]
    assert "paused" in content.lower()
    assert "turns used" in content.lower()
    # No continuation enqueued when budget is exhausted
    assert not adapter._pending_messages


@pytest.mark.asyncio
async def test_goal_verdict_skipped_when_no_active_goal(hermes_home):
    """No goal set → the hook is a no-op. Nothing is sent, nothing enqueued."""
    runner, adapter, session_entry, src = _make_runner_with_adapter()

    await runner._post_turn_goal_continuation(
        session_entry=session_entry,
        source=src,
        final_response="anything",
    )
    await asyncio.sleep(0.05)

    assert adapter.sends == []
    assert adapter._pending_messages == {}


@pytest.mark.asyncio
async def test_goal_verdict_survives_adapter_without_send(hermes_home):
    """Bad adapter (no ``send`` attribute) must not crash the judge hook."""
    runner, _adapter, session_entry, src = _make_runner_with_adapter()

    from hermes_cli.goals import GoalManager

    GoalManager(session_entry.session_id).set("survive missing send")

    class _NoSendAdapter:
        def __init__(self):
            self._pending_messages: dict = {}

    runner.adapters[Platform.TELEGRAM] = _NoSendAdapter()

    with patch("hermes_cli.goals.judge_goal", return_value=("done", "ok", False)):
        # must not raise
        await runner._post_turn_goal_continuation(
            session_entry=session_entry,
            source=src,
            final_response="whatever",
        )
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_goal_verdict_continue_runs_for_already_sent_streamed_response(hermes_home):
    """Streaming/Codex may deliver the final answer itself and mark
    ``already_sent=True``. The gateway must still evaluate the final response
    for /goal continuation before returning None to suppress duplicate sends.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from gateway.platforms.base import MessageEvent, MessageType
    from hermes_cli.goals import GoalManager

    runner, adapter, session_entry, src = _make_runner_with_adapter("sid-streamed-goal")
    GoalManager(session_entry.session_id).set("continue after streamed answer")
    deferred_callbacks = []
    adapter.register_post_delivery_callback = lambda *_args, **_kwargs: deferred_callbacks.append(_args[1])

    runner.hooks = SimpleNamespace(emit=AsyncMock())
    runner._recover_telegram_topic_thread_id = lambda _source: None
    runner._cache_session_source = lambda *_args, **_kwargs: None
    runner._is_telegram_topic_lane = lambda _source: False
    runner._set_session_env = lambda _context: []
    runner._clear_session_env = lambda _tokens: None
    runner._prepare_inbound_message_text = AsyncMock(return_value="continue the goal")
    runner._bind_adapter_run_generation = lambda *_args, **_kwargs: None
    runner._is_session_run_current = lambda *_args, **_kwargs: True
    runner._should_send_voice_reply = lambda *_args, **_kwargs: False
    runner._deliver_media_from_response = AsyncMock()
    runner._thread_metadata_for_source = lambda *_args, **_kwargs: {}
    runner._reply_anchor_for_event = lambda _event: None
    runner._clear_restart_failure_count = lambda _session_key: None
    runner._session_model_overrides = {}
    runner._set_session_reasoning_override = lambda *_args, **_kwargs: None
    runner._session_db = None
    runner.session_store.load_transcript.return_value = []
    runner.session_store.has_any_sessions.return_value = True

    final_response = "partial work done; continue"
    runner._run_agent = AsyncMock(return_value={
        "final_response": final_response,
        "already_sent": True,
        "failed": False,
        "messages": [
            {"role": "user", "content": "continue the goal"},
            {"role": "assistant", "content": final_response},
        ],
        "history_offset": 0,
        "api_calls": 1,
    })

    event = MessageEvent(
        text="continue the goal",
        message_type=MessageType.TEXT,
        source=src,
        message_id="msg-1",
    )

    with patch("hermes_cli.goals.judge_goal", return_value=("continue", "streamed but more remains", False)):
        result = await runner._handle_message_with_agent(event, src, session_entry.session_key, run_generation=1)
        await asyncio.sleep(0.05)

    assert result is None
    assert not any("Continuing toward goal" in send["content"] for send in adapter.sends)
    assert deferred_callbacks == []
    assert adapter._pending_messages, "streamed already_sent final response must still enqueue goal continuation"
