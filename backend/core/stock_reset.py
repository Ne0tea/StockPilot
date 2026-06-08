import os
import shutil
import threading
import time
from typing import Optional

from sqlalchemy.orm import Session

from core.analyzer import (
    REPORTS_DIR,
    active_analysis_workers,
    clear_queue_state,
    request_cancel_for_all_workers,
    worker_lock,
)
from core.interactive import _active_sessions, _sessions_lock
from db.models import AnalysisTaskState, Portfolio, StockReport, TradeLog, Watchlist

SESSION_CANCEL_TIMEOUT_SECONDS = 5.0
SESSION_CANCEL_POLL_SECONDS = 0.01
_reset_lock = threading.Lock()
_reset_condition = threading.Condition(_reset_lock)
_reset_in_progress = False
_reset_generation = 0
_analysis_start_slots = 0
_analysis_start_local = threading.local()


def _current_slot_depth() -> int:
    return getattr(_analysis_start_local, "depth", 0)


def acquire_analysis_start_slot() -> bool:
    global _analysis_start_slots
    with _reset_condition:
        depth = _current_slot_depth()
        if _reset_in_progress and depth == 0:
            return False
        _analysis_start_local.depth = depth + 1
        _analysis_start_slots += 1
        return True


def release_analysis_start_slot() -> None:
    global _analysis_start_slots
    with _reset_condition:
        depth = _current_slot_depth()
        if depth <= 0:
            return
        _analysis_start_local.depth = depth - 1
        _analysis_start_slots -= 1
        if _analysis_start_slots == 0:
            _reset_condition.notify_all()


def begin_reset() -> None:
    global _reset_generation, _reset_in_progress
    with _reset_condition:
        if _reset_in_progress:
            raise RuntimeError("Stock workspace reset already in progress")
        _reset_generation += 1
        _reset_in_progress = True
        while _analysis_start_slots > 0:
            _reset_condition.wait()


def finish_reset() -> None:
    global _reset_in_progress
    with _reset_condition:
        _reset_in_progress = False
        _reset_condition.notify_all()


def is_reset_in_progress() -> bool:
    with _reset_condition:
        return _reset_in_progress


def get_reset_generation() -> int:
    with _reset_condition:
        return _reset_generation


def reset_stock_workspace(db: Session, reports_root: Optional[str] = None) -> dict:
    reports_path = reports_root or REPORTS_DIR
    result = {
        "watchlist_deleted": 0,
        "stock_report_deleted": 0,
        "portfolio_deleted": 0,
        "trade_log_deleted": 0,
        "report_files_deleted": 0,
        "report_dirs_deleted": 0,
        "cancelled_sessions": 0,
    }
    reset_started = False
    staged_reports = {
        "trash_dir": "",
        "moved_entries": [],
        "files_deleted": 0,
        "dirs_deleted": 0,
    }

    try:
        begin_reset()
        reset_started = True
        result["cancelled_sessions"] = _drain_active_sessions()
        _drain_legacy_analysis_workers()
        clear_queue_state()
        db.query(AnalysisTaskState).delete()
        db.commit()

        staged_reports = _stage_reports_root(reports_path)
        result["report_files_deleted"] = staged_reports["files_deleted"]
        result["report_dirs_deleted"] = staged_reports["dirs_deleted"]

        result["watchlist_deleted"] = db.query(Watchlist).count()
        result["stock_report_deleted"] = db.query(StockReport).count()
        result["portfolio_deleted"] = db.query(Portfolio).count()
        result["trade_log_deleted"] = db.query(TradeLog).count()

        db.query(Watchlist).delete()
        db.query(StockReport).delete()
        db.query(Portfolio).delete()
        db.query(TradeLog).delete()
        db.commit()
    except Exception:
        db.rollback()
        _restore_staged_reports(staged_reports)
        raise
    finally:
        if reset_started:
            finish_reset()

    purge_warning = _purge_staged_reports(staged_reports)
    if purge_warning:
        result["trash_retained"] = purge_warning
    return result


def clear_all_analysis_data(db: Session, reports_root: Optional[str] = None) -> dict:
    """Delete every stock's analysis data while KEEPING the watchlist intact.

    Unlike ``reset_stock_workspace`` (which also wipes watchlist/portfolio/trade
    logs), this only removes analysis artefacts: StockReport rows plus the
    on-disk report files (per-code dirs and root ``*.md``/``*.html``). Running
    sessions are cancelled and the queue is cleared first, under the same reset
    barrier so no in-flight analysis can write back mid-purge.
    """
    reports_path = reports_root or REPORTS_DIR
    result = {
        "stock_report_deleted": 0,
        "report_files_deleted": 0,
        "report_dirs_deleted": 0,
        "cancelled_sessions": 0,
    }
    reset_started = False
    staged_reports = {"trash_dir": "", "moved_entries": [], "files_deleted": 0, "dirs_deleted": 0}

    try:
        begin_reset()
        reset_started = True
        result["cancelled_sessions"] = _drain_active_sessions(force=True)
        _drain_legacy_analysis_workers(force=True)
        clear_queue_state()
        db.query(AnalysisTaskState).delete()
        db.commit()

        staged_reports = _stage_reports_root(reports_path)
        result["report_files_deleted"] = staged_reports["files_deleted"]
        result["report_dirs_deleted"] = staged_reports["dirs_deleted"]

        result["stock_report_deleted"] = db.query(StockReport).count()
        db.query(StockReport).delete()
        db.commit()
    except Exception:
        db.rollback()
        _restore_staged_reports(staged_reports)
        raise
    finally:
        if reset_started:
            finish_reset()

    purge_warning = _purge_staged_reports(staged_reports)
    if purge_warning:
        result["trash_retained"] = purge_warning
    return result


