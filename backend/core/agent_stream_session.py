from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Optional


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
        self._queue: asyncio.Queue = asyncio.Queue()
        self._buffer: Deque[tuple[int, dict]] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._next_seq = 1
        self._last_enqueued_seq = 0
        self._attaching = False
        self.is_finished = False

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            self._attaching = True

        try:
            while True:
                with self._lock:
                    pending = [
                        event
                        for seq, event in self._buffer
                        if seq > self._last_enqueued_seq
                    ]
                    if pending:
                        self._last_enqueued_seq = self._buffer[-1][0]
                    else:
                        self._attaching = False
                        break

                for event in pending:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        finally:
            with self._lock:
                self._attaching = False

    def publish(self, event: dict) -> None:
        should_queue = False
        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            self._buffer.append((seq, event))
            if self._loop and self._loop.is_running() and not self._attaching:
                self._last_enqueued_seq = seq
                should_queue = True
        if should_queue and self._loop:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    async def get_event(self, timeout: float = 15.0) -> Optional[dict]:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            if self.is_finished:
                return None
            return {"type": "heartbeat"}

    def snapshot_events(self) -> list[dict]:
        with self._lock:
            return [event for _, event in self._buffer]

    def mark_finished(self, *, status: str, text: str) -> None:
        self.status = status
        self.final_result = text
        self.finished_at = datetime.now().isoformat()
        self.is_finished = True
        self.publish({"type": "session_end", "status": status, "text": text})
