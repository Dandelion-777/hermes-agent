import types
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest

from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner


@pytest.mark.asyncio
async def test_gateway_goal_prompt_loads_prompt_and_dispatches_goal(tmp_path: Path):
    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("```text\nContinue from NEXT_ACTIONS.md\n```", encoding="utf-8")

    runner = object.__new__(GatewayRunner)
    seen = {}

    async def fake_goal_handler(self, event):
        seen["text"] = event.text
        return "Goal set."

    runner._handle_goal_command = types.MethodType(fake_goal_handler, runner)
    event = MessageEvent(
        text=f"/goal_prompt {tmp_path}",
        message_type=MessageType.TEXT,
    )

    result = await runner._handle_goal_prompt_command(event)

    assert seen["text"] == "/goal Continue from NEXT_ACTIONS.md"
    assert "Loading goal prompt" in result
    assert "Goal set." in result
    # The handler restores the original event text after dispatch.
    assert event.text == f"/goal_prompt {tmp_path}"


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_queues_goal_with_counter_and_post_delivery_kickoff(tmp_path: Path, monkeypatch):
    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    goal = tmp_path / "GOAL.md"
    goal.write_text("# Goal\n", encoding="utf-8")
    prompt.write_text(f"```text\n/goal Continue from NEXT_ACTIONS.md\n- {goal}\n```", encoding="utf-8")

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda _source: SimpleNamespace(session_id="goal-prompt-oneshot-test")
    )
    registered = {}

    def fake_register(self, event, goal_text, docs):
        registered["goal_text"] = goal_text
        registered["docs"] = docs

    runner._register_goal_prompt_oneshot_post_delivery = types.MethodType(fake_register, runner)
    event = MessageEvent(
        text=f"/goal_prompt_oneshot {tmp_path}",
        message_type=MessageType.TEXT,
        source=SimpleNamespace(platform="telegram", chat_id="123"),
    )

    result = await runner._handle_goal_prompt_command(event, oneshot=True)

    assert "Loading one-shot goal prompt" in result
    assert "Goal queued (0/250) (250-turn budget). Kickoff sent as the next turn." in result
    assert "Will refresh after 5 compactions" in result
    assert registered["goal_text"].startswith("Continue from NEXT_ACTIONS.md")
    assert "/goal_prompt_oneshot mode" in registered["goal_text"]
    assert prompt.resolve() in registered["docs"]
    assert goal.resolve() in registered["docs"]
    state = goals.GoalManager("goal-prompt-oneshot-test").state
    assert state.goal_mode == "goal_prompt_oneshot"
    assert state.goal_prompt_path == str(prompt)
    assert state.max_turns == 250
    assert state.compaction_refresh_interval == 5
    assert state.turns_used == 0
    assert event.text == f"/goal_prompt_oneshot {tmp_path}"
    goals._DB_CACHE.clear()


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_post_delivery_sends_docs_before_kickoff(tmp_path: Path):
    docs = [tmp_path / "GOAL_PROMPT.md", tmp_path / "GOAL.md"]
    for path in docs:
        path.write_text(path.name, encoding="utf-8")

    runner = object.__new__(GatewayRunner)
    source = SimpleNamespace(platform="telegram", chat_id="123", message_id="source-msg")
    event = MessageEvent(
        text="/goal_prompt_oneshot",
        message_type=MessageType.TEXT,
        source=source,
        message_id="command-msg",
    )
    order = []

    class FakeAdapter:
        def register_post_delivery_callback(self, session_key, callback, *, generation=None):
            self.callback = callback

        async def send_document(self, chat_id, file_path, caption=None, file_name=None, reply_to=None, metadata=None):
            order.append(("doc", Path(file_path).name, caption, reply_to))
            return SimpleNamespace(success=True)

    adapter = FakeAdapter()
    runner.adapters = {"telegram": adapter}
    runner._session_key_for_source = lambda _source: "session-key"
    runner._thread_metadata_for_source = lambda *_args, **_kwargs: {"thread": "meta"}
    runner._enqueue_fifo = lambda _key, queued_event, _adapter: order.append(("kickoff", queued_event.text))

    runner._register_goal_prompt_oneshot_post_delivery(event, "Continue safely", docs)
    await adapter.callback()

    assert order == [
        ("doc", "GOAL_PROMPT.md", None, "command-msg"),
        ("doc", "GOAL.md", None, "command-msg"),
        ("kickoff", "Continue safely"),
    ]


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_continue_requeues_visible_prompt_loader(tmp_path: Path, monkeypatch):
    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("```text\n/goal Continue project\n```", encoding="utf-8")

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    goals.GoalManager("sid-requeue", default_max_turns=250).set(
        "Continue project",
        goal_mode="goal_prompt_oneshot",
        goal_prompt_path=str(prompt),
        compaction_refresh_interval=5,
    )

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    runner.adapters = {"telegram": object()}
    runner._session_key_for_source = lambda _source: "session-key"
    async def fake_refresh(**_kwargs):
        return False

    runner._maybe_refresh_oneshot_goal_after_compactions_gateway = fake_refresh
    notices = []
    queued = []
    queued_events = []

    async def fake_notice(_source, message):
        notices.append(message)

    runner._defer_goal_status_notice_after_delivery = fake_notice
    def fake_enqueue(_key, event, _adapter):
        queued.append(event.text)
        queued_events.append(event)

    runner._enqueue_fifo = fake_enqueue

    with patch.object(goals, "judge_goal_slice", return_value=("pass_continue", "slice verified", False, "")):
        await runner._post_turn_goal_continuation(
            session_entry=SimpleNamespace(session_id="sid-requeue"),
            source=SimpleNamespace(platform="telegram", chat_id="123", message_id="msg-1"),
            final_response=(
                "Judge reasoning: GOAL.md is not satisfied and safe work remains\n"
                "/goal_prompt_oneshot continuation decision: CONTINUE\n"
                "GOAL.md definition of done: NOT SATISFIED\n"
                "Next safe autonomous slice: next slice\n"
                "Operator input needed before next slice: None\n"
                "Hard stop: No"
            ),
        )

    assert notices
    assert "judge: GOAL.md is not satisfied and safe work remains" in notices[0]
    assert queued == [f"/goal_prompt_oneshot {prompt}"]
    assert queued_events[0].internal is False
    state = goals.GoalManager("sid-requeue").state
    assert state.turns_used == 1
    goals._DB_CACHE.clear()


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_compaction_refresh_sends_visible_notice_before_reload(tmp_path: Path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("```text\n/goal Continue project\n```", encoding="utf-8")

    state = goals.GoalManager("sid-before-refresh", default_max_turns=250).set(
        "Continue project",
        max_turns=250,
        goal_mode="goal_prompt_oneshot",
        goal_prompt_path=str(prompt),
        compaction_refresh_interval=5,
    )
    state.turns_used = 5
    goals.save_goal("sid-before-refresh", state)

    order = []

    class FakeAdapter:
        async def send(self, chat_id, message, metadata=None):
            order.append(("notice", chat_id, message))
            return SimpleNamespace(success=True)

    runner = object.__new__(GatewayRunner)
    runner.adapters = {"telegram": FakeAdapter()}
    runner.session_store = SimpleNamespace(
        reset_session=lambda _session_key: SimpleNamespace(session_id="sid-after-refresh")
    )
    runner._session_key_for_source = lambda _source: "session-key"
    runner._agent_compression_count_for_session_key = lambda _session_key: 5
    runner._thread_metadata_for_source = lambda *_args, **_kwargs: {}
    runner._clear_goal_pending_continuations = lambda *_args, **_kwargs: None
    runner._evict_cached_agent = lambda *_args, **_kwargs: None
    runner._clear_session_boundary_security_state = lambda *_args, **_kwargs: None
    runner._enqueue_fifo = lambda _key, event, _adapter: order.append(("reload", event.text, event.internal))

    refreshed = await runner._maybe_refresh_oneshot_goal_after_compactions_gateway(
        mgr=SimpleNamespace(state=state),
        session_entry=SimpleNamespace(session_id="sid-before-refresh"),
        source=SimpleNamespace(platform="telegram", chat_id="123", message_id="msg-1"),
    )

    assert refreshed is True
    assert order == [
        (
            "notice",
            "123",
            "↺ /goal_prompt_oneshot reached 5 context compactions; "
            "starting a fresh /new session and reloading GOAL_PROMPT.md.",
        ),
        ("reload", f"/goal_prompt_oneshot {prompt}", True),
    ]
    goals._DB_CACHE.clear()


@pytest.mark.asyncio
async def test_gateway_goal_prompt_reports_missing_file(tmp_path: Path):
    runner = object.__new__(GatewayRunner)
    event = MessageEvent(
        text=f"/goal_prompt {tmp_path}",
        message_type=MessageType.TEXT,
    )

    result = await runner._handle_goal_prompt_command(event)

    assert "No GOAL_PROMPT.md found" in result
    assert "Usage: `/goal_prompt [project-root-or-prompt-file]`" in result


def test_gateway_session_split_carries_persisted_oneshot_goal_state(tmp_path: Path):
    from hermes_cli.goals import GoalManager, save_goal

    runner = object.__new__(GatewayRunner)
    old_session_id = f"gateway_parent_{tmp_path.name}"
    new_session_id = f"gateway_child_{tmp_path.name}"
    state = GoalManager(old_session_id, default_max_turns=321).set(
        "Continue gateway oneshot goal",
        goal_mode="goal_prompt_oneshot",
        goal_prompt_path=str(tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"),
        compaction_refresh_interval=5,
    )
    state.turns_used = 9
    save_goal(old_session_id, state)

    assert runner._carry_goal_state_between_sessions(
        old_session_id,
        new_session_id,
        reason="compression",
    ) is True

    carried = GoalManager(new_session_id).state
    assert carried is not None
    assert carried.goal == "Continue gateway oneshot goal"
    assert carried.goal_mode == "goal_prompt_oneshot"
    assert carried.goal_prompt_path.endswith("GOAL_PROMPT.md")
    assert carried.compaction_refresh_interval == 5
    assert carried.turns_used == 9
    assert carried.max_turns == 321


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_reload_returns_notice_and_queues(tmp_path: Path, monkeypatch):
    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("```text\n/goal Continue silently\n```", encoding="utf-8")

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda _source: SimpleNamespace(session_id="goal-prompt-oneshot-internal")
    )
    registered = {}

    def fake_register(self, event, goal_text, docs):
        registered["event_internal"] = event.internal
        registered["goal_text"] = goal_text
        registered["docs"] = docs

    runner._register_goal_prompt_oneshot_post_delivery = types.MethodType(fake_register, runner)
    event = MessageEvent(
        text=f"/goal_prompt_oneshot {tmp_path}",
        message_type=MessageType.TEXT,
        source=SimpleNamespace(platform="telegram", chat_id="123"),
        internal=False,
    )

    result = await runner._handle_goal_prompt_command(event, oneshot=True)

    assert "Loading one-shot goal prompt" in result
    assert "Goal queued (0/250) (250-turn budget). Kickoff sent as the next turn." in result
    assert registered["event_internal"] is False
    assert registered["goal_text"].startswith("Continue silently")
    assert prompt.resolve() in registered["docs"]
    state = goals.GoalManager("goal-prompt-oneshot-internal").state
    assert state.goal_mode == "goal_prompt_oneshot"
    goals._DB_CACHE.clear()


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_post_delivery_registers_current_generation(tmp_path: Path):
    """The loading-notice callback must be tied to the active run generation.

    Otherwise BasePlatformAdapter pops callbacks with the current generation,
    skips legacy generation-less entries, and can leave stale one-shot kickoff
    callbacks to fire on a later ordinary message/command.
    """
    docs = [tmp_path / "GOAL_PROMPT.md"]
    docs[0].write_text("prompt", encoding="utf-8")

    runner = object.__new__(GatewayRunner)
    source = SimpleNamespace(platform="telegram", chat_id="123")
    event = MessageEvent(
        text="/goal_prompt_oneshot",
        message_type=MessageType.TEXT,
        source=source,
        message_id="command-msg",
    )

    class FakeAdapter:
        def __init__(self):
            self._active_sessions = {"session-key": SimpleNamespace(_hermes_run_generation=17)}
            self.registered_generation = None
            self.callback = None

        def register_post_delivery_callback(self, session_key, callback, *, generation=None):
            self.registered_generation = generation
            self.callback = callback

        async def send_document(self, *args, **kwargs):
            return SimpleNamespace(success=True)

    adapter = FakeAdapter()
    runner.adapters = {"telegram": adapter}
    runner._session_key_for_source = lambda _source: "session-key"
    runner._thread_metadata_for_source = lambda *_args, **_kwargs: {}
    runner._reply_anchor_for_event = lambda _event: None
    runner._enqueue_fifo = lambda *_args, **_kwargs: None

    runner._register_goal_prompt_oneshot_post_delivery(event, "Continue safely", docs)

    assert adapter.registered_generation == 17


@pytest.mark.asyncio
async def test_gateway_goal_prompt_oneshot_plain_message_does_not_restart_without_verdict(tmp_path: Path, monkeypatch):
    """An active one-shot goal must not restart from an ordinary reply.

    Only a deterministic /goal_prompt_oneshot verdict block may drive the
    controller. A normal user message sent after a paused/stale/active one-shot
    session should not fall through to the fail-open LLM judge and enqueue a
    fresh /goal_prompt_oneshot loader.
    """
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("```text\n/goal Continue project\n```", encoding="utf-8")

    session_id = "sid-oneshot-plain-message"
    goals.GoalManager(session_id, default_max_turns=250).set(
        "Continue project",
        goal_mode="goal_prompt_oneshot",
        goal_prompt_path=str(prompt),
        compaction_refresh_interval=5,
    )

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    queued = []

    class FakeAdapter:
        def __init__(self):
            self._pending_messages = {}

        async def send(self, *args, **kwargs):
            return SimpleNamespace(success=True)

    adapter = FakeAdapter()
    runner.adapters = {"telegram": adapter}
    runner._session_key_for_source = lambda _source: "session-key"
    async def fake_refresh(**_kwargs):
        return False

    runner._maybe_refresh_oneshot_goal_after_compactions_gateway = fake_refresh
    runner._defer_goal_status_notice_after_delivery = lambda *_args, **_kwargs: None

    def fake_enqueue(_key, event, _adapter):
        queued.append(event.text)

    runner._enqueue_fifo = fake_enqueue

    await runner._post_turn_goal_continuation(
        session_entry=SimpleNamespace(session_id=session_id),
        source=SimpleNamespace(platform="telegram", chat_id="123", message_id="msg-ordinary"),
        final_response="Sure — I can help with that ordinary follow-up. No controller verdict here.",
    )

    assert queued == []
    state = goals.GoalManager(session_id).state
    assert state.status == "paused"
    assert state.paused_reason == "missing /goal_prompt_oneshot continuation verdict"
    goals._DB_CACHE.clear()

@pytest.mark.asyncio
async def test_gateway_goal_pause_clears_stale_oneshot_loader_when_no_goal_state(tmp_path: Path, monkeypatch):
    """A stale queued one-shot reload must not survive a later /goal pause.

    Users can observe "No active goal" when durable goal state already moved or
    was cleared, while the adapter still has a queued /goal_prompt_oneshot reload
    in the session slot.  The pause command must clear that synthetic controller
    event anyway so the next unrelated message cannot kick off another slice.
    """
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    prompt = tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("```text\n/goal Continue project\n```", encoding="utf-8")

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda _source: SimpleNamespace(session_id="sid-no-active-goal")
    )

    class FakeAdapter:
        def __init__(self):
            self._pending_messages = {
                "session-key": MessageEvent(
                    text=f"/goal_prompt_oneshot {prompt}",
                    message_type=MessageType.TEXT,
                    source=SimpleNamespace(platform="telegram", chat_id="123"),
                )
            }

    adapter = FakeAdapter()
    runner.adapters = {"telegram": adapter}
    runner._session_key_for_source = lambda _source: "session-key"

    event = MessageEvent(
        text="/goal pause",
        message_type=MessageType.TEXT,
        source=SimpleNamespace(platform="telegram", chat_id="123"),
    )

    result = await runner._handle_goal_command(event)

    assert "No active goal" in result or "No goal" in result
    assert adapter._pending_messages == {}
    goals._DB_CACHE.clear()

