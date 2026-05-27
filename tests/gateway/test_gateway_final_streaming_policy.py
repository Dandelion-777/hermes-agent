"""Gateway final-response delivery policy tests.

Telegram/gateway should keep tool-call progress streaming available without
streaming the final assistant prose into chat. Final replies should return to
the normal paginated send path so /goal_prompt_oneshot continuation hooks see a
regular delivery boundary.
"""

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig, Platform, PlatformConfig, StreamingConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.session import SessionSource


class _RecordingAdapter(BasePlatformAdapter):
    SUPPORTS_MESSAGE_EDITING = True

    def __init__(self):
        super().__init__(PlatformConfig(enabled=True), Platform.TELEGRAM)
        self.sends = []
        self.edits = []

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        self.sends.append({"chat_id": chat_id, "content": content, "reply_to": reply_to, "metadata": metadata})
        return SendResult(success=True, message_id=f"send-{len(self.sends)}")

    async def edit_message(self, chat_id, message_id, content, **kwargs) -> SendResult:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "content": content, "kwargs": kwargs})
        return SendResult(success=True, message_id=message_id)

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


class _StreamingProbeAgent:
    last_instance = None

    def __init__(self, *args, **kwargs):
        type(self).last_instance = self
        self.tools = []
        self.model = kwargs.get("model") or "test-model"
        self.session_id = kwargs.get("session_id") or "session-1"
        self.stream_delta_callback = None
        self.interim_assistant_callback = None
        self.tool_progress_callback = None
        self.step_callback = None
        self.status_callback = None
        self.reasoning_config = None
        self.service_tier = None
        self.request_overrides = {}
        self.saw_stream_callback = False

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        if self.stream_delta_callback is not None:
            self.saw_stream_callback = True
            # This simulates provider token streaming. The gateway must not send
            # this prose to Telegram; it only needs the streaming API active so
            # tool-call generation callbacks can fire.
            self.stream_delta_callback("Final answer that should be paginated later")
        if self.tool_progress_callback is not None:
            self.tool_progress_callback("tool.started", "terminal", preview="pytest")
        return {
            "final_response": "Final answer that should be paginated later",
            "messages": [
                {"role": "user", "content": str(user_message)},
                {"role": "assistant", "content": "Final answer that should be paginated later"},
            ],
            "api_calls": 1,
        }


def _make_runner(adapter):
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner.config = GatewayConfig(streaming=StreamingConfig(enabled=True, transport="edit"))
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._session_reasoning_overrides = {}
    runner._show_reasoning = False
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._running_agents = {}
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.hooks.loaded_hooks = []
    runner._session_db = None
    runner._draining = False
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    return runner


@pytest.mark.asyncio
async def test_gateway_keeps_tool_streaming_but_does_not_stream_final_text(monkeypatch):
    adapter = _RecordingAdapter()
    runner = _make_runner(adapter)
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="chat-1",
        chat_name="Telegram",
        chat_type="group",
        user_id="user-1",
    )

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _StreamingProbeAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    monkeypatch.setattr(gateway_run, "_reload_runtime_env_preserving_config_authority", lambda: None)
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {
            "display": {
                "platforms": {
                    "telegram": {
                        "streaming": True,
                        "tool_progress": "all",
                        "interim_assistant_messages": False,
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
        },
    )

    result = await runner._run_agent(
        message="do work",
        context_prompt="",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:telegram:chat-1",
        run_generation=None,
        event_message_id="msg-1",
    )

    assert _StreamingProbeAgent.last_instance.saw_stream_callback is True
    assert result["final_response"] == "Final answer that should be paginated later"
    assert not result.get("already_sent"), "final prose must return to normal paginated gateway delivery"
    assert all("Final answer that should be paginated later" not in send["content"] for send in adapter.sends)
    assert adapter.edits == []
