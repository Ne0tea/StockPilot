"""Bridge module: makes backend/core/src/ agent SDK callable from FastAPI.

Mirrors the pattern in backend/core/Test_agent_skill.py.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_CORE_DIR = Path(__file__).resolve().parent
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

os.environ.setdefault("AGENT_ARCH", "multi")
os.environ.setdefault("AGENT_ORCHESTRATOR_MODE", "specialist")

from src.config import get_config  # noqa: E402
from src.agent.factory import build_agent_executor, get_skill_manager  # noqa: E402
from core.agent_stream_session import AgentRunSession  # noqa: E402

_lock = threading.Lock()
_executors: Dict[str, Any] = {}
_stream_sessions: Dict[str, AgentRunSession] = {}
_stream_lock = threading.Lock()


_AGENT_LLM_ENV_KEYS = {
    "agent_api_key": "OPENAI_API_KEY",
    "agent_base_url": "OPENAI_BASE_URL",
    "agent_model": "OPENAI_MODEL",
}


def apply_llm_env_from_settings(db) -> Dict[str, bool]:
    """Push the user-saved Agent LLM credentials into os.environ.

    Also invalidates the Config singleton + cached executors so that the
    next chat call rebuilds with the fresh credentials.
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
        try:
            from src.config import Config as _Config
            _Config.reset_instance()
        except Exception:
            pass
        with _lock:
            _executors.clear()
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


def get_or_create_executor(session_id: str, skill: str):
    with _lock:
        ex = _executors.get(session_id)
        if ex is None:
            ex = build_agent_executor(get_config(), skills=[skill])
            _executors[session_id] = ex
        return ex


def drop_executor(session_id: str) -> None:
    with _lock:
        _executors.pop(session_id, None)


def _cleanup_stream_session(session_id: str) -> None:
    drop_executor(session_id)


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
        _stream_sessions.pop(session.session_id, None)

    if diagnostic is not None:
        session.publish(diagnostic)
    if final_result is not None:
        session.publish({"type": "final_result", "text": final_result})
    session.mark_finished(status=status, text=text)
    _cleanup_stream_session(session.session_id)
    return True


def get_stream_session(session_id: str) -> Optional[AgentRunSession]:
    with _stream_lock:
        return _stream_sessions.get(session_id)


def end_stream_session(session_id: str) -> None:
    with _stream_lock:
        session = _stream_sessions.get(session_id)
    if session is not None:
        session.cancel_requested = True
        _complete_stream_session(
            session,
            status="cancelled",
            text="分析已取消",
            diagnostic={"type": "diagnostic", "code": "cancelled", "text": "用户已取消本次专项分析"},
        )


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
    if session.cancel_requested or session.is_finished:
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
    with _stream_lock:
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
        executor = get_or_create_executor(session_id, skill)

        def _progress(progress: dict):
            if session.cancel_requested or session.is_finished:
                return
            event = _build_progress_event(progress)
            if event:
                session.publish(event)

        try:
            result = executor.chat(
                message=background_prompt,
                session_id=session_id,
                progress_callback=_progress,
                context={"stock_code": stock_code},
            )
        except Exception as exc:
            _complete_stream_session(
                session,
                status="error",
                text=f"agent 启动失败: {exc}",
                diagnostic={"type": "diagnostic", "code": "executor_error", "text": f"agent 启动失败: {exc}"},
            )
            return

        _finalize_stream_result(session, result)

    threading.Thread(target=_runner, daemon=True, name=f"agent-stream-{session_id}").start()

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
