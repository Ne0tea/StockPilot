import asyncio
import threading
import time
from datetime import datetime, timedelta

import pytest

from backend.core.agent_stream_session import (
    MAX_CRITICAL_EVENTS,
    MAX_EVENT_BUFFER_BYTES,
    MAX_PROGRESS_EVENTS,
    AgentRunSession,
)


def _session() -> AgentRunSession:
    return AgentRunSession(
        session_id="agent-test",
        run_id="run-test",
        stock_code="000001",
        skill="specialist",
        background_prompt="test prompt",
    )


def test_event_history_is_bounded_and_preserves_semantic_events():
    session = _session()
    session.publish({"type": "prompt", "text": "prompt"})
    for index in range(10_000):
        session.publish({"type": "status", "text": f"progress-{index}"})
    session.publish({"type": "question", "text": "继续吗？"})
    session.publish({"type": "user-response", "text": "继续"})
    session.publish({"type": "output", "text": "中间输出"})
    session.publish({"type": "heartbeat"})
    assert session.finish(status="done", text="完成", final_result="最终报告")
    assert not session.finish(status="error", text="重复终态")

    events = session.snapshot_events()
    assert session.event_buffer_bytes <= MAX_EVENT_BUFFER_BYTES
    assert sum(event["type"] == "status" for event in events) <= MAX_PROGRESS_EVENTS
    assert all(event["type"] != "heartbeat" for event in events)
    assert sum(event["type"] == "session_end" for event in events) == 1
    assert sum(event["type"] == "final_result" for event in events) == 1
    assert {"prompt", "question", "user-response", "output"}.issubset(
        {event["type"] for event in events}
    )
    event_ids = [event["event_id"] for event in events]
    assert event_ids == sorted(event_ids)
    assert len(event_ids) == len(set(event_ids))


def test_large_key_events_still_respect_total_byte_limit():
    session = _session()
    session.publish({"type": "output", "text": "x" * (3 * 1024 * 1024)})
    assert session.finish(
        status="done",
        text="y" * (3 * 1024 * 1024),
        final_result="z" * (3 * 1024 * 1024),
    )
    events = session.snapshot_events()
    assert session.event_buffer_bytes <= MAX_EVENT_BUFFER_BYTES
    assert {"output", "final_result", "session_end"}.issubset(
        {event["type"] for event in events}
    )
    assert all(event.get("truncated") for event in events)


def test_critical_history_is_bounded_without_dropping_latest_semantics():
    session = _session()
    session.publish({"type": "prompt", "text": "prompt"})
    for index in range(10_000):
        session.publish({"type": "diagnostic", "code": "progress", "text": str(index)})
    events = session.snapshot_events()
    assert sum(event["type"] == "diagnostic" for event in events) <= MAX_CRITICAL_EVENTS
    assert events[-1]["text"] == "9999"
    assert any(event["type"] == "prompt" for event in events)


def test_stage_and_tool_history_is_coalesced():
    session = _session()
    session.publish({"type": "stage", "stage": "research", "status": "started"})
    session.publish({"type": "stage", "stage": "research", "status": "completed"})
    session.publish({"type": "tool", "tool": "quote", "status": "started"})
    session.publish({"type": "tool", "tool": "quote", "status": "completed"})

    events = session.snapshot_events()
    assert [event["status"] for event in events if event["type"] == "stage"] == ["completed"]
    assert [event["status"] for event in events if event["type"] == "tool"] == ["completed"]


def test_attach_replay_has_no_duplicate_live_event():
    async def scenario():
        session = _session()
        first_id = session.publish({"type": "status", "text": "before"})
        second_id = session.publish({"type": "status", "text": "before-2"})
        loop = asyncio.get_running_loop()
        replay = session.attach_loop(loop, after_event_id=first_id)
        replay_ids = [event["event_id"] for event in replay]
        live_id = session.publish({"type": "status", "text": "after"})
        await asyncio.sleep(0)
        live = await session.get_event(timeout=0.1)
        assert replay_ids == [second_id]
        assert live["event_id"] == live_id
        assert live["text"] == "after"
        session.detach_loop(loop)

    asyncio.run(scenario())


