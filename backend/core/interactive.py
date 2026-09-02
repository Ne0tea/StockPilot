"""Interactive stock analysis session using ClaudeSDKClient multi-turn flow."""

import asyncio
import json
import threading
from collections import deque
from datetime import date
from time import monotonic
from typing import Optional
from uuid import uuid4

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from claude_agent_sdk.types import AssistantMessage, ResultMessage, StreamEvent, TextBlock

from core.analysis_task_state import shanghai_today, upsert_task_status
from core.report_renderer import (
    build_report_instruction_target,
    ensure_reports_root,
    extract_report_markdown,
    move_generated_report_html,
)
from core.report_storage import resolve_stock_report_terms
from core.session_logger import SessionLogWriter


QUESTION_TIMEOUT_SECONDS = 30.0
MAX_HTML_RETRY_ATTEMPTS = 1
MAX_COMPLETION_NUDGE_ATTEMPTS = 2
ANALYSIS_DONE_SENTINEL = "__ANALYSIS_DONE__"
MAX_INTERACTIVE_EVENTS = 256
MAX_INTERACTIVE_EVENT_BYTES = 2 * 1024 * 1024
MAX_INTERACTIVE_CRITICAL_EVENTS = 128
INTERACTIVE_SESSION_TTL_SECONDS = 30 * 60
MAX_RETAINED_INTERACTIVE_SESSIONS = 256

LOGIN_QUESTION_OPTIONS = ["已登录", "继续分析", "跳过"]
AFFIRMATIVE_RESPONSES = {"已登录", "继续分析", "登录了", "allow", "允许", "yes", "y"}
NEGATIVE_RESPONSES = {"跳过", "没登录", "未登录", "不想登录", "deny", "拒绝", "no", "n"}


# Active sessions: {code: InteractiveSession}
_active_sessions: dict[str, "InteractiveSession"] = {}
_sessions_lock = threading.Lock()
_background_tasks: set[asyncio.Task] = set()
_background_tasks_lock = threading.Lock()
_accepting_lock = threading.Lock()
_accepting_new_tasks = True
_housekeeping_task: Optional[asyncio.Task] = None


