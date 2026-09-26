"""Unit tests for ``core.opencode_settings`` — runs without SQLAlchemy.

Covers payload construction, JSONC parsing, and merge semantics against
``~/.config/opencode/opencode.jsonc``.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from core.opencode_settings import (
    OPENCODE_CONFIG_PATH,
    build_provider_payload,
    clear_opencode_provider,
    merge_provider,
    sync_opencode_config,
)


class FakeSettings:
    opencode_provider = ""
    opencode_model = ""
    opencode_api_key = ""
    opencode_base_url = ""


def test_empty_row_returns_none_payload():
    assert build_provider_payload(FakeSettings()) is None


def test_opencode_go_preset_emits_no_options():
    row = FakeSettings()
    row.opencode_provider = "opencode-go"
    row.opencode_model = "opencode-go/minimax-m3"
    payload = build_provider_payload(row)
    assert "opencode-go" in payload
    assert "options" not in payload["opencode-go"]
    assert payload["opencode-go"]["models"] == {
        "minimax-m3": {"name": "opencode-go/minimax-m3"}
    }


def test_anthropic_with_custom_gateway():
    row = FakeSettings()
    row.opencode_provider = "anthropic"
    row.opencode_model = "anthropic/claude-sonnet-4-6"
    row.opencode_api_key = "sk-test"
    row.opencode_base_url = "https://kuaipao.pro"
    payload = build_provider_payload(row)
    assert payload["anthropic"]["options"] == {
        "baseURL": "https://kuaipao.pro",
        "apiKey": "sk-test",
    }
    assert "claude-sonnet-4-6" in payload["anthropic"]["models"]


def test_round_trip_preserves_existing_keys():
    """Adding opencode-go must not delete plugin/lsp/other providers."""
    backup = OPENCODE_CONFIG_PATH.read_text(encoding="utf-8") if OPENCODE_CONFIG_PATH.exists() else None
    try:
        seed = '''{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-mem", "./plugins/chinese-mode.ts"],
  "lsp": true,
  "provider": {
    "anthropic": {
      "options": {"baseURL": "https://api.anthropic.com", "apiKey": "sk-existing"},
      "models": {"claude-opus-4-6": {"name": "Claude Opus 4.6"}}
    }
  }
}
'''
        OPENCODE_CONFIG_PATH.write_text(seed, encoding="utf-8")

        row = FakeSettings()
        row.opencode_provider = "opencode-go"
        row.opencode_model = "opencode-go/minimax-m3"
        sync_opencode_config(row)

        cfg = json.loads(OPENCODE_CONFIG_PATH.read_text(encoding="utf-8"))
        assert cfg["plugin"] == ["opencode-mem", "./plugins/chinese-mode.ts"]
        assert cfg["lsp"] is True
        assert cfg["provider"]["anthropic"]["options"]["apiKey"] == "sk-existing"
        assert "claude-opus-4-6" in cfg["provider"]["anthropic"]["models"]
        assert "minimax-m3" in cfg["provider"]["opencode-go"]["models"]
    finally:
        if backup is not None:
            OPENCODE_CONFIG_PATH.write_text(backup, encoding="utf-8")
        elif OPENCODE_CONFIG_PATH.exists():
            OPENCODE_CONFIG_PATH.unlink()


def test_update_anthropic_overrides_options_merges_models():
    backup = OPENCODE_CONFIG_PATH.read_text(encoding="utf-8") if OPENCODE_CONFIG_PATH.exists() else None
    try:
        seed = '''{
  "provider": {
    "anthropic": {
      "options": {"baseURL": "https://api.anthropic.com", "apiKey": "sk-old"},
      "models": {"claude-opus-4-6": {"name": "Opus 4.6"}}
    }
  }
}
'''
        OPENCODE_CONFIG_PATH.write_text(seed, encoding="utf-8")

        row = FakeSettings()
        row.opencode_provider = "anthropic"
        row.opencode_model = "anthropic/claude-sonnet-4-6"
        row.opencode_base_url = "https://kuaipao.pro"
        row.opencode_api_key = "sk-newkey"
        sync_opencode_config(row)

        cfg = json.loads(OPENCODE_CONFIG_PATH.read_text(encoding="utf-8"))
        assert cfg["provider"]["anthropic"]["options"]["baseURL"] == "https://kuaipao.pro"
        assert cfg["provider"]["anthropic"]["options"]["apiKey"] == "sk-newkey"
        assert "claude-opus-4-6" in cfg["provider"]["anthropic"]["models"]
        assert "claude-sonnet-4-6" in cfg["provider"]["anthropic"]["models"]
    finally:
        if backup is not None:
            OPENCODE_CONFIG_PATH.write_text(backup, encoding="utf-8")
        elif OPENCODE_CONFIG_PATH.exists():
            OPENCODE_CONFIG_PATH.unlink()


def test_empty_payload_is_no_op():
    backup = OPENCODE_CONFIG_PATH.read_text(encoding="utf-8") if OPENCODE_CONFIG_PATH.exists() else None
    try:
        seed = '{"provider": {"anthropic": {"options": {"apiKey": "sk-x"}}}}'
        OPENCODE_CONFIG_PATH.write_text(seed, encoding="utf-8")

        sync_opencode_config(FakeSettings())
        cfg = json.loads(OPENCODE_CONFIG_PATH.read_text(encoding="utf-8"))
        assert "anthropic" in cfg["provider"]
    finally:
        if backup is not None:
            OPENCODE_CONFIG_PATH.write_text(backup, encoding="utf-8")
        elif OPENCODE_CONFIG_PATH.exists():
            OPENCODE_CONFIG_PATH.unlink()


def test_clear_opencode_provider_removes_only_target():
    # Build a fake opencode.jsonc with two providers
    OPENCODE_CONFIG_PATH.write_text(
        '{"provider": {"opencode-go": {"models": {"minimax-m3": {"name": "x"}}}, '
        '"anthropic": {"options": {"apiKey": "sk-x"}}}}',
        encoding="utf-8",
    )
    try:
        clear_opencode_provider("opencode-go")
        cfg = json.loads(OPENCODE_CONFIG_PATH.read_text(encoding="utf-8"))
        assert "opencode-go" not in cfg["provider"]
        assert "anthropic" in cfg["provider"]
        assert cfg["provider"]["anthropic"]["options"]["apiKey"] == "sk-x"
    finally:
        if OPENCODE_CONFIG_PATH.exists():
            OPENCODE_CONFIG_PATH.unlink()


def test_merge_provider_combines_options_and_models():
    existing = {"options": {"baseURL": "https://a"}, "models": {"x": {"name": "X"}}}
    incoming = {"options": {"apiKey": "sk-y"}, "models": {"y": {"name": "Y"}}}
    merged = merge_provider(existing, incoming)
    assert merged["options"]["baseURL"] == "https://a"
    assert merged["options"]["apiKey"] == "sk-y"
    assert "x" in merged["models"]
    assert "y" in merged["models"]
