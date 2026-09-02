"""Bridge module: makes backend/core/src/ agent SDK callable from FastAPI.

Mirrors the pattern in backend/core/Test_agent_skill.py.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_CORE_DIR = Path(__file__).resolve().parent
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

os.environ.setdefault("AGENT_ARCH", "multi")
os.environ.setdefault("AGENT_ORCHESTRATOR_MODE", "specialist")

from src.config import get_config  # noqa: E402
from src.agent.factory import build_agent_executor, get_skill_manager  # noqa: E402
try:
    from core.agent_stream_session import AgentRunSession  # noqa: E402
except ModuleNotFoundError:  # Supports importing the backend as a package in tests/tools.
    from backend.core.agent_stream_session import AgentRunSession  # noqa: E402

_lock = threading.Lock()
_executors: Dict[str, Any] = {}
_stream_sessions: Dict[str, AgentRunSession] = {}
_stream_lock = threading.Lock()
_executor_meta: Dict[str, dict] = {}
_TERMINAL_SESSION_TTL_SECONDS = 30 * 60
_MAX_TERMINAL_SESSIONS = 256
_EXECUTOR_IDLE_TTL_SECONDS = 30 * 60
_MAX_EXECUTORS = 256
_config_generation = 0
_accepting = True
_housekeeping_stop = threading.Event()
_housekeeping_thread: Optional[threading.Thread] = None
_run_threads: Dict[str, threading.Thread] = {}


_AGENT_LLM_ENV_KEYS = {
    "agent_api_key": "OPENAI_API_KEY",
    "agent_base_url": "OPENAI_BASE_URL",
    "agent_model": "OPENAI_MODEL",
}


def apply_llm_env_from_settings(db) -> Dict[str, bool]:
    """Push the user-saved Agent LLM credentials into os.environ.

    Resetting configuration affects only executors created by later runs.
    """
    from db.models import Settings as SettingsModel

    row = db.query(SettingsModel).first()
    presence: Dict[str, bool] = {v: False for v in _AGENT_LLM_ENV_KEYS.values()}
    changed = False
    if row is not None:
        for col, env_key in _AGENT_LLM_ENV_KEYS.items():
            val = (getattr(row, col, None) or "").strip()
            if val:
                if os.environ.get(env_key) != val:
                    changed = True
                os.environ[env_key] = val
                presence[env_key] = True
            elif os.environ.get(env_key):
                presence[env_key] = True

    if changed:
        global _config_generation
        with _lock:
            _config_generation += 1
        try:
            from src.config import Config as _Config
            _Config.reset_instance()
        except Exception:
            pass
    return presence


def list_skills() -> List[Dict[str, str]]:
    mgr = get_skill_manager(get_config())
    out = []
    for skill in mgr.list_skills():
        out.append({
            "name": getattr(skill, "name", ""),
            "display_name": getattr(skill, "display_name", "") or getattr(skill, "name", ""),
            "description": getattr(skill, "description", "") or "",
            "category": getattr(skill, "category", "") or "",
        })
    out.sort(key=lambda s: (s["category"], s["display_name"]))
    return out


def _close_executor(executor: Any) -> None:
    for method_name in ("close", "shutdown"):
        method = getattr(executor, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
            break


def _ensure_housekeeping() -> None:
    global _housekeeping_thread
    with _stream_lock:
        if not _accepting:
            return
    with _lock:
        if _housekeeping_thread is not None and _housekeeping_thread.is_alive():
            return
        _housekeeping_stop.clear()
        _housekeeping_thread = threading.Thread(
            target=_housekeeping_loop,
            name="agent-runtime-housekeeping",
            daemon=True,
        )
        _housekeeping_thread.start()


def _housekeeping_loop() -> None:
    while not _housekeeping_stop.wait(60.0):
        try:
            reap_agent_sessions()
        except Exception:
            pass


def get_or_create_executor(session_id: str, skill: str, *, run_id: Optional[str] = None):
    _ensure_housekeeping()
    stale_executor = None
    reaped_executors = []
    try:
        with _lock:
            ex = _executors.get(session_id)
            meta = _executor_meta.get(session_id)
            active_runs = meta.get("active_runs", set()) if meta else set()
            sync_calls = meta.get("sync_calls", 0) if meta else 0
            if ex is not None and (
                (run_id is not None and (active_runs - {run_id} or sync_calls))
                or (run_id is None and active_runs)
            ):
                raise RuntimeError("Agent executor is busy")

            if ex is not None and not active_runs and not sync_calls and (
                meta is None
                or meta.get("config_generation", _config_generation) != _config_generation
            ):
                stale_executor = _executors.pop(session_id)
                _executor_meta.pop(session_id, None)
                ex = None

            if ex is None:
                if len(_executors) >= _MAX_EXECUTORS:
                    reaped_executors = _reap_executors_locked()
                if len(_executors) >= _MAX_EXECUTORS:
                    raise RuntimeError("Agent executor capacity reached")
                ex = build_agent_executor(get_config(), skills=[skill])
                _executors[session_id] = ex
                meta = {"active_runs": set(), "sync_calls": 0, "config_generation": _config_generation}
                _executor_meta[session_id] = meta

            meta = _executor_meta.setdefault(
                session_id,
                {"active_runs": set(), "sync_calls": 0, "config_generation": _config_generation},
            )
            meta.setdefault("active_runs", set())
            meta.setdefault("sync_calls", 0)
            meta.setdefault("config_generation", _config_generation)
            if run_id is not None:
                meta["run_id"] = run_id
                meta["active_runs"].add(run_id)
            else:
                meta["sync_calls"] += 1
            meta["last_used"] = time.monotonic()
            meta["active"] = True
            result = ex
    finally:
        if stale_executor is not None:
            _close_executor(stale_executor)
        for executor in reaped_executors:
            _close_executor(executor)
    return result


def drop_executor(session_id: str, *, run_id: Optional[str] = None) -> None:
    executor = None
    with _lock:
        meta = _executor_meta.get(session_id)
        if run_id is not None:
            if not meta or meta.get("run_id") != run_id:
                return
        if meta and (meta.get("active_runs", set()) or meta.get("sync_calls", 0)):
            return
        executor = _executors.pop(session_id, None)
        _executor_meta.pop(session_id, None)
    if executor is not None:
        _close_executor(executor)


def release_executor(session_id: str, *, run_id: Optional[str] = None) -> None:
    """Mark an executor idle while retaining it for follow-up requests."""
    with _lock:
        meta = _executor_meta.get(session_id)
        if meta is None:
            return
        if run_id is not None:
            active_runs = meta.setdefault("active_runs", set())
            if run_id not in active_runs:
                return
            active_runs.discard(run_id)
        elif meta.get("sync_calls", 0):
            meta["sync_calls"] -= 1
        meta["active"] = bool(meta.get("active_runs")) or bool(meta.get("sync_calls"))
        meta["last_used"] = time.monotonic()


def _reap_executors_locked(now: Optional[float] = None) -> list[Any]:
    now = time.monotonic() if now is None else now
    executors = []
    stale = [
        session_id for session_id, meta in _executor_meta.items()
        if not meta.get("active") and now - meta.get("last_used", now) >= _EXECUTOR_IDLE_TTL_SECONDS
    ]
    for session_id in stale:
        executor = _executors.pop(session_id, None)
        _executor_meta.pop(session_id, None)
        if executor is not None:
            executors.append(executor)
    return executors


def reap_agent_sessions(now: Optional[datetime] = None) -> int:
    cutoff = (now or datetime.now()) - timedelta(seconds=_TERMINAL_SESSION_TTL_SECONDS)
    removed = 0
    with _stream_lock:
        stale = [
            (session_id, session)
            for session_id, session in _stream_sessions.items()
            if session.is_finished and session.finished_at
            and _finished_before(session, cutoff)
        ]
        for session_id, session in stale:
            _stream_sessions.pop(session_id, None)
            removed += 1
        finished = sorted(
            (
                (session.finished_at, session_id, session)
                for session_id, session in _stream_sessions.items()
                if session.is_finished and session.finished_at
            ),
            key=lambda item: item[0],
        )
        if len(finished) > _MAX_TERMINAL_SESSIONS:
            excess = len(finished) - _MAX_TERMINAL_SESSIONS
            for _, session_id, _ in finished[:excess]:
                _stream_sessions.pop(session_id, None)
                removed += 1
    with _lock:
        reaped_executors = _reap_executors_locked()
    for executor in reaped_executors:
        _close_executor(executor)
    return removed


def _finished_before(session: AgentRunSession, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(session.finished_at) < cutoff
    except (TypeError, ValueError):
        return False


def set_runtime_accepting(value: bool) -> None:
    global _accepting
    with _stream_lock:
        _accepting = value


def is_runtime_accepting() -> bool:
    with _stream_lock:
        return _accepting


def shutdown_agent_runtime() -> None:
    _housekeeping_stop.set()
    with _stream_lock:
        global _accepting
        _accepting = False
        sessions = list(_stream_sessions.values())
    for session in sessions:
        if not session.is_finished:
            end_stream_session(session.session_id)


def wait_for_agent_runtime(timeout: float = 0.0) -> bool:
    """Wait until active Agent sessions reach a terminal state."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        with _stream_lock:
            active = [thread for thread in _run_threads.values() if thread.is_alive()]
        if not active:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


