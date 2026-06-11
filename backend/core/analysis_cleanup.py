import glob
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from db.models import AnalysisTaskState, StockReport


def clear_today_analysis_artifacts(
    db: Session,
    stock_code: str,
    reports_root: str,
    analysis_date: Optional[date] = None,
) -> dict:
    target_day = analysis_date or date.today()
    target_day_iso = target_day.isoformat()
    compact_day = target_day.strftime("%Y%m%d")
    reports_root_path = Path(reports_root)

    stock_report_deleted = (
        db.query(StockReport)
        .filter(
            StockReport.stock_code == stock_code,
            StockReport.date == target_day,
        )
        .delete(synchronize_session=False)
    )
    task_state_deleted = (
        db.query(AnalysisTaskState)
        .filter(
            AnalysisTaskState.stock_code == stock_code,
            AnalysisTaskState.analysis_date == target_day,
        )
        .delete(synchronize_session=False)
    )
    db.commit()

    file_delete_targets = [
        reports_root_path / stock_code / f"{target_day_iso}.html",
        reports_root_path / stock_code / f"{target_day_iso}.log",
    ]
    file_delete_targets.extend(
        Path(path)
        for path in glob.glob(str(reports_root_path / f"{stock_code}_*_分析报告_{compact_day}.md"))
    )
    report_files_deleted = 0
    for file_path in file_delete_targets:
        if not file_path.exists():
            continue
        try:
            file_path.unlink()
            report_files_deleted += 1
        except OSError:
            pass

    history_entries_deleted = _delete_history_entries_for_day(
        reports_root_path / stock_code / "history.json",
        target_day_iso,
    )

    return {
        "stock_code": stock_code,
        "analysis_date": target_day_iso,
        "stock_report_deleted": stock_report_deleted,
        "task_state_deleted": task_state_deleted,
        "report_files_deleted": report_files_deleted,
        "history_entries_deleted": history_entries_deleted,
    }


def _delete_history_entries_for_day(history_path: Path, target_day_iso: str) -> int:
    if not history_path.exists():
        return 0

    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    if not isinstance(history, list):
        return 0

    next_history = [item for item in history if item.get("date") != target_day_iso]
    deleted = len(history) - len(next_history)
    if deleted <= 0:
        return 0

    try:
        if next_history:
            history_path.write_text(
                json.dumps(next_history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            history_path.unlink()
    except OSError:
        return 0

    return deleted