def clear_stock_analysis_data(db: Session, stock_code: str, reports_root: Optional[str] = None) -> dict:
    """Delete a single stock's analysis data (reports + on-disk files).

    The watchlist entry is preserved. Any running/queued session for this code
    is cancelled first so the purge cannot race a writer.
    """
    reports_path = reports_root or REPORTS_DIR
    result = {
        "stock_code": stock_code,
        "stock_report_deleted": 0,
        "report_files_deleted": 0,
        "cancelled_sessions": 0,
    }
    reset_started = False
    staged = {"trash_dir": "", "moved_entries": [], "files_deleted": 0}

    try:
        begin_reset()
        reset_started = True
        result["cancelled_sessions"] = _drain_active_sessions(force=True)
        _drain_legacy_analysis_workers(force=True)
        clear_queue_state()
        db.query(AnalysisTaskState).filter(AnalysisTaskState.stock_code == stock_code).delete()
        db.commit()

        staged = _stage_stock_reports(reports_path, stock_code)
        result["report_files_deleted"] = staged["files_deleted"]

        result["stock_report_deleted"] = (
            db.query(StockReport).filter(StockReport.stock_code == stock_code).count()
        )
        db.query(StockReport).filter(StockReport.stock_code == stock_code).delete()
        db.commit()
    except Exception:
        db.rollback()
        _restore_staged_reports(staged)
        raise
    finally:
        if reset_started:
            finish_reset()

    purge_warning = _purge_staged_reports(staged)
    if purge_warning:
        result["trash_retained"] = purge_warning
    return result


def _drain_active_sessions(force: bool = False) -> int:
    deadline = time.monotonic() + SESSION_CANCEL_TIMEOUT_SECONDS
    cancelled_ids: set[int] = set()

    while True:
        session_pairs = _snapshot_active_sessions()
        if not session_pairs:
            return len(cancelled_ids)

        for _, session in session_pairs:
            session_id = id(session)
            if session_id in cancelled_ids:
                continue
            session.cancel()
            cancelled_ids.add(session_id)

        try:
            _wait_for_cancelled_sessions(session_pairs, deadline)
        except TimeoutError:
            # Best-effort path (used by the analysis-only clear endpoints): an
            # orphaned session whose async task is already dead will never set
            # its _done event, so cancel() can't make it settle. Force-evict
            # the stuck entries instead of failing the whole purge with a 500.
            if not force:
                raise
            _force_remove_sessions(session_pairs)
            return len(cancelled_ids)
        _remove_settled_sessions(session_pairs)


def _snapshot_active_sessions() -> list[tuple[str, object]]:
    with _sessions_lock:
        return list(_active_sessions.items())


def _drain_legacy_analysis_workers(force: bool = False) -> int:
    deadline = time.monotonic() + SESSION_CANCEL_TIMEOUT_SECONDS

    while True:
        workers = request_cancel_for_all_workers()
        if not workers:
            return 0
        try:
            _wait_for_legacy_workers(workers, deadline)
        except TimeoutError:
            if not force:
                raise
            _force_remove_legacy_workers()
            return len(workers)
        if not _snapshot_legacy_workers():
            return len(workers)


def _force_remove_legacy_workers() -> None:
    with worker_lock:
        for worker in list(active_analysis_workers.values()):
            try:
                worker.done_event.set()
            except Exception:
                pass
        active_analysis_workers.clear()


def _snapshot_legacy_workers() -> list[object]:
    with worker_lock:
        return list(active_analysis_workers.values())


def _wait_for_cancelled_sessions(session_pairs: list[tuple[str, object]], deadline: float) -> None:
    while True:
        if all(_session_has_settled(session) for _, session in session_pairs):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for interactive sessions to cancel")
        time.sleep(SESSION_CANCEL_POLL_SECONDS)


def _session_has_settled(session: object) -> bool:
    if hasattr(session, "_done"):
        done_event = getattr(session, "_done")
        return done_event.is_set()

    return getattr(session, "is_running", True) is False


