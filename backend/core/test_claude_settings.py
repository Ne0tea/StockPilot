from types import SimpleNamespace

from core.claude_settings import build_claude_settings_payload


def test_api_key_with_blank_auth_token_explicitly_overrides_user_token():
    payload = build_claude_settings_payload(
        SimpleNamespace(
            claude_model="",
            claude_api_key="sk-new-key",
            claude_auth_token="",
            claude_base_url="",
        )
    )

    assert payload == {
        "env": {
            "ANTHROPIC_API_KEY": "sk-new-key",
            "ANTHROPIC_AUTH_TOKEN": "",
        }
    }


def test_auth_token_is_preserved_when_configured():
    payload = build_claude_settings_payload(
        SimpleNamespace(
            claude_model="",
            claude_api_key="",
            claude_auth_token="token-for-gateway",
            claude_base_url="",
        )
    )

    assert payload["env"] == {
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "token-for-gateway",
    }
