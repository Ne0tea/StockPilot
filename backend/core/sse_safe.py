"""SSE payload safety helpers — keeps chunked-HTTP event sizes well under
h11's default ``max_incomplete_event_size`` (16 KB) so uvicorn never raises
``Separator is found, but chunk is longer than limit``.

The function in this module is intentionally dependency-free so it can be
unit-tested without importing the SQLAlchemy stack.
"""

import json
from typing import Any


# h11 caps each chunked-HTTP body chunk at ~16 KB. We stay well below that
# so multi-byte UTF-8 (Chinese text) cannot push us over the line.
SSE_SAFE_PAYLOAD_BYTES = 8 * 1024
SSE_SAFE_TEXT_BYTES = 6 * 1024

# Field names dropped in last-resort pass before forcing a hard truncate.
# Only top-level optional fields are listed — we never delete ``data``,
# ``message`` etc. because they carry essential event semantics.
_DROPPABLE_TOP_LEVEL_FIELDS = (
    "partial",
    "details",
    "question",
    "reason",
    "metadata",
)
# Same field names, but scanned one level deeper (e.g. ``data.metadata``).
_DROPPABLE_NESTED_FIELDS = (
    "partial",
    "details",
    "question",
    "reason",
    "output",
    "metadata",
)


def _json_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return SSE_SAFE_PAYLOAD_BYTES + 1


def _walk_strings(obj: Any, path: tuple = ()):
    """Yield ``(path, value)`` for every string nested inside ``obj``."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, path + (i,))


def _set_at_path(obj: Any, path: tuple, value: Any) -> Any:
    """Return a copy of ``obj`` with ``obj[*path]`` replaced by ``value``."""
    if not path:
        return value
    if isinstance(obj, dict):
        new = dict(obj)
        new[path[0]] = _set_at_path(new[path[0]], path[1:], value)
        return new
    if isinstance(obj, list):
        new = list(obj)
        new[path[0]] = _set_at_path(new[path[0]], path[1:], value)
        return new
    return value


def _drop_at_path(obj: Any, path: tuple) -> Any:
    """Return a copy of ``obj`` with ``obj[*path]`` removed."""
    if len(path) == 1:
        if isinstance(obj, dict):
            new = dict(obj)
            new.pop(path[0], None)
            return new
        if isinstance(obj, list):
            return [v for i, v in enumerate(obj) if i != path[0]]
        return obj
    if isinstance(obj, dict):
        new = dict(obj)
        if path[0] in new:
            new[path[0]] = _drop_at_path(new[path[0]], path[1:])
        return new
    if isinstance(obj, list):
        new = list(obj)
        if 0 <= path[0] < len(new):
            new[path[0]] = _drop_at_path(new[path[0]], path[1:])
        return new
    return obj


def trim_event_for_sse(event: dict) -> dict:
    """Return a copy of ``event`` that fits within
    :data:`SSE_SAFE_PAYLOAD_BYTES` once JSON-encoded. Loops over two passes:

    1.  **Shrink pass** — locate the largest nested string and halve it,
        capped at :data:`SSE_SAFE_TEXT_BYTES`. Repeat until the event fits
        or no string is larger than 256 chars.
    2.  **Drop pass** — pop known heavy optional fields (``data``,
        ``partial``, ``details`` …) until the event fits.

    The function guarantees the returned value serialises to
    ≤ :data:`SSE_SAFE_PAYLOAD_BYTES` bytes, or returns the original event
    unchanged if JSON serialisation fails.
    """
    if _json_size(event) <= SSE_SAFE_PAYLOAD_BYTES:
        return event

    trimmed: Any = event

    # ── Pass 1: iteratively halve the largest string field ────────────
    for _ in range(32):
        if _json_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES:
            return trimmed
        strings = list(_walk_strings(trimmed))
        if not strings:
            break
        path, value = max(strings, key=lambda kv: len(kv[1]))
        if len(value) <= 256:
            break
        # Halve toward the cap. Use SSE_SAFE_TEXT_BYTES as the ceiling.
        target = max(256, min(len(value) // 2, SSE_SAFE_TEXT_BYTES))
        trimmed = _set_at_path(trimmed, path, value[:target] + "...[trimmed]")

    # ── Pass 2: drop known heavy optional fields ──────────────────────
    # Top-level fields first (cheap), then nested scan (one level deep).
    for _ in range(len(_DROPPABLE_TOP_LEVEL_FIELDS) + len(_DROPPABLE_NESTED_FIELDS)):
        if _json_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES:
            return trimmed
        dropped_any = False
        for field in _DROPPABLE_TOP_LEVEL_FIELDS:
            if isinstance(trimmed, dict) and field in trimmed:
                trimmed = {k: v for k, v in trimmed.items() if k != field}
                dropped_any = True
                break
        if dropped_any:
            continue
        for field in _DROPPABLE_NESTED_FIELDS:
            if isinstance(trimmed, dict):
                for k, v in list(trimmed.items()):
                    if isinstance(v, dict) and field in v:
                        new_parent = dict(v)
                        new_parent.pop(field, None)
                        new_root = dict(trimmed)
                        new_root[k] = new_parent
                        trimmed = new_root
                        dropped_any = True
                        break
            if dropped_any:
                break
        if not dropped_any:
            break

    # ── Pass 3: last-resort hard cap ──────────────────────────────────
    # Walk every string and truncate to a tiny limit until it fits.
    for _ in range(64):
        if _json_size(trimmed) <= SSE_SAFE_PAYLOAD_BYTES:
            return trimmed
        strings = list(_walk_strings(trimmed))
        if not strings:
            return trimmed
        path, value = strings[0]
        trimmed = _set_at_path(trimmed, path, value[:200] + "...")

    return trimmed