@pytest.mark.asyncio
async def test_gateway_goal_pause_clears_stale_oneshot_post_delivery_callback_without_goal_state(tmp_path: Path, monkeypatch):
    """A no-goal /goal pause must also remove stale one-shot doc/kickoff callbacks."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda _source: SimpleNamespace(session_id="sid-no-active-goal-callback")
    )

    def stale_goal_callback():
        raise AssertionError("stale callback should have been cleared")

    stale_goal_callback._hermes_goal_prompt_oneshot = True

    class FakeAdapter:
        def __init__(self):
            self._pending_messages = {}
            self._post_delivery_callbacks = {"session-key": (17, stale_goal_callback)}

    adapter = FakeAdapter()
    runner.adapters = {"telegram": adapter}
    runner._session_key_for_source = lambda _source: "session-key"

    event = MessageEvent(
        text="/goal pause",
        message_type=MessageType.TEXT,
        source=SimpleNamespace(platform="telegram", chat_id="123"),
    )

    result = await runner._handle_goal_command(event)

    assert "No active goal" in result or "No goal" in result
    assert adapter._post_delivery_callbacks == {}
    goals._DB_CACHE.clear()

@pytest.mark.asyncio
async def test_gateway_goal_status_clears_stale_oneshot_post_delivery_callback(tmp_path: Path, monkeypatch):
    """/goal status must be native and must not flush stale one-shot docs/kickoff callbacks."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_cli import goals
    goals._DB_CACHE.clear()

    session_id = "sid-status-stale-callback"
    goals.GoalManager(session_id, default_max_turns=250).set(
        "Continue project",
        goal_mode="goal_prompt_oneshot",
        goal_prompt_path=str(tmp_path / "docs" / "runbooks" / "GOAL_PROMPT.md"),
        compaction_refresh_interval=5,
    )

    runner = object.__new__(GatewayRunner)
    runner.config = {"goals": {"oneshot_max_turns": 250, "oneshot_compaction_refresh_interval": 5}}
    runner.session_store = SimpleNamespace(
        get_or_create_session=lambda _source: SimpleNamespace(session_id=session_id)
    )

    def stale_goal_callback():
        raise AssertionError("stale callback should have been cleared")

    stale_goal_callback._hermes_goal_prompt_oneshot = True

    class FakeAdapter:
        def __init__(self):
            self._pending_messages = {}
            self._post_delivery_callbacks = {"session-key": (17, stale_goal_callback)}

    adapter = FakeAdapter()
    runner.adapters = {"telegram": adapter}
    runner._session_key_for_source = lambda _source: "session-key"

    event = MessageEvent(
        text="/goal status",
        message_type=MessageType.TEXT,
        source=SimpleNamespace(platform="telegram", chat_id="123"),
    )

    result = await runner._handle_goal_command(event)

    assert "Goal" in result
    assert "GOAL_PROMPT" not in result
    assert adapter._post_delivery_callbacks == {}
    goals._DB_CACHE.clear()


def test_goal_continuation_event_recognizes_bare_oneshot_loader():
    runner = object.__new__(GatewayRunner)

    assert runner._is_goal_continuation_event("/goal_prompt_oneshot") is True
    assert runner._is_goal_continuation_event("/goal_prompt_oneshot /tmp/project") is True