def test_stale_connection_generation_cannot_detach_new_connection():
    async def scenario():
        session = _session()
        loop = asyncio.get_running_loop()
        session.attach_loop(loop)
        old_generation = session.connection_generation
        session.detach_loop_for_generation(old_generation)
        session.attach_loop(loop)
        new_generation = session.connection_generation
        assert new_generation != old_generation
        assert await session.get_event(timeout=0.01, generation=old_generation) is None
        session.detach_loop_for_generation(old_generation)
        assert session.connection_generation == new_generation
        session.detach_loop_for_generation(new_generation)

    asyncio.run(scenario())


def test_attached_finish_delivers_exactly_one_terminal_event():
    async def scenario():
        session = _session()
        loop = asyncio.get_running_loop()
        session.attach_loop(loop)
        session.publish({"type": "status", "text": "running"})
        assert session.finish(status="done", text="完成", final_result="报告")
        await asyncio.sleep(0)
        events = []
        while True:
            event = await session.get_event(timeout=0.1)
            if event is None:
                break
            events.append(event)
            if event["type"] == "session_end":
                break
        assert sum(event["type"] == "session_end" for event in events) == 1
        assert sum(event["type"] == "final_result" for event in events) == 1
        session.detach_loop(loop)

    asyncio.run(scenario())


def test_pending_dispatcher_and_queue_remain_bounded():
    async def scenario():
        session = _session()
        loop = asyncio.get_running_loop()
        session.attach_loop(loop)
        for index in range(10_000):
            session.publish({"type": "status", "text": str(index)})
        assert len(session._pending) <= 256
        await asyncio.sleep(0)
        assert session.queue_size <= 256
        session.detach_loop(loop)

    asyncio.run(scenario())


def test_executor_cleanup_is_fenced_by_run_id(monkeypatch):
    import sys
    import types
    if 'dotenv' not in sys.modules:
        dotenv_stub = types.ModuleType('dotenv')
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
        monkeypatch.setitem(sys.modules, 'dotenv', dotenv_stub)
    import backend.core.agent_runtime as runtime

    class DummyExecutor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    created = []

    def build(*args, **kwargs):
        executor = DummyExecutor()
        created.append(executor)
        return executor

    monkeypatch.setattr(runtime, "build_agent_executor", build)
    monkeypatch.setattr(runtime, "get_config", lambda: object())
    monkeypatch.setattr(runtime, "_ensure_housekeeping", lambda: None)
    monkeypatch.setattr(runtime, "_executors", {})
    monkeypatch.setattr(runtime, "_executor_meta", {})

    executor = runtime.get_or_create_executor("session", "skill", run_id="old")
    runtime.release_executor("session", run_id="old")
    assert runtime.get_or_create_executor("session", "skill", run_id="new") is executor

    runtime.release_executor("session", run_id="old")
    assert runtime._executor_meta["session"]["active_runs"] == {"new"}
    with pytest.raises(RuntimeError):
        runtime.get_or_create_executor("session", "skill", run_id="other")

    runtime.release_executor("session", run_id="new")
    runtime.drop_executor("session", run_id="new")
    assert executor.closed
    assert len(created) == 1


def test_completed_session_can_restart_without_old_run_cleanup(monkeypatch):
    import backend.core.agent_runtime as runtime

    class DummyExecutor:
        def __init__(self):
            self.calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            return type("Result", (), {"success": True, "content": f"result-{self.calls}"})()

    executor = DummyExecutor()
    monkeypatch.setattr(runtime, "build_agent_executor", lambda *args, **kwargs: executor)
    monkeypatch.setattr(runtime, "get_config", lambda: object())
    monkeypatch.setattr(runtime, "_ensure_housekeeping", lambda: None)
    monkeypatch.setattr(runtime, "_stream_sessions", {})
    monkeypatch.setattr(runtime, "_executors", {})
    monkeypatch.setattr(runtime, "_executor_meta", {})
    monkeypatch.setattr(runtime, "_accepting", True)

    first = runtime.start_stream_session(
        session_id="restart-session",
        stock_code="000001",
        stock_name="test",
        skill="specialist",
        background_prompt="prompt",
    )
    assert runtime.wait_for_agent_runtime(timeout=1.0)
    assert runtime._stream_sessions["restart-session"].is_finished

    second = runtime.start_stream_session(
        session_id="restart-session",
        stock_code="000001",
        stock_name="test",
        skill="specialist",
        background_prompt="prompt",
    )
    assert first["run_id"] != second["run_id"]
    assert second["ok"]
    assert runtime.wait_for_agent_runtime(timeout=1.0)
    assert runtime._stream_sessions["restart-session"].status == "done"
    assert executor.calls == 2


