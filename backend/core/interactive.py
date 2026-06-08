"""Interactive stock analysis session using ClaudeSDKClient multi-turn flow."""

import asyncio
import json
import threading
from datetime import date
from typing import Optional

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
    ensure_reports_root,
    extract_report_markdown,
    move_generated_report_html,
)
from core.session_logger import SessionLogWriter


QUESTION_TIMEOUT_SECONDS = 30.0

LOGIN_QUESTION_OPTIONS = ["已登录", "继续分析", "跳过"]
AFFIRMATIVE_RESPONSES = {"已登录", "继续分析", "登录了", "allow", "允许", "yes", "y"}
NEGATIVE_RESPONSES = {"跳过", "没登录", "未登录", "不想登录", "deny", "拒绝", "no", "n"}


# Active sessions: {code: InteractiveSession}
_active_sessions: dict[str, "InteractiveSession"] = {}
_sessions_lock = threading.Lock()

_bulk_pending: list[tuple[str, str]] = []   # FIFO of (code, name) not yet started
_bulk_queued_codes: list[str] = []          # codes still waiting (snapshot view)
_bulk_running_code: Optional[str] = None
_bulk_running_name: str = ""
_bulk_lock = threading.Lock()
_bulk_dispatcher_running = False


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
        self.session_id = f"stock_{code}_{date.today().isoformat()}"
        self.output_buffer = ""
        self.report_markdown = ""
        self._events: asyncio.Queue = asyncio.Queue()
        self._done = asyncio.Event()
        self._running = True
        self._cancel_requested = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending_response: Optional[UserResponse] = None
        self._pending_question: Optional[dict] = None
        self.final_status = "running"
        self.final_message = ""
        self._results_task_started = False
        self._log_writer = SessionLogWriter(
            reports_root=ensure_reports_root(),
            code=code,
            date_str=date.today().isoformat(),
        )
        self._log_writer_name = name
        self._log_writer_auto_respond = auto_respond

    @property
    def is_running(self) -> bool:
        return self._running

    async def get_event(self) -> Optional[dict]:
        try:
            return await asyncio.wait_for(self._events.get(), timeout=15.0)
        except asyncio.TimeoutError:
            if self._done.is_set():
                return None
            return {"type": "heartbeat"}

    def _put_event(self, event: dict):
        self._log_writer.append(event)
        async def _enqueue():
            await self._events.put(event)

        if self._event_loop and self._event_loop.is_running():
            asyncio.run_coroutine_threadsafe(_enqueue(), self._event_loop)
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_enqueue())

    async def start(self):
        self._event_loop = asyncio.get_running_loop()
        self._log_writer.open(name=self._log_writer_name, auto_respond=self._log_writer_auto_respond)
        try:
            await self._run_conversation()
            if self.final_status == "running":
                self.final_status = "cancelled" if self._cancel_requested else "done"
        except Exception as exc:
            self.final_status = "error"
            self.final_message = str(exc)
            mark_analysis_error(self.code, str(exc))
            self._put_event({"type": "error", "text": str(exc)})
        finally:
            self._running = False
            self._put_event(
                {
                    "type": "session_end",
                    "status": self.final_status,
                    "text": self.final_message,
                }
            )
            if self.final_status == "done" and not self._results_task_started:
                self._results_task_started = True
                asyncio.create_task(save_results(self, reset_generation=get_reset_generation()))
            elif self.final_status == "cancelled":
                mark_analysis_idle(self.code)
            remove_session(self.code)
            self._done.set()
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
            "5. 输出顺序固定：先在对话中完整输出 Markdown 报告 → 再生成 HTML 报告并写入当前工作目录下的 "
            f"`{self.code}/{date.today().isoformat()}.html`"
            "（当前工作目录就是 reports 根目录；禁止再额外套一层 reports/ 子目录）。\n"
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

                if next_user_reply is None:
                    self._put_event({"type": "status", "text": "正在整理最终报告..."})
                    return

                outgoing_message = next_user_reply

    async def _handle_assistant_message(self, message: AssistantMessage) -> Optional[str]:
        text = "".join(block.text for block in message.content if isinstance(block, TextBlock)).strip()
        if not text:
            return None

        self.output_buffer += text + "\n"
        self._put_event({"type": "output", "text": text})

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

    def cancel(self):
        self._cancel_requested = True
        self.final_status = "cancelled"
        self.final_message = "分析已取消"
        self._running = False
        if self._pending_response is not None:
            self._pending_response.set("")


def start_session(code: str, name: str, auto_respond: bool = False) -> Optional["InteractiveSession"]:
    if not acquire_analysis_start_slot():
        return None

    with _sessions_lock:
        try:
            if is_reset_in_progress():
                return None
            existing = _active_sessions.get(code)
            if existing and existing.is_running:
                return None
            session = InteractiveSession(code, name, auto_respond=auto_respond)
            _active_sessions[code] = session
        finally:
            release_analysis_start_slot()

    _persist_interactive_status(code, "running", run_mode="interactive")
    asyncio.create_task(session.start())
    return session


def get_session(code: str) -> Optional["InteractiveSession"]:
    with _sessions_lock:
        return _active_sessions.get(code)


def respond_session(code: str, text: str) -> bool:
    session = get_session(code)
    if session:
        return session.respond(text)
    return False


def remove_session(code: str):
    with _sessions_lock:
        _active_sessions.pop(code, None)


async def save_results(
    session: InteractiveSession,
    html_path: str = "",
    reset_generation: Optional[int] = None,
):
    from core.analyzer import save_report_summary
    from db.database import SessionLocal

    if session.final_status != "done":
        return

    if not acquire_analysis_start_slot():
        return

    try:
        if is_reset_in_progress():
            return
        if reset_generation is not None and reset_generation != get_reset_generation():
            return

        content = extract_report_markdown(session.report_markdown or session.output_buffer)
        if (
            not content
            or len(content.strip()) < 200
            or "<tool_use" in content
            or ("投资分析报告" not in content and "综合评分" not in content)
        ):
            mark_analysis_error(session.code, "模型未生成有效报告（疑似工具未启用）")
            return

        final_html_path = html_path or move_generated_report_html(session.code)

        db = SessionLocal()
        try:
            report = save_report_summary(db, session.code, content, final_html_path)
        finally:
            db.close()

        if report is None:
            return

        _persist_interactive_status(session.code, "done", run_mode="interactive")
    finally:
        release_analysis_start_slot()


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
