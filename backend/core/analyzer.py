import glob
import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional
from sqlalchemy.orm import Session

from db.database import SessionLocal
from core.parser import parse_report_markdown
from core.analysis_task_state import (
    clear_task_state_for_code,
    get_task_status_for_code,
    shanghai_today,
    upsert_task_status,
)
from core.report_renderer import (
    build_report_paths,
    move_generated_report_html,
    relative_report_path,
    save_report_markdown,
)
from db.models import StockReport, Watchlist

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
CLAUDE_CLI = os.path.expanduser("~/.local/bin/claude")


@dataclass
class AnalysisWorker:
    code: str
    name: str
    thread: threading.Thread | None = None
    cancel_requested: bool = False
    done_event: threading.Event = field(default_factory=threading.Event)

    def request_cancel(self):
        self.cancel_requested = True


active_analysis_workers: dict[str, AnalysisWorker] = {}
worker_lock = threading.Lock()

_analysis_queue: "queue.Queue[tuple[str, str, Callable]]" = queue.Queue()
_queue_order: list[str] = []
_queue_lock = threading.Lock()
_dispatcher_thread: Optional[threading.Thread] = None
_dispatcher_lock = threading.Lock()


def acquire_analysis_start_slot() -> bool:
    from core.stock_reset import acquire_analysis_start_slot as _acquire

    return _acquire()


def release_analysis_start_slot() -> None:
    from core.stock_reset import release_analysis_start_slot as _release

    _release()


def is_reset_in_progress() -> bool:
    from core.stock_reset import is_reset_in_progress as _is_reset

    return _is_reset()


def ensure_report_dir(stock_code: str) -> str:
    path = os.path.join(REPORTS_DIR, stock_code)
    os.makedirs(path, exist_ok=True)
    return path


def register_analysis_worker(code: str, name: str, thread: threading.Thread | None = None) -> AnalysisWorker:
    worker = AnalysisWorker(code=code, name=name, thread=thread)
    with worker_lock:
        active_analysis_workers[code] = worker
    return worker


def get_analysis_worker(code: str) -> AnalysisWorker | None:
    with worker_lock:
        return active_analysis_workers.get(code)


def request_cancel_for_all_workers() -> list[AnalysisWorker]:
    """Cancel running worker AND drain pending queued workers."""
    drained_codes: list[str] = []
    with _queue_lock:
        try:
            while True:
                _analysis_queue.get_nowait()
        except queue.Empty:
            pass
        drained_codes = list(_queue_order)
        _queue_order.clear()

    with worker_lock:
        workers = list(active_analysis_workers.values())

    for worker in workers:
        worker.request_cancel()

    for code in drained_codes:
        with worker_lock:
            worker = active_analysis_workers.pop(code, None)
        if worker is not None:
            worker.done_event.set()

    return workers


def cleanup_analysis_worker(code: str, worker: AnalysisWorker) -> None:
    worker.done_event.set()
    with worker_lock:
        if active_analysis_workers.get(code) is worker:
            active_analysis_workers.pop(code, None)


def should_abort_worker(worker: AnalysisWorker | None) -> bool:
    if worker and worker.cancel_requested:
        return True

    return is_reset_in_progress()


def clear_queue_state() -> None:
    """Reset all queue/status state. Call after reset finishes."""
    with _queue_lock:
        try:
            while True:
                _analysis_queue.get_nowait()
        except queue.Empty:
            pass
        _queue_order.clear()


def get_queue_position(code: str) -> Optional[int]:
    with _queue_lock:
        try:
            return _queue_order.index(code) + 1
        except ValueError:
            return None


def get_queue_snapshot() -> dict:
    with _queue_lock:
        queued_codes = list(_queue_order)

    with worker_lock:
        worker_map = dict(active_analysis_workers)

    queue_entries = []
    for idx, code in enumerate(queued_codes, start=1):
        worker = worker_map.get(code)
        queue_entries.append({
            "code": code,
            "name": worker.name if worker else "",
            "position": idx,
        })

    running = None
    for code, worker in worker_map.items():
        if code in queued_codes:
            continue
        status = get_analysis_status(code)
        if status == "running":
            running = {"code": code, "name": worker.name}
            break

    return {
        "queue": queue_entries,
        "running": running,
        "size": len(queue_entries),
    }


def _ensure_dispatcher_running() -> None:
    global _dispatcher_thread
    with _dispatcher_lock:
        if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
            return
        t = threading.Thread(target=_dispatcher_loop, daemon=True, name="analysis-dispatcher")
        _dispatcher_thread = t
        t.start()


def _dispatcher_loop() -> None:
    while True:
        try:
            code, name, db_session_factory = _analysis_queue.get()
        except Exception:
            continue

        with _queue_lock:
            try:
                _queue_order.remove(code)
            except ValueError:
                pass

        worker = get_analysis_worker(code)
        if worker is None:
            continue

        if should_abort_worker(worker):
            _persist_task_status(code, "cancelled", run_mode="legacy", message="任务已取消")
            cleanup_analysis_worker(code, worker)
            continue

        try:
            run_stock_analysis(code, name, db_session_factory, worker)
        except Exception as e:
            _persist_task_status(code, "error", run_mode="legacy", message=str(e))
            cleanup_analysis_worker(code, worker)


