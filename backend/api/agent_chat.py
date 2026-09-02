from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Portfolio, StockReport
from core.agent_runtime import (
    apply_llm_env_from_settings,
    build_holding_background,
    end_stream_session,
    get_or_create_executor,
    get_stream_session,
    is_runtime_accepting,
    list_skills,
    release_executor,
    start_stream_session,
)

router = APIRouter(tags=["agent-chat"])
_active_stream_consumers: dict[str, object] = {}
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


def _acquire_stream_consumer(session_id: str) -> Optional[object]:
    with _active_stream_consumers_lock:
        if session_id in _active_stream_consumers:
            return None
        token = object()
        _active_stream_consumers[session_id] = token
        return token


def _release_stream_consumer(session_id: str, token: Optional[object] = None) -> None:
    with _active_stream_consumers_lock:
        current = _active_stream_consumers.get(session_id)
        if current is not None and (token is None or current is token):
            _active_stream_consumers.pop(session_id, None)


@router.get("/agent/skills")
def get_skills():
    return {"skills": list_skills()}


@router.post("/agent/chat/start")
def start_chat(body: StartIn, db: Session = Depends(get_db)):
    if not is_runtime_accepting():
        return {"error": "服务正在关闭，请稍后重试"}
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

    operation_run_id = None
    try:
        sid = _session_id(body.stock_code, body.skill)
        operation_run_id = f"sync-{uuid.uuid4().hex}"
        executor = get_or_create_executor(sid, body.skill, run_id=operation_run_id)
        result = executor.chat(
            message=background,
            session_id=sid,
            context={"stock_code": body.stock_code},
        )
    except Exception as exc:
        return {"error": f"agent 启动失败: {exc}"}
    finally:
        if "sid" in locals() and operation_run_id is not None:
            release_executor(sid, run_id=operation_run_id)
    if not getattr(result, "success", False):
        return {"error": getattr(result, "error", None) or "agent 启动失败"}
    return {"session_id": sid, "background": background, "reply": result.content}


@router.post("/agent/chat/start-stream")
def start_chat_stream(body: StartIn, db: Session = Depends(get_db)):
    if not is_runtime_accepting():
        return {"error": "服务正在关闭，请稍后重试"}
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
    if not is_runtime_accepting():
        return {"error": "服务正在关闭，请稍后重试"}
    cfg_err = _ensure_llm_configured(db)
    if cfg_err:
        return {"error": cfg_err}

    try:
        operation_run_id = f"sync-{uuid.uuid4().hex}"
        executor = get_or_create_executor(
            body.session_id,
            body.skill,
            run_id=operation_run_id,
        )
        result = executor.chat(
            message=body.message,
            session_id=body.session_id,
            context={},
        )
    except Exception as exc:
        return {"error": f"agent 调用失败: {exc}"}
    finally:
        if "operation_run_id" in locals():
            release_executor(body.session_id, run_id=operation_run_id)
    if not getattr(result, "success", False):
        return {"error": getattr(result, "error", None) or "agent 调用失败"}
    return {"reply": result.content}


@router.get("/agent/chat/{session_id}/stream")
async def stream_chat(
    session_id: str,
    after_event_id: Optional[int] = Query(default=None, ge=0),
):
    async def event_generator():
        session = get_stream_session(session_id)
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

        consumer_token = _acquire_stream_consumer(session_id)
        if consumer_token is None:
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

        if get_stream_session(session_id) is not session:
            _release_stream_consumer(session_id, consumer_token)
            payload = json.dumps(
                {
                    "type": "diagnostic",
                    "code": "session_replaced",
                    "text": "会话已切换，请重新连接当前分析",
                },
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"
            return

        loop = None
        generation = None
        try:
            loop = asyncio.get_running_loop()
            replay = session.attach_loop(loop, after_event_id)
            generation = session.connection_generation
            for event in replay:
                event_id = event.get("event_id", "")
                prefix = f"id: {event_id}\n" if event_id else ""
                yield f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n"

            while True:
                event = await session.get_event(generation=generation)
                if event is None:
                    break
                if event.get("type") == "heartbeat":
                    yield ":ping\n\n"
                    continue
                event_id = event.get("event_id", "")
                prefix = f"id: {event_id}\n" if event_id else ""
                yield f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "session_end":
                    break
        finally:
            if generation is not None:
                session.detach_loop_for_generation(generation)
            _release_stream_consumer(session_id, consumer_token)

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
    return {"ok": True}
