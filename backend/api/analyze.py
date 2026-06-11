import json
import re
from datetime import date as _date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.analysis_task_state import get_task_status_for_code
from core.analysis_cleanup import clear_today_analysis_artifacts
from core.interactive import (
    get_session,
    remove_session,
    respond_session,
    start_session,
)
from core.report_listing import list_reports, rescan_reports
from core.report_storage import save_report_html, save_report_summary
from core.stock_reset import acquire_analysis_start_slot, is_reset_in_progress, release_analysis_start_slot
from db.database import get_db
from db.models import StockReport, Watchlist

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
router = APIRouter(tags=["analyze"])

class ReportIn(BaseModel):
    markdown: str
    html: Optional[str] = ""

class InteractIn(BaseModel):
    response: str

class InteractiveStartIn(BaseModel):
    auto_respond: bool = False

@router.get("/analyze/{code}/status")
def check_status(code: str, db: Session = Depends(get_db)):
    status, status_date = get_task_status_for_code(db, code)
    return {
        "code": code,
        "status": status,
        "status_date": status_date.isoformat(),
    }

@router.post("/analyze/{code}/report")
def submit_report(code: str, body: ReportIn, db: Session = Depends(get_db)):
    if is_reset_in_progress():
        return {"error": "系统正在初始化，请稍后重试"}
    if not acquire_analysis_start_slot():
        return {"error": "系统正在初始化，请稍后重试"}
    try:
        if is_reset_in_progress():
            return {"error": "系统正在初始化，请稍后重试"}
        html_path = ""
        if body.html:
            html_path = save_report_html(code, body.html)
        report = save_report_summary(db, code, body.markdown, html_path)
        if report is None:
            return {"error": "系统正在初始化，请稍后重试"}
        return {"ok": True, "report_id": report.id}
    finally:
        release_analysis_start_slot()

@router.get("/reports")
def get_all_reports(code: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    return list_reports(db, code=code or None, limit=limit)


@router.post("/reports/rescan")
def rescan_reports_endpoint(code: Optional[str] = None, db: Session = Depends(get_db)):
    return rescan_reports(db, code=code or None)


@router.get("/reports/{code}")
def get_reports(code: str, limit: int = 30, db: Session = Depends(get_db)):
    return list_reports(db, code=code, limit=limit)

@router.get("/reports/{code}/latest")
def get_latest_report(code: str, db: Session = Depends(get_db)):
    return db.query(StockReport).filter(
        StockReport.stock_code == code
    ).order_by(StockReport.date.desc()).first()


@router.post("/analyze/{code}/interactive")
async def start_interactive(
    code: str,
    body: Optional[InteractiveStartIn] = None,
    db: Session = Depends(get_db),
):
    """Start an interactive analysis session via claude-agent-sdk."""
    if is_reset_in_progress():
        return {"error": "系统正在初始化，请稍后重试"}
    stock = db.query(Watchlist).filter(Watchlist.stock_code == code, Watchlist.is_active == True).first()
    if not stock:
        return {"error": "Stock not in watchlist"}
    auto_respond = body.auto_respond if body else False
    session = start_session(code, stock.name, auto_respond=auto_respond)
    if session is None:
        if is_reset_in_progress():
            return {"error": "系统正在初始化，请稍后重试"}
        return {"status": "running", "message": "交互式分析正在进行中..."}
    return {"status": "started", "message": f"已开始交互式分析 {stock.name}"}


@router.get("/analyze/{code}/stream")
async def stream_events(code: str):
    """SSE endpoint — streams real-time analysis events to the client.

    Event types:
      status    — internal status text
      output    — Claude's Markdown output
      progress  — tool-use progress (action + partial text)
      question  — structured question waiting for user response
      user-response — resolved answer that continued the flow
      session_end — session finished, includes status=done/error/cancelled
      error     — error occurred
      heartbeat — keepalive (sent when queue is idle)
    """
    async def event_generator():
        session = get_session(code)
        if session is None:
            payload = json.dumps({"type": "error", "text": "会话不存在，请先发起分析"}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            return

        while True:
            event = await session.get_event()
            if event is None:
                break

            if event.get("type") == "heartbeat":
                # Must be a `data:` line, not an SSE comment (`:ping`).
                # EventSource silently ignores comment lines and never fires
                # `onmessage`, so a bare `:ping` would not refresh the client's
                # inactivity watchdog and the client would reconnect on every
                # quiet phase > 30s. Sending it as data lets onmessage fire.
                yield "data: :ping\n\n"
                continue

            payload = json.dumps(event, ensure_ascii=False)
            yield f"data: {payload}\n\n"

            if event.get("type") == "session_end":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.post("/analyze/{code}/respond")
async def respond_to_session(code: str, body: InteractIn):
    """Inject a user response into the currently pending interactive question."""
    ok = respond_session(code, body.response)
    if ok:
        return {"ok": True}
    return {"ok": False, "error": "没有待响应的问题，或会话不存在"}


@router.delete("/analyze/{code}/session")
async def cancel_session(code: str, db: Session = Depends(get_db)):
    """Cancel an active interactive session."""
    session = get_session(code)
    if session:
        session.cancel()
    remove_session(code)
    cleanup = clear_today_analysis_artifacts(
        db,
        stock_code=code,
        reports_root=str(REPORTS_DIR),
        analysis_date=_date.today(),
    )
    return {"ok": True, "cleanup": cleanup}


_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@router.get("/analyze/{code}/log/today")
def get_today_log(code: str):
    """Return metadata for today's analysis log file (text content is served
    directly via the /reports static mount, so this endpoint only reports
    existence/size/mtime and whether a session is currently active).

    If today's file does not exist (e.g. the user is checking just past
    midnight), fall back to the most recent ``*.log`` in the stock's report
    directory so the frontend can still surface a usable button. The response
    always carries the actual log date in ``date`` so the UI can mark stale
    entries.
    """
    today = _date.today().isoformat()
    if not _SAFE_CODE_RE.match(code or ""):
        return {"exists": False, "date": today}

    code_dir = REPORTS_DIR / code
    log_path = code_dir / f"{today}.log"
    if not log_path.exists() and code_dir.is_dir():
        candidates = sorted(code_dir.glob("*.log"))
        if candidates:
            log_path = candidates[-1]

    if not log_path.exists():
        return {"exists": False, "date": today}

    stat = log_path.stat()
    return {
        "exists": True,
        "path": f"/reports/{code}/{log_path.name}",
        "date": log_path.stem,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "is_active": get_session(code) is not None,
    }