def run_stock_analysis(code: str, name: str, db_session_factory, worker: Optional[AnalysisWorker] = None):
    """Run full stock-analyzer skill via Claude CLI in dispatcher thread."""
    if worker is None:
        worker = get_analysis_worker(code) or register_analysis_worker(code, name)

    _persist_task_status(code, "running", run_mode="legacy")

    try:
        if should_abort_worker(worker):
            _persist_task_status(code, "cancelled", run_mode="legacy", message="任务已取消")
            return

        prompt = (
            f"分析股票 {name}({code})，请生成完整分析报告。"
            "重要：用户已登录东方财富，跳过Step 0登录引导，直接从Step 1开始执行分析。"
        )
        result = subprocess.run(
            [CLAUDE_CLI, "-p", prompt, "--output-format", "text",
             "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=600,
            cwd=REPORTS_DIR
        )

        if should_abort_worker(worker):
            _persist_task_status(code, "cancelled", run_mode="legacy", message="任务已取消")
            return

        if result.returncode != 0:
            _persist_task_status(
                code,
                "error",
                run_mode="legacy",
                message=f"CLI returned {result.returncode}",
            )
            return

        markdown_content = result.stdout

        if should_abort_worker(worker):
            _persist_task_status(code, "cancelled", run_mode="legacy", message="任务已取消")
            return

        html_path = move_generated_report_html(code)

        if should_abort_worker(worker):
            _persist_task_status(code, "cancelled", run_mode="legacy", message="任务已取消")
            return

        db = db_session_factory()
        try:
            save_report_summary(db, code, markdown_content, html_path)
        finally:
            db.close()

        if should_abort_worker(worker):
            _persist_task_status(code, "cancelled", run_mode="legacy", message="任务已取消")
            return

        _persist_task_status(code, "done", run_mode="legacy")
    except subprocess.TimeoutExpired:
        _persist_task_status(code, "error", run_mode="legacy", message="timeout")
    except Exception as e:
        _persist_task_status(code, "error", run_mode="legacy", message=str(e))
    finally:
        cleanup_analysis_worker(code, worker)


def start_analysis(code: str, name: str, db_session_factory) -> dict:
    """Enqueue analysis for FIFO processing.

    Returns:
        {"ok": True, "status": "queued", "position": int}
        {"ok": False, "reason": "already_running" | "reset_in_progress"}
    """
    if not acquire_analysis_start_slot():
        return {"ok": False, "reason": "reset_in_progress"}

    try:
        if is_reset_in_progress():
            return {"ok": False, "reason": "reset_in_progress"}

        with worker_lock:
            existing = active_analysis_workers.get(code)
            if existing and not existing.done_event.is_set():
                return {"ok": False, "reason": "already_running"}

            worker = AnalysisWorker(code=code, name=name)
            active_analysis_workers[code] = worker

        _persist_task_status(code, "queued", run_mode="legacy")

        with _queue_lock:
            _queue_order.append(code)
            position = len(_queue_order)

        _analysis_queue.put((code, name, db_session_factory))
        _ensure_dispatcher_running()

        return {"ok": True, "status": "queued", "position": position}
    finally:
        release_analysis_start_slot()


def enqueue_many(items: list[tuple[str, str]], db_session_factory) -> dict:
    """Enqueue multiple stocks. Each item is (code, name).

    Returns:
        {"queued": [{"code","name","position"}], "skipped": [{"code","name","reason"}]}
    """
    queued: list[dict] = []
    skipped: list[dict] = []

    for code, name in items:
        result = start_analysis(code, name, db_session_factory)
        if result.get("ok"):
            queued.append({
                "code": code,
                "name": name,
                "position": result["position"],
            })
        else:
            skipped.append({
                "code": code,
                "name": name,
                "reason": result.get("reason", "unknown"),
            })

    return {"queued": queued, "skipped": skipped}


def get_analysis_status(code: str) -> str:
    db = SessionLocal()
    try:
        status, _ = get_task_status_for_code(db, code, shanghai_today())
        return status
    finally:
        db.close()


def _persist_task_status(code: str, status: str, run_mode: str = "", message: str = "") -> None:
    db = SessionLocal()
    try:
        upsert_task_status(
            db,
            stock_code=code,
            analysis_date=shanghai_today(),
            status=status,
            status_message=message,
            run_mode=run_mode,
        )
    finally:
        db.close()


def save_report_html(stock_code: str, html_content: str) -> str:
    absolute_path, relative_path = build_report_paths(stock_code)
    with open(absolute_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return relative_path


def save_report_summary(db: Session, stock_code: str, markdown_content: str, html_path: str):
    if not acquire_analysis_start_slot():
        return None

    worker = get_analysis_worker(stock_code)
    try:
        if should_abort_worker(worker):
            return None

        summary = parse_report_markdown(markdown_content)
        normalized_html_path = relative_report_path(html_path) if html_path else ""
        today = date.today()

        # Persist the report markdown so the listing/dashboard can re-parse it as
        # the canonical summary source (matches the *_分析报告_<date>.md naming the
        # scanner recognises). The DB row stays the fast-read cache.
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
            stock_code=stock_code, date=today,
            score_total=summary.score_total,
            score_fundamental=summary.score_fundamental,
            score_news=summary.score_news,
            score_capital=summary.score_capital,
            score_technical=summary.score_technical,
            recommendation=summary.recommendation,
            action=summary.action, reason=summary.reason,
            target_price=summary.target_price,
            stop_loss_price=summary.stop_loss_price,
            entry_price=summary.entry_price,
            current_price=summary.current_price,
            report_file_path=normalized_html_path,
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        if should_abort_worker(worker):
            return report

        report_dir = ensure_report_dir(stock_code)
        history_path = os.path.join(report_dir, "history.json")
        history = []
        if os.path.exists(history_path):
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        if should_abort_worker(worker):
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
