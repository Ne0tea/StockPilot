from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from db.models import AnalysisTaskState


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
ACTIVE_STATUSES = {"running"}


def shanghai_today(now: datetime | None = None) -> date:
    current = now.astimezone(SHANGHAI_TZ) if now else datetime.now(SHANGHAI_TZ)
    return current.date()


def clear_stale_task_states(db: Session, today: date | None = None) -> int:
    current_day = today or shanghai_today()
    deleted = _delete_stale_task_states(db, current_day)
    db.commit()
    return deleted


def get_task_state_row(db: Session, stock_code: str, analysis_date: date | None = None) -> AnalysisTaskState | None:
    target_day = analysis_date or shanghai_today()
    return (
        db.query(AnalysisTaskState)
        .filter(
            AnalysisTaskState.stock_code == stock_code,
            AnalysisTaskState.analysis_date == target_day,
        )
        .first()
    )


def get_task_status_for_code(db: Session, stock_code: str, analysis_date: date | None = None) -> tuple[str, date]:
    target_day = analysis_date or shanghai_today()
    row = get_task_state_row(db, stock_code, target_day)
    return (row.status if row else "idle", target_day)


def upsert_task_status(
    db: Session,
    stock_code: str,
    analysis_date: date | None = None,
    status: str = "idle",
    status_message: str = "",
    run_mode: str = "",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> AnalysisTaskState:
    target_day = analysis_date or shanghai_today()
    row = get_task_state_row(db, stock_code, target_day)
    if row is None:
        row = AnalysisTaskState(
            stock_code=stock_code,
            analysis_date=target_day,
        )
        db.add(row)

    row.status = status
    row.status_message = status_message or ""
    if run_mode:
        row.run_mode = run_mode
    if started_at and row.started_at is None:
        row.started_at = started_at
    if finished_at:
        row.finished_at = finished_at
    elif status in {"done", "error", "cancelled", "idle"}:
        row.finished_at = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
    if status in ACTIVE_STATUSES and row.started_at is None:
        row.started_at = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
    row.updated_at = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)

    db.commit()
    db.refresh(row)
    return row


def reset_active_task_states(
    db: Session,
    today: date | None = None,
    message: str = "服务重启，任务状态已重置",
) -> int:
    target_day = today or shanghai_today()
    rows = (
        db.query(AnalysisTaskState)
        .filter(
            AnalysisTaskState.analysis_date == target_day,
            AnalysisTaskState.status.in_(ACTIVE_STATUSES),
        )
        .all()
    )
    if not rows:
        return 0

    finished_at = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
    for row in rows:
        row.status = "error"
        row.status_message = message
        row.finished_at = finished_at
        row.updated_at = finished_at

    db.commit()
    return len(rows)


def clear_task_state_for_code(db: Session, stock_code: str, analysis_date: date | None = None) -> int:
    target_day = analysis_date or shanghai_today()
    deleted = (
        db.query(AnalysisTaskState)
        .filter(
            AnalysisTaskState.stock_code == stock_code,
            AnalysisTaskState.analysis_date == target_day,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def _delete_stale_task_states(db: Session, today: date) -> int:
    return (
        db.query(AnalysisTaskState)
        .filter(AnalysisTaskState.analysis_date != today)
        .delete(synchronize_session=False)
    )