def close_agent_executors() -> None:
    """Close idle executors after callers have waited for active runs."""
    with _lock:
        idle_ids = [
            session_id
            for session_id, meta in _executor_meta.items()
            if not meta.get("active")
        ]
        idle_ids.extend(
            session_id for session_id in _executors if session_id not in _executor_meta
        )
        executors = []
        for session_id in idle_ids:
            executor = _executors.pop(session_id, None)
            _executor_meta.pop(session_id, None)
            if executor is not None:
                executors.append(executor)
    for executor in executors:
        _close_executor(executor)


def _cleanup_stream_session(session_id: str, *, run_id: Optional[str] = None) -> None:
    release_executor(session_id, run_id=run_id)


def _complete_stream_session(
    session: AgentRunSession,
    *,
    status: str,
    text: str,
    diagnostic: Optional[dict] = None,
    final_result: Optional[str] = None,
) -> bool:
    with _stream_lock:
        active = _stream_sessions.get(session.session_id)
        if session.is_finished or active is not session:
            return False

    # Release the completed run before exposing the terminal session. This
    # closes the small window where a caller could restart a finished session
    # while its previous executor was still marked active. The executor is
    # retained as an idle follow-up resource until its TTL expires.
    _cleanup_stream_session(session.session_id, run_id=session.run_id)
    return session.finish(
        status=status,
        text=text,
        diagnostic=diagnostic,
        final_result=final_result,
    )


