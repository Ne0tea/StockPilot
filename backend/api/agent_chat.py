from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Portfolio, StockReport
from core.agent_runtime import (
    apply_llm_env_from_settings,
    build_holding_background,
    drop_executor,
    end_stream_session,
    get_or_create_executor,
    get_stream_session,
    list_skills,
    start_stream_session,
)

router = APIRouter(tags=["agent-chat"])
_active_stream_consumers: set[str] = set()
_active_stream_consumers_lock = threading.Lock()


class StartIn(BaseModel):
    stock_code: str
    skill: str


class MessageIn(BaseModel):
    session_id: str
    skill: str
    message: str


def _session_id(stock_code: str, skill: str) -> str:
    return f"agent-{stock_code}-{skill}"


def _latest_price(db: Session, code: str) -> Optional[float]:
    rep = (
        db.query(StockReport)
        .filter(StockReport.stock_code == code)
        .order_by(StockReport.date.desc(), StockReport.id.desc())
        .first()
    )
    return rep.current_price if rep else None


def _portfolio_total_cost(db: Session) -> float:
    rows = db.query(Portfolio).filter(Portfolio.status == "holding").all()
    return sum((r.shares or 0) * (r.cost_price or 0) for r in rows)


def _ensure_llm_configured(db: Session) -> Optional[str]:
    presence = apply_llm_env_from_settings(db)
    if (
        not presence.get("OPENAI_API_KEY")
        or not presence.get("OPENAI_BASE_URL")
        or not presence.get("OPENAI_MODEL")
    ):
        return "Agent LLM 未配置，请先在“设置”页填写 API Key / Base URL / 模型。"
    return None


def _build_start_context(db: Session, stock_code: str, skill: str) -> dict:
    pos = (
        db.query(Portfolio)
        .filter(Portfolio.stock_code == stock_code, Portfolio.status == "holding")
        .first()
    )
    if pos is None:
        return {"error": "该股票不在当前持仓中"}

    total_cost = _portfolio_total_cost(db)
    holding_cost = (pos.shares or 0) * (pos.cost_price or 0)
    position_pct = (holding_cost / total_cost * 100) if total_cost else 0.0
    current_price = _latest_price(db, stock_code)
    background = build_holding_background(
        stock_code=pos.stock_code,
        stock_name=pos.stock_name or "",
        shares=pos.shares or 0,
        cost_price=pos.cost_price or 0.0,
        current_price=current_price,
        buy_date=pos.buy_date,
        holding_cost=round(holding_cost, 2),
        position_pct=round(position_pct, 2),
        total_portfolio_cost=round(total_cost, 2),
    )
    return {
        "session_id": _session_id(stock_code, skill),
        "background": background,
        "stock_name": pos.stock_name or stock_code,
    }


def _acquire_stream_consumer(session_id: str) -> bool:
    with _active_stream_consumers_lock:
        if session_id in _active_stream_consumers:
            return False
        _active_stream_consumers.add(session_id)
        return True


def _release_stream_consumer(session_id: str) -> None:
    with _active_stream_consumers_lock:
        _active_stream_consumers.discard(session_id)


@router.get("/agent/skills")
def get_skills():
    return {"skills": list_skills()}


@router.post("/agent/chat/start")
def start_chat(body: StartIn, db: Session = Depends(get_db)):
    cfg_err = _ensure_llm_configured(db)
    if cfg_err:
        return {"error": cfg_err}

    pos = (
        db.query(Portfolio)
        .filter(Portfolio.stock_code == body.stock_code, Portfolio.status == "holding")
        .first()
    )
    if pos is None:
        return {"error": "该股票不在当前持仓中"}

    total_cost = _portfolio_total_cost(db)
    holding_cost = (pos.shares or 0) * (pos.cost_price or 0)
    position_pct = (holding_cost / total_cost * 100) if total_cost else 0.0
    current_price = _latest_price(db, body.stock_code)

    background = build_holding_background(
        stock_code=pos.stock_code,
        stock_name=pos.stock_name or "",
        shares=pos.shares or 0,
        cost_price=pos.cost_price or 0.0,
        current_price=current_price,
        buy_date=pos.buy_date,
        holding_cost=round(holding_cost, 2),
        position_pct=round(position_pct, 2),
        total_portfolio_cost=round(total_cost, 2),
    )

    sid = _session_id(body.stock_code, body.skill)
    executor = get_or_create_executor(sid, body.skill)
    try:
        result = executor.chat(
            message=background,
            session_id=sid,
            context={"stock_code": body.stock_code},
        )
    except Exception as exc:
        drop_executor(sid)
        return {"error": f"agent 启动失败: {exc}"}

    if not getattr(result, "success", False):
        drop_executor(sid)
        return {"error": getattr(result, "error", None) or "agent 启动失败"}
    return {
        "session_id": sid,
        "background": background,
        "reply": result.content,
    }


@router.post("/agent/chat/start-stream")
def start_chat_stream(body: StartIn, db: Session = Depends(get_db)):
    cfg_err = _ensure_llm_configured(db)
    if cfg_err:
        return {"error": cfg_err}

    context = _build_start_context(db, body.stock_code, body.skill)
    if context.get("error"):
        return {"error": context["error"]}

    return start_stream_session(
        session_id=context["session_id"],
        stock_code=body.stock_code,
        stock_name=context["stock_name"],
        skill=body.skill,
        background_prompt=context["background"],
    )


@router.post("/agent/chat/message")
def send_message(body: MessageIn, db: Session = Depends(get_db)):
    cfg_err = _ensure_llm_configured(db)
    if cfg_err:
        return {"error": cfg_err}

    executor = get_or_create_executor(body.session_id, body.skill)
    try:
        result = executor.chat(
            message=body.message,
            session_id=body.session_id,
            context={},
        )
    except Exception as exc:
        return {"error": f"agent 调用失败: {exc}"}

    if not getattr(result, "success", False):
        return {"error": getattr(result, "error", None) or "agent 调用失败"}
    return {"reply": result.content}


@router.get("/agent/chat/{session_id}/stream")
async def stream_chat(session_id: str):
    session = get_stream_session(session_id)

    async def event_generator():
        if session is None:
            payload = json.dumps(
                {
                    "type": "diagnostic",
                    "code": "session_not_found",
                    "text": "会话不存在，请先发起分析",
                },
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"
            return

        if not _acquire_stream_consumer(session_id):
            payload = json.dumps(
                {
                    "type": "diagnostic",
                    "code": "stream_busy",
                    "text": "当前会话已有活跃连接，请稍后重试",
                },
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"
            return

        try:
            session.attach_loop(asyncio.get_running_loop())
            for event in session.snapshot_events():
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            while True:
                event = await session.get_event()
                if event is None:
                    break
                if event.get("type") == "heartbeat":
                    yield ":ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "session_end":
                    break
        finally:
            _release_stream_consumer(session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/agent/chat/{session_id}")
def end_chat(session_id: str):
    end_stream_session(session_id)
    drop_executor(session_id)
    return {"ok": True}
