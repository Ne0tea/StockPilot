from pathlib import Path
import importlib
import sys
import types

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_interactive_with_stubs():
    sdk = types.ModuleType("claude_agent_sdk")
    sdk.ClaudeAgentOptions = object
    sdk.ClaudeSDKClient = object
    sdk.PermissionResultAllow = object
    sdk.PermissionResultDeny = object
    sdk.ToolPermissionContext = object
    types_mod = types.ModuleType("claude_agent_sdk.types")
    types_mod.AssistantMessage = object
    types_mod.ResultMessage = object
    types_mod.StreamEvent = object
    types_mod.TextBlock = object
    sys.modules.setdefault("claude_agent_sdk", sdk)
    sys.modules.setdefault("claude_agent_sdk.types", types_mod)
    return importlib.import_module("core.interactive")


def test_start_session_rolls_back_in_memory_registration_on_persist_failure(monkeypatch):
    interactive = _load_interactive_with_stubs()
    interactive._active_sessions.clear()

    class _DummySession:
        def __init__(self, code, name, auto_respond=False):
            self.code = code
            self.name = name
            self.auto_respond = auto_respond
            self.is_running = True

    monkeypatch.setattr(interactive, "acquire_analysis_start_slot", lambda: True)
    monkeypatch.setattr(interactive, "release_analysis_start_slot", lambda: None)
    monkeypatch.setattr(interactive, "is_reset_in_progress", lambda: False)
    monkeypatch.setattr(interactive, "InteractiveSession", _DummySession)
    monkeypatch.setattr(interactive, "_persist_interactive_status", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db locked")))

    with pytest.raises(RuntimeError, match="db locked"):
        interactive.start_session("600089", "特变电工", auto_respond=True)

    assert "600089" not in interactive._active_sessions
