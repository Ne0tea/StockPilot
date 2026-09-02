from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Optional


MAX_PROGRESS_EVENTS = 256
MAX_EVENT_BUFFER_BYTES = 2 * 1024 * 1024
MAX_QUEUE_EVENTS = 256
MAX_CRITICAL_EVENTS = 128

_CRITICAL_EVENT_TYPES = frozenset({
    "prompt", "question", "user-response", "output", "diagnostic",
    "final_result", "session_end",
})
_PROTECTED_EVENT_TYPES = frozenset({
    "prompt", "question", "user-response", "output", "diagnostic",
})
_TERMINAL_EVENT_TYPES = frozenset({"final_result", "session_end"})


def _event_size(event: dict) -> int:
    return len(json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _event_key(event: dict) -> Optional[tuple[str, str]]:
    event_type = event.get("type")
    if event_type == "stage" and event.get("stage"):
        return ("stage", str(event["stage"]))
    if event_type == "tool" and event.get("tool"):
        return ("tool", str(event["tool"]))
    return None


def _is_critical(event: dict) -> bool:
    return event.get("type") in _CRITICAL_EVENT_TYPES


class _BoundedEventQueue:
    """Event-loop-owned queue with coalescing and a hard item bound."""

    def __init__(self, maxsize: int = MAX_QUEUE_EVENTS):
        self.maxsize = maxsize
        self._items: Deque[tuple[dict, bool, Optional[tuple[str, str]]]] = deque()
        self._wake: Optional[asyncio.Event] = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        del loop
        self._wake = asyncio.Event()

    def clear(self) -> None:
        self._items.clear()
        if self._wake is not None:
            self._wake.clear()

    def qsize(self) -> int:
        return len(self._items)

    def put_nowait(self, event: dict, *, critical: bool, key: Optional[tuple[str, str]]) -> bool:
        if key is not None:
            self._items = deque(item for item in self._items if item[2] != key)
        if len(self._items) >= self.maxsize:
            index = next((i for i, item in enumerate(self._items) if not item[1]), None)
            if index is None:
                index = next(
                    (
                        i for i, item in enumerate(self._items)
                        if item[0].get("type") not in _PROTECTED_EVENT_TYPES
                        and item[0].get("type") not in _TERMINAL_EVENT_TYPES
                    ),
                    None,
                )
                if index is None:
                    # Preserve already queued semantic events. A terminal
                    # event may displace a non-terminal event; another
                    # critical event must wait for the replay buffer instead.
                    if not critical or event.get("type") not in _TERMINAL_EVENT_TYPES:
                        return False
                    index = next(
                        (i for i, item in enumerate(self._items) if item[0].get("type") not in _TERMINAL_EVENT_TYPES),
                        None,
                    )
                    if index is None:
                        return False
            items = list(self._items)
            items.pop(index)
            self._items = deque(items)
        self._items.append((event, critical, key))
        if self._wake is not None:
            self._wake.set()
        return True

    async def get(self) -> dict:
        if self._wake is None:
            self.bind(asyncio.get_running_loop())
        while not self._items:
            assert self._wake is not None
            self._wake.clear()
            await self._wake.wait()
        event, _, _ = self._items.popleft()
        if not self._items and self._wake is not None:
            self._wake.clear()
        return event


@dataclass(frozen=True)
class _EventRecord:
    seq: int
    event: dict
    size: int
    critical: bool
    key: Optional[tuple[str, str]] = None


@dataclass
class AgentRunSession:
    session_id: str
    run_id: str
    stock_code: str
    skill: str
    background_prompt: str
    status: str = "starting"
    final_result: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""
    cancel_requested: bool = False
    diagnostics: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue = _BoundedEventQueue()
        self._buffer: Deque[_EventRecord] = deque()
        self._buffer_bytes = 0
        self._ordinary_count = 0
        self._critical_count = 0
        self._lock = threading.Lock()
        self._next_seq = 1
        self._connection_generation = 0
        self._queue_cursor = 0
        self._pending: Deque[tuple[dict, bool, Optional[tuple[str, str]], int]] = deque()
        self._dispatch_scheduled = False
        self._completion_started = False
        self._terminal_published = False
        self._final_result_published = False
        self.is_finished = False
        self.finished_monotonic: Optional[float] = None

    @property
    def event_buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def event_buffer_bytes(self) -> int:
        with self._lock:
            return self._buffer_bytes

    @property
    def event_count(self) -> int:
        return self.event_buffer_size

    @property
    def event_bytes(self) -> int:
        return self.event_buffer_bytes

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def connection_generation(self) -> int:
        with self._lock:
            return self._connection_generation

    def _remove_record_locked(self, index: int) -> None:
        records = list(self._buffer)
        record = records.pop(index)
        self._buffer = deque(records)
        self._buffer_bytes -= record.size
        if record.critical:
            self._critical_count -= 1
        else:
            self._ordinary_count -= 1

    def _replace_record_locked(self, index: int, event: dict) -> None:
        records = list(self._buffer)
        old = records[index]
        size = _event_size(event)
        records[index] = _EventRecord(old.seq, event, size, old.critical, old.key)
        self._buffer = deque(records)
        self._buffer_bytes += size - old.size

    def _shrink_record_locked(self, index: int, target_size: int) -> bool:
        record = self._buffer[index]
        if record.size <= target_size:
            return False
        original = record.event
        text = original.get("text")
        candidate = None
        if isinstance(text, str):
            low, high = 0, len(text)
            while low <= high:
                middle = (low + high) // 2
                trial = dict(original)
                trial["text"] = text[:middle]
                trial["truncated"] = True
                if _event_size(trial) <= target_size:
                    candidate = trial
                    low = middle + 1
                else:
                    high = middle - 1
        if candidate is None:
            candidate = {
                key: value
                for key, value in original.items()
                if key in {"type", "event_id", "run_id", "status", "code"}
            }
            candidate.update({"truncated": True, "text": "事件内容超过缓冲上限，已截断"})
        size = _event_size(candidate)
        if size >= record.size:
            return False
        self._replace_record_locked(index, candidate)
        return True

    def _preserved_indices_locked(self) -> set[int]:
        latest: dict[str, int] = {}
        for index, record in enumerate(self._buffer):
            event_type = record.event.get("type")
            if event_type in _PROTECTED_EVENT_TYPES or event_type in _TERMINAL_EVENT_TYPES:
                latest[event_type] = index
        return set(latest.values())

    def _trim_locked(self) -> None:
        while self._buffer:
            if self._ordinary_count > MAX_PROGRESS_EVENTS:
                index = next(
                    (i for i, record in enumerate(self._buffer) if not record.critical),
                    None,
                )
                if index is not None:
                    self._remove_record_locked(index)
                    continue

            if self._critical_count > MAX_CRITICAL_EVENTS:
                preserved = self._preserved_indices_locked()
                index = next(
                    (
                        i for i, record in enumerate(self._buffer)
                        if record.critical
                        and i not in preserved
                        and record.event.get("type") not in _TERMINAL_EVENT_TYPES
                    ),
                    None,
                )
                if index is None:
                    index = next(
                        (
                            i for i, record in enumerate(self._buffer)
                            if record.critical
                            and record.event.get("type") not in _TERMINAL_EVENT_TYPES
                        ),
                        None,
                    )
                if index is not None:
                    self._remove_record_locked(index)
                    continue

            if self._buffer_bytes <= MAX_EVENT_BUFFER_BYTES:
                break

            preserved = self._preserved_indices_locked()
            index = next(
                (i for i, record in enumerate(self._buffer) if not record.critical and i not in preserved),
                None,
            )
            if index is None:
                index = next((i for i in range(len(self._buffer)) if i not in preserved), None)
            if index is not None:
                self._remove_record_locked(index)
                continue

            # Only the latest semantic and terminal events remain. Shrink
            # them proportionally instead of dropping a semantic event.
            target_size = max(64, MAX_EVENT_BUFFER_BYTES // max(1, len(preserved)))
            changed = False
            for index in sorted(preserved):
                if self._buffer[index].size > target_size:
                    changed = self._shrink_record_locked(index, target_size) or changed
            if changed:
                continue

            # Non-text payloads are reduced to a compact diagnostic by
            # _shrink_record_locked. Keep terminal events as the final fallback.
            index = next(
                (i for i, record in enumerate(self._buffer) if record.event.get("type") not in _TERMINAL_EVENT_TYPES),
                0,
            )
            self._remove_record_locked(index)

    def _append_history_locked(self, record: _EventRecord) -> None:
        if record.key is not None:
            old_index = next((i for i, old in enumerate(self._buffer) if old.key == record.key), None)
            if old_index is not None:
                self._remove_record_locked(old_index)
        self._buffer.append(record)
        self._buffer_bytes += record.size
        if record.critical:
            self._critical_count += 1
        else:
            self._ordinary_count += 1
        self._trim_locked()

    def attach_loop(self, loop: asyncio.AbstractEventLoop, after_event_id: int = 0) -> list[dict]:
        """Atomically register a connection and return one replay slice."""
        with self._lock:
            self._queue.bind(loop)
            self._loop = loop
            self._connection_generation += 1
            self._pending.clear()
            self._dispatch_scheduled = False
            self._queue.clear()
            try:
                threshold = max(0, int(after_event_id or 0))
            except (TypeError, ValueError):
                threshold = 0
            self._queue_cursor = self._buffer[-1].seq if self._buffer else 0
            return [dict(record.event) for record in self._buffer if record.seq > threshold]

    def detach_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        with self._lock:
            if loop is not None and self._loop is not loop:
                return
            self._detach_loop_locked()

    def detach_loop_for_generation(self, generation: int) -> None:
        with self._lock:
            if generation != self._connection_generation:
                return
            self._detach_loop_locked()

    def _detach_loop_locked(self) -> None:
        self._connection_generation += 1
        self._loop = None
        self._pending.clear()
        self._dispatch_scheduled = False
        self._queue.clear()

    def _queue_pending_locked(
        self,
        event: dict,
        critical: bool,
        key: Optional[tuple[str, str]],
        generation: int,
    ) -> bool:
        if key is not None:
            self._pending = deque(item for item in self._pending if item[2] != key)
        if len(self._pending) >= MAX_QUEUE_EVENTS:
            index = next((i for i, item in enumerate(self._pending) if not item[1]), None)
            if index is None:
                index = next(
                    (
                        i for i, item in enumerate(self._pending)
                        if item[0].get("type") not in _PROTECTED_EVENT_TYPES
                        if item[0].get("type") not in _TERMINAL_EVENT_TYPES
                    ),
                    None,
                )
                if index is None:
                    # Do not sacrifice queued semantic events for another
                    # non-terminal event. Only a terminal event may displace
                    # a non-terminal item when the queue is entirely critical.
                    if not critical or event.get("type") not in _TERMINAL_EVENT_TYPES:
                        return False
                    index = next(
                        (i for i, item in enumerate(self._pending) if item[0].get("type") not in _TERMINAL_EVENT_TYPES),
                        None,
                    )
                    if index is None:
                        return False
            items = list(self._pending)
            items.pop(index)
            self._pending = deque(items)
        self._pending.append((event, critical, key, generation))
        return True

    def _flush_pending(self, generation: int) -> None:
        """Move a bounded cross-thread batch into the loop-owned queue."""
        with self._lock:
            if self._loop is None or generation != self._connection_generation:
                if generation == self._connection_generation:
                    self._dispatch_scheduled = False
                return
            pending = list(self._pending)
            self._pending.clear()
        for event, critical, key, item_generation in pending:
            if item_generation == generation:
                self._queue.put_nowait(event, critical=critical, key=key)

        with self._lock:
            if self._loop is None or generation != self._connection_generation:
                if generation == self._connection_generation:
                    self._dispatch_scheduled = False
                return
            if not self._pending:
                self._dispatch_scheduled = False
                return
            loop = self._loop
        try:
            loop.call_soon(self._flush_pending, generation)
        except RuntimeError:
            with self._lock:
                if generation == self._connection_generation:
                    self._dispatch_scheduled = False

    def _fit_event_locked(self, event: dict, seq: int) -> tuple[dict, int]:
        event_with_id = dict(event)
        event_with_id.setdefault("run_id", self.run_id)
        event_with_id["event_id"] = seq
        size = _event_size(event_with_id)
        if size <= MAX_EVENT_BUFFER_BYTES:
            return event_with_id, size

        text = event_with_id.get("text")
        if isinstance(text, str):
            event_with_id["text"] = text[: MAX_EVENT_BUFFER_BYTES // 2]
            event_with_id["truncated"] = True
            size = _event_size(event_with_id)
        if size > MAX_EVENT_BUFFER_BYTES:
            event_with_id = {
                key: value
                for key, value in event_with_id.items()
                if key in {"type", "event_id", "run_id", "status", "code"}
            }
            event_with_id.update({"truncated": True, "text": "事件内容超过 2 MiB 上限，已截断"})
            size = _event_size(event_with_id)
        return event_with_id, size

    def _prepare_event_locked(self, event: dict, *, allow_completion: bool = False):
        if not isinstance(event, dict) or event.get("type") == "heartbeat":
            return None
        event_type = event.get("type")
        if event_type == "session_end" and self._terminal_published:
            return None
        if event_type == "final_result" and self._final_result_published:
            return None
        if self.is_finished or (self._completion_started and not allow_completion):
            return None

        seq = self._next_seq
        self._next_seq += 1
        event_with_id, size = self._fit_event_locked(event, seq)
        critical = _is_critical(event_with_id)
        key = _event_key(event_with_id)
        self._append_history_locked(_EventRecord(seq, event_with_id, size, critical, key))
        if event_type == "diagnostic":
            self.diagnostics.append(dict(event_with_id))
            del self.diagnostics[:-128]
        if event_type == "final_result":
            self._final_result_published = True
        if event_type == "session_end":
            self._terminal_published = True

        loop = self._loop
        generation = self._connection_generation
        should_queue = loop is not None and seq > self._queue_cursor
        if should_queue:
            self._queue_cursor = seq
        return loop, generation, event_with_id, critical, key, should_queue

    def _schedule(self, prepared) -> None:
        if prepared is None:
            return
        loop, generation, event, critical, key, should_queue = prepared
        if not should_queue or loop is None or not loop.is_running():
            return
        with self._lock:
            if self._loop is not loop or generation != self._connection_generation:
                return
            if not self._queue_pending_locked(event, critical, key, generation):
                return
            if self._dispatch_scheduled:
                return
            self._dispatch_scheduled = True
        try:
            loop.call_soon_threadsafe(self._flush_pending, generation)
        except RuntimeError:
            with self._lock:
                if generation == self._connection_generation:
                    self._dispatch_scheduled = False

    def publish(self, event: dict) -> Optional[int]:
        with self._lock:
            prepared = self._prepare_event_locked(event)
        self._schedule(prepared)
        return prepared[2]["event_id"] if prepared else None

    def finish(
        self,
        *,
        status: str,
        text: str,
        diagnostic: Optional[dict] = None,
        final_result: Optional[str] = None,
    ) -> bool:
        with self._lock:
            if self.is_finished or self._completion_started:
                return False
            self._completion_started = True
            prepared = []
            if diagnostic is not None:
                prepared.append(self._prepare_event_locked(diagnostic, allow_completion=True))
            if final_result is not None:
                prepared.append(
                    self._prepare_event_locked(
                        {"type": "final_result", "text": final_result},
                        allow_completion=True,
                    )
                )
            self.status = status
            self.final_result = text
            self.finished_at = datetime.now().isoformat()
            self.finished_monotonic = time.monotonic()
            prepared.append(
                self._prepare_event_locked(
                    {"type": "session_end", "status": status, "text": text},
                    allow_completion=True,
                )
            )
        for item in prepared:
            self._schedule(item)
        with self._lock:
            self.is_finished = True
        return True

    async def get_event(
        self, timeout: float = 15.0, generation: Optional[int] = None
    ) -> Optional[dict]:
        with self._lock:
            if generation is not None and generation != self._connection_generation:
                return None
            terminal_and_drained = (
                self.is_finished
                and not self._pending
                and not self._dispatch_scheduled
            )
        if terminal_and_drained and self._queue.qsize() == 0:
            return None
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            if generation is not None:
                with self._lock:
                    if generation != self._connection_generation:
                        return None
            if self.is_finished:
                return None
            return {"type": "heartbeat"}

    def snapshot_events(self, after_event_id: int = 0) -> list[dict]:
        try:
            threshold = max(0, int(after_event_id or 0))
        except (TypeError, ValueError):
            threshold = 0
        with self._lock:
            return [dict(record.event) for record in self._buffer if record.seq > threshold]

    def request_cancel(self) -> bool:
        with self._lock:
            if self.is_finished or self._completion_started:
                return False
            self.cancel_requested = True
            self.status = "cancelling"
        self.publish({"type": "status", "status": "cancelling", "text": "正在等待后台分析收尾"})
        return True

    def mark_finished(self, *, status: str, text: str) -> bool:
        return self.finish(status=status, text=text)