def _wait_for_legacy_workers(workers: list[object], deadline: float) -> None:
    while True:
        if all(worker.done_event.is_set() for worker in workers):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for legacy analysis workers to cancel")
        time.sleep(SESSION_CANCEL_POLL_SECONDS)


def _remove_settled_sessions(session_pairs: list[tuple[str, object]]) -> None:
    with _sessions_lock:
        for code, session in session_pairs:
            if not _session_has_settled(session):
                continue
            if _active_sessions.get(code) is session:
                _active_sessions.pop(code, None)


def _force_remove_sessions(session_pairs: list[tuple[str, object]]) -> None:
    """Evict the given sessions from the registry regardless of settled state.

    Used by the analysis-only clear endpoints when a session task has already
    died without setting its _done event (an orphan). Marking it not-running
    keeps any late callback from reviving it.
    """
    with _sessions_lock:
        for code, session in session_pairs:
            try:
                session._running = False
            except Exception:
                pass
            if _active_sessions.get(code) is session:
                _active_sessions.pop(code, None)


def _stage_reports_root(reports_root: str) -> dict:
    staged = {
        "trash_dir": "",
        "moved_entries": [],
        "files_deleted": 0,
        "dirs_deleted": 0,
    }

    if not os.path.isdir(reports_root):
        return staged

    entries_to_stage = []
    for name in os.listdir(reports_root):
        if name.startswith("."):
            continue

        source_path = os.path.join(reports_root, name)
        if os.path.isdir(source_path):
            entries_to_stage.append((name, source_path, "dir"))
            continue

        if os.path.isfile(source_path) and name.endswith((".md", ".html")):
            entries_to_stage.append((name, source_path, "file"))

    if not entries_to_stage:
        return staged

    trash_dir = os.path.join(reports_root, f".reset-trash-{time.time_ns()}")
    os.makedirs(trash_dir, exist_ok=False)
    staged["trash_dir"] = trash_dir

    try:
        for name, source_path, entry_type in entries_to_stage:
            destination_path = os.path.join(trash_dir, name)
            shutil.move(source_path, destination_path)
            staged["moved_entries"].append((name, destination_path, source_path, entry_type))
            if entry_type == "dir":
                staged["dirs_deleted"] += 1
                for _, _, files in os.walk(destination_path):
                    staged["files_deleted"] += len(files)
            else:
                staged["files_deleted"] += 1
    except Exception:
        _restore_staged_reports(staged)
        raise

    return staged


def _stage_stock_reports(reports_root: str, stock_code: str) -> dict:
    """Move one stock's report artefacts into a trash dir (atomic-ish purge).

    Targets: the per-code directory ``reports/<code>/`` and any root-level
    ``<code>_*.md`` / ``<code>_*.html`` summary files matching that stock.
    """
    staged = {"trash_dir": "", "moved_entries": [], "files_deleted": 0, "dirs_deleted": 0}

    if not os.path.isdir(reports_root) or not stock_code:
        return staged

    entries_to_stage = []
    code_dir = os.path.join(reports_root, stock_code)
    if os.path.isdir(code_dir):
        entries_to_stage.append((stock_code, code_dir, "dir"))

    prefix = f"{stock_code}_"
    for name in os.listdir(reports_root):
        if not name.startswith(prefix):
            continue
        source_path = os.path.join(reports_root, name)
        if os.path.isfile(source_path) and name.endswith((".md", ".html")):
            entries_to_stage.append((name, source_path, "file"))

    if not entries_to_stage:
        return staged

    trash_dir = os.path.join(reports_root, f".reset-trash-{time.time_ns()}")
    os.makedirs(trash_dir, exist_ok=False)
    staged["trash_dir"] = trash_dir

    try:
        for name, source_path, entry_type in entries_to_stage:
            destination_path = os.path.join(trash_dir, name)
            shutil.move(source_path, destination_path)
            staged["moved_entries"].append((name, destination_path, source_path, entry_type))
            if entry_type == "dir":
                staged["dirs_deleted"] += 1
                for _, _, files in os.walk(destination_path):
                    staged["files_deleted"] += len(files)
            else:
                staged["files_deleted"] += 1
    except Exception:
        _restore_staged_reports(staged)
        raise

    return staged


def _restore_staged_reports(staged_reports: dict) -> None:
    trash_dir = staged_reports["trash_dir"]
    if not trash_dir or not os.path.isdir(trash_dir):
        return

    for _, staged_path, original_path, _ in reversed(staged_reports["moved_entries"]):
        if os.path.exists(staged_path):
            shutil.move(staged_path, original_path)

    shutil.rmtree(trash_dir, ignore_errors=True)


def _purge_staged_reports(staged_reports: dict) -> str:
    trash_dir = staged_reports.get("trash_dir", "")
    if not trash_dir or not os.path.isdir(trash_dir):
        return ""
    try:
        shutil.rmtree(trash_dir)
    except OSError:
        return trash_dir
    return ""
