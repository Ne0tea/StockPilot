import json
from pathlib import Path
from typing import Any, Dict


CLAUDE_SETTINGS_PATH = (
    Path(__file__).resolve().parents[1] / "reports" / ".claude" / "settings.json"
)


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def build_claude_settings_payload(settings_row: Any) -> Dict[str, Any]:
    model = _clean_str(getattr(settings_row, "claude_model", ""))
    api_key = _clean_str(getattr(settings_row, "claude_api_key", ""))
    auth_token = _clean_str(getattr(settings_row, "claude_auth_token", ""))
    base_url = _clean_str(getattr(settings_row, "claude_base_url", ""))

    env: Dict[str, str] = {}
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    if auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = auth_token
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url

    payload: Dict[str, Any] = {}
    if model:
        payload["model"] = model
    if env:
        payload["env"] = env
    return payload


def sync_claude_settings_file(settings_row: Any) -> None:
    payload = build_claude_settings_payload(settings_row)
    settings_path = CLAUDE_SETTINGS_PATH

    if not payload:
        try:
            settings_path.unlink()
        except FileNotFoundError:
            pass
        return

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