def get_stream_session(session_id: str) -> Optional[AgentRunSession]:
    _ensure_housekeeping()
    reap_agent_sessions()
    with _stream_lock:
        return _stream_sessions.get(session_id)


def end_stream_session(session_id: str) -> None:
    with _stream_lock:
        session = _stream_sessions.get(session_id)
    if session is not None and session.request_cancel():
        session.publish({
            "type": "diagnostic",
            "code": "cancelling",
            "text": "已请求取消，正在等待后台调用结束",
        })


def _build_progress_event(progress: dict) -> Optional[dict]:
    event_type = progress.get("type")
    if event_type == "stage_start":
        return {"type": "stage", "stage": progress.get("stage", ""), "status": "started", "text": progress.get("message", "")}
    if event_type == "stage_done":
        return {"type": "stage", "stage": progress.get("stage", ""), "status": progress.get("status", "completed"), "duration": progress.get("duration", 0)}
    if event_type == "tool_start":
        return {"type": "tool", "tool": progress.get("tool", ""), "status": "started"}
    if event_type == "tool_done":
        return {
            "type": "tool",
            "tool": progress.get("tool", ""),
            "status": "completed" if progress.get("success") else "failed",
            "duration": progress.get("duration", 0),
        }
    if event_type in {"pipeline_timeout", "budget_skip"}:
        return {"type": "diagnostic", "code": event_type, "text": str(progress)}
    if event_type == "thinking":
        return {"type": "status", "text": progress.get("message", "")}
    return None


def _finalize_stream_result(session: AgentRunSession, result) -> None:
    if session.is_finished:
        return
    if session.cancel_requested:
        _complete_stream_session(
            session,
            status="cancelled",
            text="分析已取消",
            diagnostic={"type": "diagnostic", "code": "cancelled", "text": "用户已取消本次专项分析"},
        )
        return

    if not getattr(result, "success", False):
        _complete_stream_session(
            session,
            status="error",
            text=getattr(result, "error", None) or "agent 启动失败",
            diagnostic={
                "type": "diagnostic",
                "code": "executor_error",
                "text": getattr(result, "error", None) or "agent 启动失败",
            },
        )
        return

    content = (getattr(result, "content", "") or "").strip()
    if not content:
        _complete_stream_session(
            session,
            status="error",
            text="本次专项分析未生成有效结论",
            diagnostic={
                "type": "diagnostic",
                "code": "empty_result",
                "text": "本次专项分析未生成有效结论，请展开执行详情查看诊断信息。",
            },
        )
        return

    _complete_stream_session(
        session,
        status="done",
        text=content,
        final_result=content,
    )


