import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
CORE_DIR = BACKEND_DIR / "core"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

if "markdown2" not in sys.modules:
    markdown2_stub = types.ModuleType("markdown2")
    markdown2_stub.markdown = lambda text, *args, **kwargs: text
    sys.modules["markdown2"] = markdown2_stub

WECHAT_SENDER_PATH = CORE_DIR / "src" / "notification_sender" / "wechat_sender.py"
WECHAT_SENDER_SPEC = importlib.util.spec_from_file_location("test_wechat_sender_module", WECHAT_SENDER_PATH)
WECHAT_SENDER_MODULE = importlib.util.module_from_spec(WECHAT_SENDER_SPEC)
assert WECHAT_SENDER_SPEC and WECHAT_SENDER_SPEC.loader
WECHAT_SENDER_SPEC.loader.exec_module(WECHAT_SENDER_MODULE)
WechatSender = WECHAT_SENDER_MODULE.WechatSender


def _build_sender(msg_type: str) -> WechatSender:
    return WechatSender(
        SimpleNamespace(
            wechat_webhook_url="https://example.com/webhook",
            wechat_max_bytes=4000,
            wechat_msg_type=msg_type,
            webhook_verify_ssl=True,
        )
    )


def test_gen_wechat_payload_uses_text_block_for_text_type():
    sender = _build_sender("text")

    payload = sender._gen_wechat_payload("hello")

    assert payload == {
        "msgtype": "text",
        "text": {
            "content": "hello",
        },
    }


def test_gen_wechat_payload_uses_markdown_block_for_markdown_type():
    sender = _build_sender("markdown")

    payload = sender._gen_wechat_payload("## hello")

    assert payload == {
        "msgtype": "markdown",
        "markdown": {
            "content": "## hello",
        },
    }


def test_gen_wechat_payload_uses_markdown_v2_block_for_markdown_v2_type():
    sender = _build_sender("markdown_v2")

    payload = sender._gen_wechat_payload("## hello v2")

    assert payload == {
        "msgtype": "markdown_v2",
        "markdown_v2": {
            "content": "## hello v2",
        },
    }