class _BoundedEventQueue:
    """Event-loop-owned queue with bounded storage and progress coalescing."""

    def __init__(self, maxsize: int = MAX_INTERACTIVE_EVENTS):
        self.maxsize = maxsize
        self._items: deque[tuple[dict, bool, Optional[tuple]]] = deque()
        self._wake: Optional[asyncio.Event] = None

    def bind(self) -> None:
        if self._wake is None:
            self._wake = asyncio.Event()

    def clear(self) -> None:
        self._items.clear()
        if self._wake is not None:
            self._wake.clear()

    def qsize(self) -> int:
        return len(self._items)

    def _replace_key(self, key: Optional[tuple], event: dict, critical: bool) -> bool:
        if key is None:
            return False
        for index, item in enumerate(self._items):
            if item[2] == key:
                items = list(self._items)
                items[index] = (event, critical, key)
                self._items = deque(items)
                if self._wake is not None:
                    self._wake.set()
                return True
        return False

    def put_nowait(self, event: dict, *, critical: bool, key: Optional[tuple]) -> bool:
        if self._replace_key(key, event, critical):
            return True
        if len(self._items) >= self.maxsize:
            index = next((i for i, item in enumerate(self._items) if not item[1]), None)
            if index is None:
                if not critical:
                    return False
                index = next(
                    (i for i, item in enumerate(self._items)
                     if not _event_is_protected(item[0])),
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
        self.bind()
        while not self._items:
            assert self._wake is not None
            await self._wake.wait()
            if not self._items:
                self._wake.clear()
        event, _, _ = self._items.popleft()
        if not self._items and self._wake is not None:
            self._wake.clear()
        return event


def _track_task(task: asyncio.Task) -> asyncio.Task:
    with _background_tasks_lock:
        _background_tasks.add(task)

    def _discard(done_task: asyncio.Task) -> None:
        with _background_tasks_lock:
            _background_tasks.discard(done_task)

    task.add_done_callback(_discard)
    return task


def get_background_tasks() -> list[asyncio.Task]:
    with _background_tasks_lock:
        return list(_background_tasks)


def set_accepting_new_tasks(accepting: bool) -> None:
    global _accepting_new_tasks
    with _accepting_lock:
        _accepting_new_tasks = bool(accepting)
    if not accepting:
        _stop_housekeeping()


def is_accepting_new_tasks() -> bool:
    with _accepting_lock:
        return _accepting_new_tasks


def _ensure_housekeeping() -> None:
    global _housekeeping_task
    if not is_accepting_new_tasks():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    if _housekeeping_task is not None and not _housekeeping_task.done():
        return
    task = asyncio.create_task(_interactive_housekeeping_loop())
    _housekeeping_task = _track_task(task)

    def clear_task(done_task: asyncio.Task) -> None:
        global _housekeeping_task
        if _housekeeping_task is done_task:
            _housekeeping_task = None

    task.add_done_callback(clear_task)


def _stop_housekeeping() -> None:
    global _housekeeping_task
    task = _housekeeping_task
    _housekeeping_task = None
    if task is not None and not task.done():
        task.cancel()


async def _interactive_housekeeping_loop() -> None:
    while True:
        await asyncio.sleep(60.0)
        with _sessions_lock:
            _prune_sessions_locked()


def _event_is_critical(event: dict) -> bool:
    return event.get("type") in {
        "prompt", "question", "user-response", "output",
        "diagnostic", "final_result", "session_end", "error",
    }


def _event_is_protected(event: dict) -> bool:
    return event.get("type") in {"final_result", "session_end"}


def _event_key(event: dict) -> Optional[tuple]:
    if event.get("type") not in {"progress", "status"}:
        return None
    return (event.get("type"), event.get("action"), event.get("stage"), event.get("tool"))


def _event_size(event: dict) -> int:
    try:
        return len(json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def _fit_event_to_buffer(event: dict) -> dict:
    """Keep a single event from exceeding the history byte budget."""
    if _event_size(event) <= MAX_INTERACTIVE_EVENT_BYTES:
        return event

    fitted = dict(event)
    for field in ("text", "details", "question"):
        value = fitted.get(field)
        if isinstance(value, str):
            fitted[field] = value[: max(0, len(value) // 2)]
            if _event_size(fitted) <= MAX_INTERACTIVE_EVENT_BYTES:
                return fitted
    return {
        "type": fitted.get("type", "event"),
        "event_id": fitted.get("event_id"),
        "truncated": True,
    }


def _shrink_event_to_size(event: dict, target_size: int) -> dict:
    if _event_size(event) <= target_size:
        return event
    for field in ("text", "details", "question"):
        value = event.get(field)
        if not isinstance(value, str):
            continue
        low, high = 0, len(value)
        best = None
        while low <= high:
            middle = (low + high) // 2
            candidate = dict(event)
            candidate[field] = value[:middle]
            candidate["truncated"] = True
            if _event_size(candidate) <= target_size:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        if best is not None:
            return best
    return {
        "type": event.get("type", "event"),
        "event_id": event.get("event_id"),
        "truncated": True,
    }


def acquire_analysis_start_slot() -> bool:
    from core.stock_reset import acquire_analysis_start_slot as _acquire
    return _acquire()


def release_analysis_start_slot() -> None:
    from core.stock_reset import release_analysis_start_slot as _release
    _release()


def is_reset_in_progress() -> bool:
    from core.stock_reset import is_reset_in_progress as _is_reset
    return _is_reset()


def get_reset_generation() -> int:
    from core.stock_reset import get_reset_generation as _get_generation
    return _get_generation()


def normalize_answer(answer: Optional[str], default: str) -> str:
    value = (answer or "").strip()
    return value or default


def classify_assistant_question(text: str) -> Optional[dict]:
    stripped = (text or "").strip()
    if not stripped:
        return None

    login_question_markers = [
        "请问您是否已经登录东方财富",
        "是否已经登录东方财富",
        "回复\"已登录\"",
        "回复“已登录”",
        "请回复\"已登录\"",
        "请回复“已登录”",
    ]
    if any(marker in stripped for marker in login_question_markers):
        return {
            "kind": "login_confirmation",
            "question": "请问您是否已经登录东方财富？",
            "default": "已登录",
            "options": LOGIN_QUESTION_OPTIONS,
            "details": stripped,
        }

    generic_confirm_markers = ["是否继续", "是否确认", "请选择", "请回复"]
    if any(marker in stripped for marker in generic_confirm_markers):
        return {
            "kind": "text_confirmation",
            "question": stripped.splitlines()[-1].strip() or stripped,
            "default": "继续",
            "options": ["继续", "跳过"],
            "details": stripped,
        }

    return None


def build_permission_question(tool_name: str, tool_input: dict, context: ToolPermissionContext) -> dict:
    title = context.title or f"是否允许使用工具 {tool_name}？"
    details = context.description or json.dumps(tool_input, ensure_ascii=False)
    return {
        "kind": "tool_permission",
        "question": title,
        "default": "允许",
        "options": ["允许", "拒绝"],
        "details": f"{tool_name}: {details}",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


class UserResponse:
    """Holds a pending user response with async coordination."""

    def __init__(self):
        self.event = asyncio.Event()
        self.response: Optional[str] = None

    async def wait(self, timeout: float) -> Optional[str]:
        try:
            await asyncio.wait_for(self.event.wait(), timeout=timeout)
            return self.response
        except asyncio.TimeoutError:
            return None

    def set(self, text: str):
        self.response = text
        self.event.set()


class InteractiveSession:
    """Manages an interactive analysis via ClaudeSDKClient streaming conversation."""

    def __init__(self, code: str, name: str, auto_respond: bool = False):
        self.code = code
        self.name = name
        self.auto_respond = auto_respond
        self.report_time, self.report_date = resolve_stock_report_terms(code)
        self.session_id = f"stock_{code}_{date.today().isoformat()}"
        self.run_id = uuid4().hex
        self.output_buffer = ""
        self.report_markdown = ""
        self._events = _BoundedEventQueue()
        self._event_history = deque()
        self._event_history_bytes = 0
        self._event_ordinary_count = 0
        self._event_critical_count = 0
        self._event_sequence = 0
        self._event_lock = threading.Lock()
        self._done = asyncio.Event()
        self._running = True
        self._settling = False
        self._cancel_requested = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._connection_generation = 0
        self._queue_cursor = 0
        self._start_generation = uuid4().hex
        self._task: Optional[asyncio.Task] = None
        self._results_task: Optional[asyncio.Task] = None
        self._pending_response: Optional[UserResponse] = None
        self._pending_question: Optional[dict] = None
        self.final_status = "running"
        self.final_message = ""
        self._html_retry_count = 0
        self._analysis_done_seen = False
        self._completion_nudge_count = 0
        self._results_task_started = False
        self._terminal_event_published = False
        self._finished_at = 0.0
        self._log_closed = False
        self._log_writer = SessionLogWriter(
            reports_root=ensure_reports_root(),
            code=code,
            date_str=date.today().isoformat(),
        )
        self._log_writer_name = name
        self._log_writer_auto_respond = auto_respond

    @property
    def is_running(self) -> bool:
        task = self._task
        return self._running or (task is not None and not task.done())

    @property
    def is_settling(self) -> bool:
        return self._settling

    def set_task(self, task: asyncio.Task) -> None:
        self._task = task

    @property
    def run_identity(self) -> tuple[str, str]:
        return self.run_id, self._start_generation

    @property
    def event_buffer_size(self) -> int:
        with self._event_lock:
            return len(self._event_history)

    @property
    def event_buffer_bytes(self) -> int:
        with self._event_lock:
            return self._event_history_bytes

    @property
    def queue_size(self) -> int:
        return self._events.qsize()

    def _remove_history_at_locked(self, index: int) -> None:
        records = list(self._event_history)
        removed = records.pop(index)
        self._event_history = deque(records)
        self._event_history_bytes -= _event_size(removed)
        if _event_is_critical(removed):
            self._event_critical_count -= 1
        else:
            self._event_ordinary_count -= 1

    def _record_event(self, event: dict) -> dict:
        recorded = dict(event)
        with self._event_lock:
            self._event_sequence += 1
            recorded["event_id"] = self._event_sequence
            recorded = _fit_event_to_buffer(recorded)
            key = _event_key(recorded)
            if key is not None:
                retained = deque()
                for previous in self._event_history:
                    if _event_key(previous) == key:
                        self._event_history_bytes -= _event_size(previous)
                        if _event_is_critical(previous):
                            self._event_critical_count -= 1
                        else:
                            self._event_ordinary_count -= 1
                    else:
                        retained.append(previous)
                self._event_history = retained
            self._event_history.append(recorded)
            self._event_history_bytes += _event_size(recorded)
            if _event_is_critical(recorded):
                self._event_critical_count += 1
            else:
                self._event_ordinary_count += 1
            while (
                self._event_ordinary_count > MAX_INTERACTIVE_EVENTS
                or self._event_critical_count > MAX_INTERACTIVE_CRITICAL_EVENTS
                or self._event_history_bytes > MAX_INTERACTIVE_EVENT_BYTES
            ):
                index = next(
                    (i for i, candidate in enumerate(self._event_history)
                     if not _event_is_critical(candidate)),
                    None,
                )
                if index is None:
                    index = next(
                         (i for i, candidate in enumerate(self._event_history)
                          if not _event_is_protected(candidate)),
                        None,
                    )
                if index is None:
                    index = 0
                    candidate = self._event_history[index]
                    target_size = max(64, MAX_INTERACTIVE_EVENT_BYTES - (
                        self._event_history_bytes - _event_size(candidate)
                    ))
                    fitted = _shrink_event_to_size(candidate, target_size)
                    if _event_size(fitted) < _event_size(candidate):
                        records = list(self._event_history)
                        records[index] = fitted
                        self._event_history = deque(records)
                        self._event_history_bytes += _event_size(fitted) - _event_size(candidate)
                        continue
                self._remove_history_at_locked(index)
        return recorded

    def _enqueue_event(self, event: dict) -> None:
        self._events.put_nowait(
            event,
            critical=_event_is_critical(event),
            key=_event_key(event),
        )

    def _enqueue_if_current(self, event: dict, generation: int) -> None:
        with self._event_lock:
            if generation != self._connection_generation or self._event_loop is None:
                return
            self._enqueue_event(event)

    def attach_loop(
        self,
        loop: asyncio.AbstractEventLoop,
        after_event_id: Optional[int] = None,
    ) -> list[dict]:
        try:
            after = max(0, int(after_event_id or 0))
        except (TypeError, ValueError):
            after = 0
        with self._event_lock:
            self._event_loop = loop
            self._connection_generation += 1
            self._events.bind()
            self._events.clear()
            self._queue_cursor = self._event_sequence
            return [
                dict(event)
                for event in self._event_history
                if int(event.get("event_id", 0)) > after
            ]

    def detach_loop(self) -> None:
        self.detach_loop_for_generation(None)

    @property
    def connection_generation(self) -> int:
        with self._event_lock:
            return self._connection_generation

    def detach_loop_for_generation(self, generation: Optional[int]) -> None:
        with self._event_lock:
            if generation is not None and generation != self._connection_generation:
                return
            self._connection_generation += 1
            self._event_loop = None
            self._events.clear()
            self._queue_cursor = self._event_sequence

    def events_after(self, after_event_id: Optional[int]) -> list[dict]:
        try:
            after = max(0, int(after_event_id or 0))
        except (TypeError, ValueError):
            after = 0
        with self._event_lock:
            return [
                dict(event) for event in self._event_history
                if int(event.get("event_id", 0)) > after
            ]

    async def get_event(self, generation: Optional[int] = None) -> Optional[dict]:
        if generation is not None and generation != self.connection_generation:
            return None
        try:
            event = await asyncio.wait_for(self._events.get(), timeout=15.0)
            if generation is not None and generation != self.connection_generation:
                return None
            return event
        except asyncio.TimeoutError:
            if generation is not None and generation != self.connection_generation:
                return None
            if self._done.is_set():
                return None
            return {"type": "heartbeat"}

    def _put_event(self, event: dict):
        if event.get("type") == "heartbeat":
            return
        event = self._record_event(event)
        self._log_writer.append(event)
        with self._event_lock:
            loop = self._event_loop
            generation = self._connection_generation
            event_id = int(event.get("event_id", 0))
            should_queue = event_id > self._queue_cursor
            if should_queue:
                self._queue_cursor = event_id
        if should_queue and loop and loop.is_running():
            loop.call_soon_threadsafe(self._enqueue_if_current, event, generation)
            return
        # A disconnected client must not leave events accumulating in the
        # live queue; retained history is the replay source on reconnect.
        return

    async def start(self):
        loop = asyncio.get_running_loop()
        with self._event_lock:
            if self._event_loop is None:
                self._event_loop = loop
                self._connection_generation += 1
            self._events.bind()
        self._log_writer.open(name=self._log_writer_name, auto_respond=self._log_writer_auto_respond)
        try:
            await self._run_conversation()
            if self.final_status == "running":
                self.final_status = self._resolve_terminal_status()
                if self.final_status == "error" and not self.final_message:
                    self.final_message = f"分析未收到完成信号 {ANALYSIS_DONE_SENTINEL}"
                    mark_analysis_error_for_session(self, self.final_message)
        except asyncio.CancelledError:
            self._cancel_requested = True
            self.final_status = "cancelled"
            self.final_message = "分析已取消"
        except Exception as exc:
            if not self._cancel_requested:
                self.final_status = "error"
                self.final_message = str(exc)
                mark_analysis_error_for_session(self, str(exc))
                self._put_event({"type": "error", "text": str(exc)})
            else:
                self.final_status = "cancelled"
                self.final_message = "分析已取消"
        finally:
            if self.final_status == "done" and not self._results_task_started:
                self._results_task_started = True
                self._settling = True
                result_task = _track_task(
                    asyncio.create_task(
                        save_results(self, reset_generation=get_reset_generation())
                    )
                )
                self._results_task = result_task
                results_saved = False
                try:
                    results_saved = await result_task
                except asyncio.CancelledError:
                    self.final_status = "cancelled"
                    self.final_message = "分析已取消"
                except Exception as exc:
                    self.final_status = "error"
                    self.final_message = str(exc)
                    mark_analysis_error_for_session(self, self.final_message)
                finally:
                    self._settling = False
                if self.final_status == "done" and not results_saved:
                    self.final_status = "error"
                    self.final_message = "报告保存失败"
                    mark_analysis_error_for_session(self, self.final_message)
            self._running = False
            if not self._terminal_event_published:
                self._terminal_event_published = True
                self._put_event(
                    {
                        "type": "session_end",
                        "status": self.final_status,
                        "text": self.final_message,
                    }
                )
            if self.final_status == "cancelled":
                mark_analysis_idle_for_session(self)
            self._finished_at = monotonic()
            _retain_session(self)
            self._done.set()
            if not self._log_closed:
                self._log_closed = True
                self._log_writer.close(final_status=self.final_status)

    async def _run_conversation(self):
        async def can_use_tool(tool_name: str, tool_input: dict, context: ToolPermissionContext):
            question = build_permission_question(tool_name, tool_input, context)
            answer, meta = await self._ask_question(question)
            response_text = normalize_answer(answer, question["default"])
            self._emit_user_response(question, response_text, meta)
            allow = response_text in AFFIRMATIVE_RESPONSES
            if allow:
                return PermissionResultAllow()
            message = "用户拒绝了本次工具调用"
            if meta.get("source") == "timeout":
                message = "超时后默认拒绝工具调用"
            return PermissionResultDeny(message=message, interrupt=False)

        options = ClaudeAgentOptions(
            permission_mode="bypassPermissions" if self.auto_respond else "default",
            skills=["stock-analyzer"],
            continue_conversation=False,
            cwd=ensure_reports_root(),
            allowed_tools=[
                "Bash", "Read", "Write", "Edit",
                "WebFetch", "WebSearch", "Glob", "Grep",
            ],
            can_use_tool=None if self.auto_respond else can_use_tool,
            include_partial_messages=True,
        )

        html_target_path = build_report_instruction_target(self.code, self.report_date)
        outgoing_message = (
            f"分析股票 {self.name}({self.code})，请生成完整分析报告。\n"
            "\n"
            "【一键式自动模式 — 强约束】\n"
            "1. 跳过 stock-analyzer skill 的 Step 0 登录引导，视为用户【已登录东方财富】，"
            "直接从Step 1 开始执行。\n"
            "2. 全程禁止向用户提出任何确认型问题（包括但不限于：\n"
            "   - “请问您是否已经登录东方财富”\n"
            "   - “是否继续 / 是否确认 / 请选择 / 请回复”\n"
            "   - 任何需要用户回答“是/否/继续/跳过”的提示）。\n"
            "   遇到需要决策的分支，按skill 的默认推荐路径继续执行，不要停下等待。\n"
            "3. 工具调用一律视为已授权，按 skill 内置默认参数直接调用，不要解释“是否使用某工具”。\n"
            "4. 失败处理：单次工具失败按 skill 重试一次，仍失败则在最终报告“数据来源状态”表格中""标注为【失败】并继续推进，不要中断流程，不要询问用户。\n"
            "5. 输出顺序固定：先在对话中完整输出 Markdown 报告 → 再生成 HTML 报告并写入 "
            f"`{html_target_path}`"
            "6. 全部完成后，仅追加一行：`__ANALYSIS_DONE__`，不要再问用户任何问题。\n"
        )
        self._put_event({"type": "status", "text": "正在启动分析会话..."})

        async with ClaudeSDKClient(options) as client:
            while self._running:
                await client.query(outgoing_message, session_id=self.session_id)
                next_user_reply: Optional[str] = None
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        reply = await self._handle_assistant_message(message)
                        if reply is not None:
                            next_user_reply = reply
                    elif isinstance(message, StreamEvent):
                        self._handle_stream_event(message)
                    elif isinstance(message, ResultMessage):
                        if message.is_error:
                            detail = message.result or "分析会话失败"
                            raise RuntimeError(detail)
                        break

                if not self._running:
                    return

                if self._should_check_html_after_turn(next_user_reply):
                    if self._handle_missing_html_after_turn(move_generated_report_html(self.code, self.report_date)):
                        outgoing_message = self._build_missing_html_retry_message()
                        continue
                    self._put_event({"type": "status", "text": "正在整理最终报告..."})
                    return

                if next_user_reply is None:
                    outgoing_message = self._build_completion_nudge_message()
                    continue

                outgoing_message = next_user_reply

    async def _handle_assistant_message(self, message: AssistantMessage) -> Optional[str]:
        text = "".join(block.text for block in message.content if isinstance(block, TextBlock)).strip()
        if not text:
            return None

        self.output_buffer += text + "\n"
        self._put_event({"type": "output", "text": text})
        if ANALYSIS_DONE_SENTINEL in text:
            self._analysis_done_seen = True

        question = classify_assistant_question(text)
        if not question:
            extracted = extract_report_markdown(self.output_buffer)
            if extracted:
                self.report_markdown = extracted
            return None

        answer, meta = await self._ask_question(question)
        response_text = normalize_answer(answer, question["default"])
        self._emit_user_response(question, response_text, meta)
        return response_text

    def _build_missing_html_retry_message(self) -> str:
        html_target_path = build_report_instruction_target(self.code, self.report_date)
        return (
            f"你还没有生成 HTML 文件。现在不要重写 Markdown 报告，也不要补充解释。\n"
            f"请只执行 HTML 生成步骤，并将文件写入后端指定的绝对路径 `{html_target_path}`。\n"
            "完成后仅输出 `__ANALYSIS_DONE__`。"
        )

    def _build_completion_nudge_message(self) -> str:
        if self._completion_nudge_count < MAX_COMPLETION_NUDGE_ATTEMPTS:
            self._completion_nudge_count += 1
            return (
                "分析流程尚未完成。请继续执行剩余步骤，不要提前结束。\n"
                "请先完整输出 Markdown 报告，再生成 HTML 报告并写入指定路径。\n"
                f"全部完成后仅输出 `{ANALYSIS_DONE_SENTINEL}`。"
            )

        self.final_status = "error"
        self.final_message = f"分析未收到完成信号 {ANALYSIS_DONE_SENTINEL}"
        mark_analysis_error_for_session(self, self.final_message)
        self._put_event({"type": "error", "text": self.final_message})
        self._running = False
        return ""

    def _should_check_html_after_turn(self, next_user_reply: Optional[str]) -> bool:
        return next_user_reply is None and self._analysis_done_seen and self._running

    def _handle_missing_html_after_turn(self, html_path: str) -> bool:
        if html_path:
            return False

        if self._html_retry_count < MAX_HTML_RETRY_ATTEMPTS:
            self._html_retry_count += 1
            self._put_event(
                {
                    "type": "status",
                    "text": "检测到 HTML 报告缺失，正在强制补生成一次...",
                }
            )
            return True

        self.final_message = "HTML报告缺失，已保存Markdown结果"
        self._put_event(
            {
                "type": "status",
                "text": self.final_message,
            }
        )
        return False

    def _handle_stream_event(self, message: StreamEvent):
        event = message.event or {}
        stream_type = event.get("type", "")
        if stream_type in {"task_progress", "task_notification"}:
            payload = event.get("data") or event
            text = payload.get("message") or payload.get("description") or ""
            action = payload.get("task_type") or payload.get("status") or "progress"
            if text:
                self._put_event({"type": "progress", "action": action, "text": text[:300]})
            return

        if stream_type in {"content_block_delta", "message_delta"}:
            return

        name = event.get("name") or event.get("tool_name")
        partial = event.get("partial") or event.get("text") or ""
        if name and partial:
            self._put_event({"type": "progress", "action": name, "text": partial[:300]})

    async def _ask_question(self, question: dict) -> tuple[str, dict]:
        default = question.get("default") or ""
        options = question.get("options") or []
        meta = {"source": "manual"}

        if self.auto_respond:
            self._put_event(
                {
                    "type": "question",
                    **question,
                    "auto": True,
                    "timeout_seconds": QUESTION_TIMEOUT_SECONDS,
                }
            )
            return default, {"source": "auto"}

        pending = UserResponse()
        self._pending_response = pending
        self._pending_question = question
        self._put_event(
            {
                "type": "question",
                **question,
                "auto": False,
                "timeout_seconds": QUESTION_TIMEOUT_SECONDS,
            }
        )

        response = await pending.wait(timeout=QUESTION_TIMEOUT_SECONDS)
        if response is None:
            meta = {"source": "timeout"}
            response = default

        self._pending_response = None
        self._pending_question = None
        return response, meta

    def _emit_user_response(self, question: dict, response_text: str, meta: dict):
        self._put_event(
            {
                "type": "user-response",
                "text": response_text,
                "question_kind": question["kind"],
                "auto": meta.get("source") != "manual",
            }
        )

    def respond(self, text: str) -> bool:
        pending = self._pending_response
        if pending is None:
            return False
        pending.set(text)
        return True

    def cancel(self) -> bool:
        if self._terminal_event_published:
            return False
        self._cancel_requested = True
        self.final_status = "cancelled"
        self.final_message = "分析已取消"
        self._running = False
        if self._pending_response is not None:
            self._pending_response.set("")
        return True

    def _resolve_terminal_status(self) -> str:
        if self._cancel_requested:
            return "cancelled"
        if self._analysis_done_seen:
            return "done"
        return "error"


def start_session(code: str, name: str, auto_respond: bool = False) -> Optional["InteractiveSession"]:
    _ensure_housekeeping()
    if not acquire_analysis_start_slot():
        return None

    session: Optional[InteractiveSession] = None
    try:
        with _accepting_lock:
            if not _accepting_new_tasks:
                return None
            with _sessions_lock:
                _prune_sessions_locked()
                if is_reset_in_progress():
                    return None
                existing = _active_sessions.get(code)
                if existing and not existing._cancel_requested and (
                    existing.is_running or existing.is_settling
                ):
                    return None
                session = InteractiveSession(code, name, auto_respond=auto_respond)
                _active_sessions[code] = session
    finally:
        release_analysis_start_slot()

    try:
        _persist_interactive_status(code, "running", run_mode="interactive")
        task = _track_task(asyncio.create_task(session.start()))
        session.set_task(task)
        return session
    except Exception:
        with _sessions_lock:
            if _active_sessions.get(code) is session:
                _active_sessions.pop(code, None)
        raise


def get_session(code: str) -> Optional["InteractiveSession"]:
    _ensure_housekeeping()
    with _sessions_lock:
        _prune_sessions_locked()
        return _active_sessions.get(code)


def respond_session(code: str, text: str) -> bool:
    session = get_session(code)
    if session:
        return session.respond(text)
    return False


def remove_session(code: str, session: Optional["InteractiveSession"] = None):
    with _sessions_lock:
        current = _active_sessions.get(code)
        if session is None:
            if current is not None and (current.is_running or current.is_settling):
                return
        elif current is not session:
            return
        if current is not None:
            _active_sessions.pop(code, None)


def _prune_sessions_locked() -> None:
    now = monotonic()
    expired = [
        code
        for code, session in _active_sessions.items()
        if not session.is_running
        and not session.is_settling
        and now - getattr(session, "_finished_at", now) >= INTERACTIVE_SESSION_TTL_SECONDS
    ]
    for code in expired:
        _active_sessions.pop(code, None)

    if len(_active_sessions) <= MAX_RETAINED_INTERACTIVE_SESSIONS:
        return
    finished = sorted(
        (
            (getattr(session, "_finished_at", now), code)
            for code, session in _active_sessions.items()
            if not session.is_running and not session.is_settling
        )
    )
    for _, code in finished[: max(0, len(_active_sessions) - MAX_RETAINED_INTERACTIVE_SESSIONS)]:
        _active_sessions.pop(code, None)


def _retain_session(session: InteractiveSession) -> None:
    with _sessions_lock:
        if _active_sessions.get(session.code) is session:
            _prune_sessions_locked()


def _session_is_current(session: InteractiveSession) -> bool:
    with _sessions_lock:
        return _active_sessions.get(session.code) is session


def mark_analysis_error_for_session(session: InteractiveSession, message: str):
    if _session_is_current(session):
        mark_analysis_error(session.code, message)


def mark_analysis_idle_for_session(session: InteractiveSession):
    if _session_is_current(session):
        mark_analysis_idle(session.code)


async def save_results(
    session: InteractiveSession,
    html_path: str = "",
    reset_generation: Optional[int] = None,
):
    from core.report_storage import save_report_summary
    from db.database import SessionLocal

    if session.final_status != "done" or not _session_is_current(session):
        return False

    if not acquire_analysis_start_slot():
        return False

    try:
        if is_reset_in_progress():
            return False
        if reset_generation is not None and reset_generation != get_reset_generation():
            return False
        if session.final_status != "done" or not _session_is_current(session):
            return False

        content = extract_report_markdown(session.report_markdown or session.output_buffer)
        if (
            not content
            or len(content.strip()) < 200
            or "<tool_use" in content
            or ("投资分析报告" not in content and "综合评分" not in content)
        ):
            mark_analysis_error_for_session(session, "模型未生成有效报告（疑似工具未启用）")
            return False

        final_html_path = html_path or move_generated_report_html(session.code, session.report_date)
        if session.final_status != "done" or not _session_is_current(session):
            return False

        db = SessionLocal()
        try:
            report = save_report_summary(
                db,
                session.code,
                content,
                final_html_path,
                session.report_date,
                session.report_time,
            )
        finally:
            db.close()

        if report is None:
            return False

        if session.final_status != "done" or not _session_is_current(session):
            return False
        _persist_interactive_status(
            session.code,
            "done",
            run_mode="interactive",
            message=session.final_message,
        )
        return True
    finally:
        release_analysis_start_slot()


async def shutdown_interactive_sessions(deadline: float) -> bool:
    set_accepting_new_tasks(False)
    with _sessions_lock:
        sessions = list(_active_sessions.values())
    for session in sessions:
        session.cancel()
    while True:
        tasks = get_background_tasks()
        if not tasks:
            return True
        timeout = max(0.0, deadline - monotonic())
        if timeout <= 0:
            for task in tasks:
                if not task.done():
                    task.cancel()
            return False
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending and monotonic() >= deadline:
            for task in pending:
                task.cancel()
            return False


def mark_analysis_running(code: str):
    _persist_interactive_status(code, "running", run_mode="interactive")


def mark_analysis_error(code: str, message: str):
    _persist_interactive_status(code, "error", run_mode="interactive", message=message)


def mark_analysis_idle(code: str):
    _persist_interactive_status(code, "cancelled", run_mode="interactive", message="分析已取消")


def _persist_interactive_status(code: str, status: str, run_mode: str = "", message: str = ""):
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        upsert_task_status(
            db,
            stock_code=code,
            analysis_date=shanghai_today(),
            status=status,
            status_message=message,
            run_mode=run_mode,
        )
    finally:
        db.close()