def start_stream_session(*, session_id: str, stock_code: str, stock_name: str, skill: str, background_prompt: str) -> dict:
    _ensure_housekeeping()
    reap_agent_sessions()
    with _stream_lock:
        if not _accepting:
            return {"ok": False, "error": "服务正在关闭，请稍后重试", "session_id": session_id}
        existing = _stream_sessions.get(session_id)
        if existing and not existing.is_finished:
            return {
                "ok": False,
                "error": "当前专项分析仍在运行，请稍候再试。",
                "session_id": session_id,
            }

        run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        session = AgentRunSession(
            session_id=session_id,
            run_id=run_id,
            stock_code=stock_code,
            skill=skill,
            background_prompt=background_prompt,
        )
        _stream_sessions[session_id] = session

    session.publish({"type": "prompt", "text": background_prompt, "skill": skill, "stock_code": stock_code})
    session.publish({"type": "status", "text": "会话已创建"})
    session.publish({"type": "status", "text": "正在加载技能"})
    session.publish({"type": "status", "text": "正在构建持仓上下文"})
    session.publish({"type": "status", "text": "正在启动 specialist 流程"})

    def _runner():
        def _progress(progress: dict):
            if session.cancel_requested or session.is_finished:
                return
            event = _build_progress_event(progress)
            if event:
                session.publish(event)

        try:
            executor = get_or_create_executor(session_id, skill, run_id=session.run_id)
            if session.cancel_requested:
                _complete_stream_session(
                    session,
                    status="cancelled",
                    text="分析已取消",
                    diagnostic={"type": "diagnostic", "code": "cancelled", "text": "用户已取消本次专项分析"},
                )
                return
            result = executor.chat(
                message=background_prompt,
                session_id=session_id,
                progress_callback=_progress,
                context={"stock_code": stock_code},
            )
        except BaseException as exc:
            status = "cancelled" if session.cancel_requested else "error"
            text = "分析已取消" if session.cancel_requested else f"agent 启动失败: {exc}"
            code = "cancelled" if session.cancel_requested else "executor_error"
            _complete_stream_session(
                session,
                status=status,
                text=text,
                diagnostic={"type": "diagnostic", "code": code, "text": text},
            )
        else:
            try:
                _finalize_stream_result(session, result)
            except Exception as exc:
                _complete_stream_session(
                    session,
                    status="cancelled" if session.cancel_requested else "error",
                    text="分析已取消" if session.cancel_requested else f"agent 启动失败: {exc}",
                    diagnostic={
                        "type": "diagnostic",
                        "code": "cancelled" if session.cancel_requested else "executor_error",
                        "text": "分析已取消" if session.cancel_requested else f"agent 启动失败: {exc}",
                    },
                )
        finally:
            _cleanup_stream_session(session.session_id, run_id=session.run_id)
            with _stream_lock:
                if _run_threads.get(session.run_id) is threading.current_thread():
                    _run_threads.pop(session.run_id, None)

    runner_thread = threading.Thread(
        target=_runner,
        daemon=True,
        name=f"agent-stream-{session_id}-{run_id}",
    )
    with _stream_lock:
        _run_threads[run_id] = runner_thread
    try:
        runner_thread.start()
    except BaseException as exc:
        with _stream_lock:
            _run_threads.pop(run_id, None)
        _complete_stream_session(
            session,
            status="error",
            text=f"agent 启动失败: {exc}",
            diagnostic={"type": "diagnostic", "code": "executor_error", "text": f"agent 启动失败: {exc}"},
        )

    return {
        "ok": True,
        "session_id": session_id,
        "run_id": run_id,
        "status": "accepted",
        "background_prompt": background_prompt,
        "started_at": session.started_at,
    }


def build_holding_background(
    *, stock_code: str, stock_name: str, shares: int,
    cost_price: float, current_price: Optional[float],
    buy_date: Optional[date], holding_cost: float,
    position_pct: float, total_portfolio_cost: float,
) -> str:
    today = date.today()
    holding_days = (today - buy_date).days if buy_date else None
    pnl = None
    pnl_pct = None
    if current_price is not None and cost_price:
        pnl = round((current_price - cost_price) * shares, 2)
        pnl_pct = round((current_price - cost_price) / cost_price * 100, 2)

    lines = ["【持仓背景】请基于以下持仓信息进行专项分析："]
    lines.append(f"- 股票：{stock_name}（{stock_code}）")
    lines.append(f"- 持股数：{shares}")
    lines.append(f"- 成本价：{cost_price:.3f}" if cost_price else "- 成本价：未知")
    lines.append(
        f"- 现价：{current_price:.3f}" if current_price is not None else "- 现价：暂无最新报告"
    )
    lines.append(f"- 持仓成本：¥{holding_cost:.2f}（占组合 {position_pct:.2f}%）")
    if buy_date:
        lines.append(
            f"- 买入日期：{buy_date.isoformat()}（持有 {holding_days} 天）"
        )
    else:
        lines.append("- 买入日期：未知")
    lines.append(
        f"- 浮动盈亏：¥{pnl} ({pnl_pct:+.2f}%)"
        if pnl is not None
        else "- 浮动盈亏：暂无现价"
    )
    lines.append("")
    lines.append(
        "请结合所选策略分析当前持仓状态，给出 持有/加仓/减仓/卖出 建议、关键支撑/止损位，"
        "以及后续可追问的关注点。"
    )
    return "\n".join(lines)
