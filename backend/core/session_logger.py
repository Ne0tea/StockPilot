import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# Flush at most this often. Per-line flush() on a slow filesystem (e.g. WSL2
# /mnt drvfs) serializes write syscalls on the shared event loop and stutters
# all concurrent SSE streams. Time-throttling keeps tailing near-real-time
# while collapsing many small writes into far fewer syscalls.
_FLUSH_INTERVAL_SECONDS = 0.5


class SessionLogWriter:
    """Per-session writer that appends human-readable text lines to
    backend/reports/<code>/<date>.log. Designed to be invoked from
    InteractiveSession._put_event before the SSE queue receives the event.

    Failures are swallowed (logged to stderr) so the SSE pipeline never
    breaks because of a disk-write issue.
    """

    def __init__(self, reports_root: str, code: str, date_str: str):
        self._reports_root = Path(reports_root)
        self._code = code
        self._date_str = date_str
        self._fp = None
        self._last_flush = 0.0

    @property
    def path(self) -> Path:
        return self._reports_root / self._code / f"{self._date_str}.log"

    def open(self, name: str, auto_respond: bool):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existed = self.path.exists()
            self._fp = open(self.path, "a", encoding="utf-8")
            if existed:
                self._write_line("session_start", "=== 重新生成 ===")
            self._write_line(
                "session_start",
                f"{self._code} {name} auto_respond={auto_respond}",
            )
        except Exception as exc:
            sys.stderr.write(f"[SessionLogWriter] open failed: {exc}\n")
            self._fp = None

    def append(self, event: dict):
        if self._fp is None:
            return
        event_type = event.get("type")
        if not event_type or event_type in ("heartbeat", "session_end"):
            # session_end is written directly by close(); skip it here to
            # avoid a duplicate blank-bodied line.
            return
        try:
            text = self._format_body(event)
            for line in text.splitlines() or [""]:
                self._write_line(event_type, line)
        except Exception as exc:
            sys.stderr.write(f"[SessionLogWriter] append failed: {exc}\n")

    def close(self, final_status: Optional[str] = None):
        if self._fp is None:
            return
        try:
            if final_status is not None:
                self._write_line("session_end", f"status={final_status}", flush=True)
            self._fp.flush()
            self._fp.close()
        except Exception as exc:
            sys.stderr.write(f"[SessionLogWriter] close failed: {exc}\n")
        finally:
            self._fp = None

    # ── private ──

    def _format_body(self, event: dict) -> str:
        t = event.get("type")
        if t == "progress":
            action = event.get("action") or ""
            text = event.get("text") or ""
            return f"({action}) {text}" if action else text
        if t == "question":
            question = event.get("question") or ""
            default = event.get("default")
            return f"{question}(默认: {default})" if default else question
        if t == "user-response":
            return event.get("text") or ""
        # session_end is written directly by close(); not routed through append().
        return event.get("text") or ""

    def _write_line(self, event_type: str, body: str, flush: bool = False):
        if self._fp is None:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self._fp.write(f"[{ts}] [{event_type}] {body}\n")
        now = time.monotonic()
        if flush or (now - self._last_flush) >= _FLUSH_INTERVAL_SECONDS:
            self._fp.flush()
            self._last_flush = now
