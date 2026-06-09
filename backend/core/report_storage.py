import glob
import json
import os
from datetime import date, datetime

from sqlalchemy.orm import Session

from core.parser import parse_report_markdown
from core.report_renderer import (
    build_report_paths,
    relative_report_path,
    save_report_markdown,
)
from db.models import StockReport, Watchlist

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")


def ensure_report_dir(stock_code: str) -> str:
    path = os.path.join(REPORTS_DIR, stock_code)
    os.makedirs(path, exist_ok=True)
    return path


def save_report_html(stock_code: str, html_content: str) -> str:
    absolute_path, relative_path = build_report_paths(stock_code)
    with open(absolute_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return relative_path


def save_report_summary(db: Session, stock_code: str, markdown_content: str, html_path: str):
    from core.interactive import acquire_analysis_start_slot, is_reset_in_progress, release_analysis_start_slot

    if not acquire_analysis_start_slot():
        return None

    try:
        if is_reset_in_progress():
            return None

        summary = parse_report_markdown(markdown_content)
        normalized_html_path = relative_report_path(html_path) if html_path else ""
        today = date.today()

        stock_name = ""
        watch_row = db.query(Watchlist).filter(Watchlist.stock_code == stock_code).first()
        if watch_row:
            stock_name = watch_row.name or ""
        try:
            save_report_markdown(stock_code, stock_name, markdown_content, today)
        except OSError:
            pass

        db.query(StockReport).filter(
            StockReport.stock_code == stock_code,
            StockReport.date == today,
        ).delete(synchronize_session=False)

        report = StockReport(
            stock_code=stock_code,
            date=today,
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
        today_iso = today.isoformat()
        history = [item for item in history if item.get("date") != today_iso]
        history.append({
            "date": today_iso,
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
