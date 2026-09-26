"""Read/write OpenCode global config (``~/.config/opencode/opencode.jsonc``).

The settings page persists one ``provider`` entry into this file. Other
sections (``plugin``, ``lsp``, ``small_model`` …) are preserved untouched.

OpenCode config is JSONC (JSON with ``//`` line comments). We strip comments
on read and write back as plain JSON — comments are non-functional and are
lost on save, which is an acceptable trade-off for our use case.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


OPENCODE_CONFIG_PATH = Path.home() / ".config" / "opencode" / "opencode.jsonc"

# Known provider presets. ``custom`` is a placeholder for any user-supplied
# OpenAI/Anthropic-compatible gateway (e.g. kuaipao.pro) that needs baseURL
# and apiKey explicitly configured.
PROVIDER_PRESETS = (
    {
        "value": "opencode-go",
        "label": "opencode-go (Coding Plan 订阅)",
        "hint": "走 opencode-go 计费，无需填写 API Key",
    },
    {
        "value": "anthropic",
        "label": "anthropic (Anthropic 官方/兼容网关)",
        "hint": "需要 Base URL + API Key",
    },
    {
        "value": "openai",
        "label": "openai (OpenAI 官方/兼容网关)",
        "hint": "需要 Base URL + API Key",
    },
    {
        "value": "custom",
        "label": "custom (自定义 provider)",
        "hint": "需要 Base URL + API Key",
    },
)


_LINE_COMMENT_RE = re.compile(r"^\s*//.*$")


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _strip_jsonc(text: str) -> str:
    """Strip JSONC-style ``// line comments`` while keeping string contents.

    Only handles single-line comments; the project's ``opencode.jsonc`` does
    not use block comments or ``//`` inside string values.
    """
    out_lines = []
    for line in text.splitlines():
        stripped = _LINE_COMMENT_RE.match(line)
        if stripped is not None:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _read_config() -> Dict[str, Any]:
    if not OPENCODE_CONFIG_PATH.exists():
        return {}
    try:
        raw = OPENCODE_CONFIG_PATH.read_text(encoding="utf-8")
        return json.loads(_strip_jsonc(raw)) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(config: Dict[str, Any]) -> None:
    OPENCODE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENCODE_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _split_model_id(model_id: str) -> tuple[str, str]:
    """``opencode-go/minimax-m3`` → ``(opencode-go, minimax-m3)``."""
    if "/" in model_id:
        provider, model = model_id.split("/", 1)
        return provider.strip(), model.strip()
    return "", model_id.strip()


def build_provider_payload(settings_row: Any) -> Optional[Dict[str, Any]]:
    """Build the ``provider`` section that should be merged into opencode.jsonc."""
    provider_id = _clean_str(getattr(settings_row, "opencode_provider", ""))
    model_id = _clean_str(getattr(settings_row, "opencode_model", ""))
    api_key = _clean_str(getattr(settings_row, "opencode_api_key", ""))
    base_url = _clean_str(getattr(settings_row, "opencode_base_url", ""))

    if not any((provider_id, model_id, api_key, base_url)):
        return None

    if not provider_id:
        provider_id = "opencode-go"

    provider_cfg: Dict[str, Any] = {}

    options: Dict[str, Any] = {}
    if base_url:
        options["baseURL"] = base_url
    if api_key:
        options["apiKey"] = api_key
    if options:
        provider_cfg["options"] = options

    if model_id:
        _, model_short = _split_model_id(model_id)
        if model_short:
            provider_cfg.setdefault("models", {})[model_short] = {
                "name": model_id,
            }

    return {provider_id: provider_cfg}


def merge_provider(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge incoming provider config into existing without losing fields."""
    merged_options = dict(existing.get("options", {}))
    merged_options.update(incoming.get("options", {}))
    if merged_options:
        existing["options"] = merged_options

    merged_models = dict(existing.get("models", {}))
    merged_models.update(incoming.get("models", {}))
    if merged_models:
        existing["models"] = merged_models

    if "name" in incoming and incoming["name"]:
        existing["name"] = incoming["name"]

    return existing


def sync_opencode_config(settings_row: Any) -> None:
    """Merge ``provider.<opencode_provider>`` into opencode.jsonc.

    A no-op when the row has no opencode_* values populated — this avoids
    wiping existing provider entries (e.g. ``anthropic`` already configured
    by hand) when the user simply hasn't touched the new fields yet.
    """
    payload = build_provider_payload(settings_row)
    if payload is None:
        return

    config = _read_config()
    providers = config.setdefault("provider", {})
    for provider_id, provider_cfg in payload.items():
        existing = providers.get(provider_id, {})
        providers[provider_id] = merge_provider(existing, provider_cfg)
    _write_config(config)


def clear_opencode_provider(provider_id: str) -> None:
    """Remove a single provider entry from opencode.jsonc (used by tests/CLI)."""
    if not provider_id:
        return
    config = _read_config()
    providers = config.get("provider", {})
    providers.pop(provider_id, None)
    if providers:
        config["provider"] = providers
    else:
        config.pop("provider", None)
    _write_config(config)
