from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.database import get_db
from core.analysis_task_state import get_task_status_for_code
from db.models import Watchlist, Portfolio
from core.report_listing import list_reports
from core.report_renderer import REPORTS_DIR
from core.stock_reset import (
    clear_all_analysis_data,
    clear_stock_analysis_data,
    reset_stock_workspace,
)
from db.models import StockReport

router = APIRouter(tags=["watchlist"])

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_HISTORY_LIMIT = 30
_TODAY_REPORT_PROBE_LIMIT = 10

class StockIn(BaseModel):
    stock_code: str
    market: str
    name: str

@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    holdings = db.query(Portfolio).filter(Portfolio.status == "holding").all()
    held_codes = {p.stock_code for p in holdings}
    stocks = db.query(Watchlist).filter(Watchlist.is_active == True).all()
    return [
        {**{c.name: getattr(s, c.name) for c in Watchlist.__table__.columns},
         "is_held": s.stock_code in held_codes}
        for s in stocks
    ]

@router.get("/watchlist/overview")
def get_watchlist_overview(db: Session = Depends(get_db)):
    """Aggregated payload for the Stocks page — one round-trip per page render.

    Returns watchlist + per-stock history (limited) + today's html-ready report (if any)
    + analysis queue snapshot + today's date + server timestamp.
    """
    holdings = db.query(Portfolio).filter(Portfolio.status == "holding").all()
    held_codes = {p.stock_code for p in holdings}
    watchlist_rows = db.query(Watchlist).filter(Watchlist.is_active == True).all()

    stocks = [
        {**{c.name: getattr(s, c.name) for c in Watchlist.__table__.columns},
         "is_held": s.stock_code in held_codes}
        for s in watchlist_rows
    ]

    now = datetime.now(_SHANGHAI_TZ)
    today_str = now.strftime("%Y-%m-%d")

    history_map: dict[str, list] = {}
    today_report_map: dict[str, dict] = {}
    analysis_state: dict[str, str] = {}

    for stock in watchlist_rows:
        code = stock.stock_code
        history = _history_rows_for_code(db, code, stock.name, limit=_HISTORY_LIMIT)
        history_map[code] = history

        today_report = _resolve_today_report(history, today_str)
        if today_report:
            today_report_map[code] = today_report

        status, _ = get_task_status_for_code(db, code, now.date())
        if status:
            analysis_state[code] = status

    return {
        "stocks": stocks,
        "history_map": history_map,
        "today_report_map": today_report_map,
        "analysis_state": analysis_state,
        "today_date": today_str,
        "server_time": now.isoformat(),
    }


def _history_rows_for_code(db: Session, code: str, stock_name: str, limit: int | None = None):
    query = db.query(StockReport).filter(StockReport.stock_code == code).order_by(
        StockReport.date.asc(),
        StockReport.created_at.asc(),
        StockReport.id.asc(),
    )
    rows = query.all()
    if limit is not None:
        rows = rows[-limit:]

    return [
        {
            "date": row.date.isoformat() if row.date else "",
            "score_total": row.score_total,
            "score_fundamental": row.score_fundamental,
            "score_news": row.score_news,
            "score_capital": row.score_capital,
            "score_technical": row.score_technical,
            "recommendation": row.recommendation,
            "action": row.action,
            "reason": row.reason,
            "target_price": row.target_price,
            "stop_loss_price": row.stop_loss_price,
            "entry_price": row.entry_price,
            "current_price": row.current_price,
            "report_file_path": row.report_file_path or "",
            "html_status": "ready" if row.report_file_path else "missing",
            "markdown_file_path": _resolve_markdown_report_path(code, row.date, stock_name),
        }
        for row in rows
    ]


def _resolve_today_report(history, today):
    for record in history or []:
        if record.get("date") != today:
            continue
        if record.get("html_status") == "ready" and record.get("report_file_path"):
            return record
        if record.get("markdown_file_path"):
            return record
    return None


def _resolve_markdown_report_path(code: str, report_date, stock_name: str) -> str:
    if not code or not report_date:
        return ""

    reports_root = Path(REPORTS_DIR)
    compact_date = report_date.strftime("%Y%m%d")
    candidates = sorted(reports_root.glob(f"{code}_*_分析报告_{compact_date}.md"))
    if not candidates:
        return ""

    preferred_name = (stock_name or "").strip()
    if preferred_name:
        preferred = reports_root / f"{code}_{preferred_name}_分析报告_{compact_date}.md"
        if preferred.exists():
            return f"reports/{preferred.name}"

    return f"reports/{candidates[0].name}"


@router.get("/watchlist/check")
def check_stock_in_watchlist(stock_code: str = Query(...), db: Session = Depends(get_db)):
    item = db.query(Watchlist).filter(
        Watchlist.stock_code == stock_code, Watchlist.is_active == True
    ).first()
    return {"in_watchlist": item is not None, "id": item.id if item else None}

@router.post("/watchlist")
def add_stock(stock: StockIn, db: Session = Depends(get_db)):
    item = Watchlist(stock_code=stock.stock_code, market=stock.market, name=stock.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.post("/watchlist/reset")
def reset_watchlist_endpoint(db: Session = Depends(get_db)):
    return reset_stock_workspace(db)


@router.post("/watchlist/analysis/clear")
def clear_all_analysis_endpoint(db: Session = Depends(get_db)):
    """Delete every stock's analysis data (reports + files), keep the watchlist."""
    return clear_all_analysis_data(db)


@router.delete("/watchlist/{stock_code}/analysis")
def clear_stock_analysis_endpoint(stock_code: str, db: Session = Depends(get_db)):
    """Delete a single stock's analysis data (reports + files), keep the watchlist entry."""
    return clear_stock_analysis_data(db, stock_code)


@router.delete("/watchlist/{stock_id}")
def remove_stock(stock_id: int, db: Session = Depends(get_db)):
    item = db.query(Watchlist).get(stock_id)
    if item:
        item.is_active = False
        db.commit()
    return {"ok": True}