def test_runner_exception_converges_to_one_terminal_event(monkeypatch):
    import backend.core.agent_runtime as runtime

    class FailingExecutor:
        def chat(self, **kwargs):
            raise RuntimeError("synthetic failure")

    monkeypatch.setattr(runtime, "build_agent_executor", lambda *args, **kwargs: FailingExecutor())
    monkeypatch.setattr(runtime, "get_config", lambda: object())
    monkeypatch.setattr(runtime, "_ensure_housekeeping", lambda: None)
    monkeypatch.setattr(runtime, "_stream_sessions", {})
    monkeypatch.setattr(runtime, "_executors", {})
    monkeypatch.setattr(runtime, "_executor_meta", {})
    monkeypatch.setattr(runtime, "_accepting", True)

    response = runtime.start_stream_session(
        session_id="exception-session",
        stock_code="000001",
        stock_name="test",
        skill="specialist",
        background_prompt="prompt",
    )
    assert response["ok"]
    assert runtime.wait_for_agent_runtime(timeout=1.0)
    session = runtime._stream_sessions["exception-session"]
    events = session.snapshot_events()
    assert session.status == "error"
    assert sum(event["type"] == "session_end" for event in events) == 1
    assert sum(event.get("code") == "executor_error" for event in events) == 1


def test_explicit_cancel_waits_for_executor_and_converges(monkeypatch):
    import backend.core.agent_runtime as runtime

    release_chat = threading.Event()

    class BlockingExecutor:
        def chat(self, **kwargs):
            release_chat.wait(timeout=1.0)
            return type("Result", (), {"success": True, "content": "late result"})()

    monkeypatch.setattr(runtime, "build_agent_executor", lambda *args, **kwargs: BlockingExecutor())
    monkeypatch.setattr(runtime, "get_config", lambda: object())
    monkeypatch.setattr(runtime, "_ensure_housekeeping", lambda: None)
    monkeypatch.setattr(runtime, "_stream_sessions", {})
    monkeypatch.setattr(runtime, "_executors", {})
    monkeypatch.setattr(runtime, "_executor_meta", {})
    monkeypatch.setattr(runtime, "_accepting", True)

    runtime.start_stream_session(
        session_id="cancel-session",
        stock_code="000001",
        stock_name="test",
        skill="specialist",
        background_prompt="prompt",
    )
    deadline = time.monotonic() + 1.0
    while "cancel-session" not in runtime._stream_sessions and time.monotonic() < deadline:
        time.sleep(0.01)
    session = runtime._stream_sessions["cancel-session"]
    runtime.end_stream_session("cancel-session")
    assert session.status == "cancelling"
    assert not session.is_finished
    release_chat.set()
    assert runtime.wait_for_agent_runtime(timeout=1.0)
    events = session.snapshot_events()
    assert session.status == "cancelled"
    assert sum(event["type"] == "session_end" for event in events) == 1
    assert sum(event.get("code") == "cancelled" for event in events) == 1


def test_terminal_sessions_are_reaped_by_ttl_and_count(monkeypatch):
    from datetime import datetime, timedelta

    import backend.core.agent_runtime as runtime

    now = datetime.now()
    stale = _session()
    stale.is_finished = True
    stale.finished_at = (
        now - timedelta(seconds=runtime._TERMINAL_SESSION_TTL_SECONDS + 1)
    ).isoformat()
    active = _session()
    sessions = {"stale": stale, "active": active}
    for index in range(runtime._MAX_TERMINAL_SESSIONS + 1):
        item = _session()
        item.is_finished = True
        item.finished_at = (now - timedelta(seconds=index + 1)).isoformat()
        sessions[f"finished-{index}"] = item

    monkeypatch.setattr(runtime, "_stream_sessions", sessions)
    monkeypatch.setattr(runtime, "_executor_meta", {})
    monkeypatch.setattr(runtime, "_executors", {})
    assert runtime.reap_agent_sessions(now=now) >= 2
    assert "stale" not in runtime._stream_sessions
    assert "active" in runtime._stream_sessions
    assert sum(
        item.is_finished for item in runtime._stream_sessions.values()
    ) <= runtime._MAX_TERMINAL_SESSIONS
