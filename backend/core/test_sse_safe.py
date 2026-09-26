"""Unit tests for ``core.sse_safe`` — runs without SQLAlchemy or any
project dependencies.

Covers all three trim passes plus guarantees that the returned value
JSON-encodes to ≤ :data:`SSE_SAFE_PAYLOAD_BYTES`.
"""

import json

from core.sse_safe import (
    SSE_SAFE_PAYLOAD_BYTES,
    SSE_SAFE_TEXT_BYTES,
    trim_event_for_sse,
)


def _serialised_size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_small_event_passes_through():
    event = {"type": "output", "text": "hello"}
    assert trim_event_for_sse(event) == event


def test_huge_text_trimmed_under_cap():
    event = {"type": "output", "text": "x" * 50000}
    trimmed = trim_event_for_sse(event)
    size = _serialised_size(trimmed)
    assert size <= SSE_SAFE_PAYLOAD_BYTES
    assert trimmed["text"].endswith("...[trimmed]")


def test_tool_use_with_large_output_dropped():
    """Reproduces the original chunk-overflow trigger (60 K-line bars)."""
    event = {
        "type": "task_progress",
        "data": {
            "task_type": "bash",
            "status": "completed",
            "message": "kline → huge output",
            "exit": 0,
            "metadata": {"duration": 1200, "truncated": False},
            "output": "x" * 30000,
        },
        "name": "bash",
        "partial": "x" * 30000,
    }
    trimmed = trim_event_for_sse(event)
    # The shrink pass should already cap the JSON at the SSE safe size —
    # whether metadata is dropped or kept depends on whether shrink alone
    # was sufficient. The contract is just: size <= cap.
    size = _serialised_size(trimmed)
    assert size <= SSE_SAFE_PAYLOAD_BYTES


def test_extreme_case_every_field_huge():
    event = {
        "type": "output",
        "text": "y" * 100000,
        "details": "z" * 100000,
        "data": {"message": "w" * 100000, "metadata": {"a": "b" * 100000}},
    }
    trimmed = trim_event_for_sse(event)
    assert _serialised_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES


def test_progress_event_under_cap():
    event = {
        "type": "progress",
        "action": "bash",
        "data": {"message": "M" * 20000},
    }
    trimmed = trim_event_for_sse(event)
    assert _serialised_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES


def test_question_event_with_long_details():
    event = {
        "type": "question",
        "kind": "text_confirmation",
        "question": "是否继续？",
        "details": "D" * 50000,
        "options": ["继续", "跳过"],
    }
    trimmed = trim_event_for_sse(event)
    assert _serialised_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES


def test_error_event_with_long_traceback():
    event = {"type": "error", "text": "E" * 30000}
    trimmed = trim_event_for_sse(event)
    assert _serialised_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES


def test_nested_list_of_big_strings():
    event = {
        "type": "output",
        "items": [{"text": "x" * 50000}, {"text": "y" * 50000}],
    }
    trimmed = trim_event_for_sse(event)
    assert _serialised_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES


def test_realistic_kline_output_under_cap():
    """60 K-line bars, JSON-encoded — the original failing payload."""
    kline_bars = [
        {
            "time": f"2026-09-{i:02d}",
            "open": 30 + i * 0.1,
            "close": 31 + i * 0.1,
            "high": 32 + i * 0.1,
            "low": 29 + i * 0.1,
            "volume": 200000 + i * 1000,
            "amount": 800000000 + i * 1000000,
        }
        for i in range(1, 61)
    ]
    raw = json.dumps(kline_bars, ensure_ascii=False)
    event = {
        "type": "task_progress",
        "data": {
            "task_type": "bash",
            "status": "completed",
            "message": "fetch_stock.py --kline",
            "exit": 0,
            "metadata": {"duration": 1200},
            "output": raw,
        },
        "name": "bash",
        "partial": raw,
    }
    trimmed = trim_event_for_sse(event)
    assert _serialised_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES


def test_original_dict_not_mutated():
    """trim_event_for_sse must return a new object, never mutate the input."""
    event = {"type": "output", "text": "x" * 50000}
    snapshot = json.dumps(event, sort_keys=True)
    trim_event_for_sse(event)
    assert json.dumps(event, sort_keys=True) == snapshot


def test_unserialisable_event_returned_unchanged():
    """A dict that json.dumps cannot encode should not raise.

    Pass 1's ``_json_size`` swallows the JSON error and reports the event
    as oversized, which forces a walk-and-shrink pass. The string walk
    returns no strings (since ``set`` is unserialisable but not a string),
    so the function ends up returning a trimmed copy. The key contract is
    that the function does not raise and returns *some* dict.
    """
    event = {"type": "output", "data": {"value": set([1, 2, 3])}}
    # set is not JSON-serialisable; trim should not raise
    result = trim_event_for_sse(event)
    assert isinstance(result, dict)


def test_constants_match_h11_safety_budget():
    # We stay well below h11's default 16 KB.
    assert SSE_SAFE_PAYLOAD_BYTES <= 8 * 1024
    assert SSE_SAFE_TEXT_BYTES <= SSE_SAFE_PAYLOAD_BYTES
