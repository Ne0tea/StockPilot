import glob
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.parser import parse_report_markdown
from core.report_renderer import (
    build_report_paths,
    relative_report_path,
    save_report_markdown,
)
from core.src.core.trading_calendar import (
    get_market_for_stock,
    get_notification_report_date,
)
from db.models import StockReport, Watchlist

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def ensure_report_dir(stock_code: str) -> str:
    path = os.path.join(REPORTS_DIR, stock_code)
    os.makedirs(path, exist_ok=True)
    return path


def resolve_stock_report_date(stock_code: str) -> date:
    """Return the market-aware business report date for a stock."""
    _, data_date = resolve_stock_report_terms(stock_code)
    return data_date


def resolve_stock_report_terms(stock_code: str, report_time: datetime | None = None) -> tuple[datetime, date]:
    """Return (precise report time, market-aware data date)."""
    market = get_market_for_stock(stock_code)
    normalized_time = _normalize_report_time(report_time)
    reference_time = normalized_time.replace(tzinfo=SHANGHAI_TZ)
    return normalized_time, get_notification_report_date(market, current_time=reference_time)


def _normalize_report_time(report_time: datetime | None = None) -> datetime:
    current = report_time or datetime.now(SHANGHAI_TZ)
    if current.tzinfo is not None:
        current = current.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
    return current.replace(second=0, microsecond=0)


def save_report_html(stock_code: str, html_content: str, report_date: date | None = None) -> str:
    absolute_path, relative_path = build_report_paths(
        stock_code,
        report_date or resolve_stock_report_date(stock_code),
    )
    with open(absolute_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return relative_path


def save_report_summary(
    db: Session,
    stock_code: str,
    markdown_content: str,
    html_path: str,
    report_date: date | None = None,
    report_time: datetime | None = None,
):
    from core.interactive import acquire_analysis_start_slot, is_reset_in_progress, release_analysis_start_slot

    if not acquire_analysis_start_slot():
        return None

    try:
        if is_reset_in_progress():
            return None

        summary = parse_report_markdown(markdown_content)
        normalized_html_path = relative_report_path(html_path) if html_path else ""
        target_time, resolved_date = resolve_stock_report_terms(stock_code, report_time)
        target_date = report_date or resolved_date

        stock_name = ""
        watch_row = db.query(Watchlist).filter(Watchlist.stock_code == stock_code).first()
        if watch_row:
            stock_name = watch_row.name or ""
        try:
            save_report_markdown(stock_code, stock_name, markdown_content, target_date)
        except OSError:
            pass

        db.query(StockReport).filter(
            StockReport.stock_code == stock_code,
            StockReport.date == target_date,
        ).delete(synchronize_session=False)

        report = StockReport(
            stock_code=stock_code,
            date=target_date,
            score_total=summary.score_total,
            score_fundamental=summary.score_fundamental,
            score_news=summary.score_news,
            score_capital=summary.score_capital,
            score_technical=summary.score_technical,
            recommendation=summary.recommendation,
            action=summary.action,
            reason=summary.reason,
            target_price=summary.target_price,
            stop_loss_price=summary.stop_loss_price,
            entry_price=summary.entry_price,
            current_price=summary.current_price,
            report_file_path=normalized_html_path,
            report_time=target_time,
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        if is_reset_in_progress():
            return report

        report_dir = ensure_report_dir(stock_code)
        history_path = os.path.join(report_dir, "history.json")
        history = []
        if os.path.exists(history_path):
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        if is_reset_in_progress():
            return report
        target_date_iso = target_date.isoformat()
        history = [item for item in history if item.get("date") != target_date_iso]
        history.append({
            "date": target_date_iso,
            "score_total": summary.score_total,
            "score_fundamental": summary.score_fundamental,
            "score_news": summary.score_news,
            "score_capital": summary.score_capital,
            "score_technical": summary.score_technical,
            "recommendation": summary.recommendation,
            "action": summary.action,
            "reason": summary.reason,
            "target_price": summary.target_price,
            "stop_loss_price": summary.stop_loss_price,
            "entry_price": summary.entry_price,
        })
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        return report
    finally:
        release_analysis_start_slot()


def cleanup_old_reports(days: int = 90):
    cutoff = datetime.now().timestamp() - days * 86400
    for html_file in glob.glob(os.path.join(REPORTS_DIR, "*/*.html")):
        if os.path.getmtime(html_file) < cutoff:
            os.remove(html_file)
