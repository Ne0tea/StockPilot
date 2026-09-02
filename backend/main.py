import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from db.database import engine, Base, SessionLocal
from db.models import Settings
from core.runtime_checks import assert_runtime_dependencies
from core.schema_migrations import (
    migrate_analysis_task_state_schema,
    migrate_mail_delivery_record_schema,
    migrate_notification_log_schema,
    migrate_settings_schema,
    migrate_stock_report_current_price,
    migrate_watchlist_stock_code,
)
from core.analysis_task_state import clear_stale_task_states, reset_active_task_states
from core.scheduler import init_scheduler, scheduler
import os

logger = logging.getLogger(__name__)
SHUTDOWN_TIMEOUT_SECONDS = 120.0
_shutdown_state_lock = threading.Lock()
_shutdown_task = None
_shutdown_complete = False

assert_runtime_dependencies()

from api import watchlist, analyze, portfolio, dashboard, settings, market_data, agent_chat


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - monotonic())


def _pause_scheduler() -> None:
    try:
        if scheduler.running:
            scheduler.pause()
    except Exception:
        logger.exception("scheduler_pause_failed")


def _close_data_sources() -> None:
    """Close process-level data source clients without changing their APIs."""
    try:
        from src.agent.tools import data_tools
        manager = getattr(data_tools, "_fetcher_manager_singleton", None)
        if manager is not None and hasattr(manager, "close"):
            manager.close()
        data_tools.reset_fetcher_manager()
    except Exception:
        logger.exception("data_source_shutdown_failed")

    try:
        import core.market_data as market_data_module
        session = getattr(market_data_module, "_SESSION", None)
        if session is not None:
            session.close()
            market_data_module._SESSION = None
    except Exception:
        logger.exception("market_data_session_shutdown_failed")


def _close_database() -> None:
    try:
        engine.dispose()
    except Exception:
        logger.exception("database_shutdown_failed")


async def _run_sync_with_deadline(operation, deadline: float, operation_name: str) -> bool:
    remaining = _remaining(deadline)
    if remaining <= 0:
        return False
    try:
        await asyncio.wait_for(asyncio.to_thread(operation), timeout=remaining)
        return True
    except asyncio.TimeoutError:
        logger.error("shutdown_timeout operation=%s", operation_name)
        return False
    except Exception:
        logger.exception("shutdown_operation_failed operation=%s", operation_name)
        return False


async def _perform_shutdown() -> bool:
    deadline = monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    timed_out = False

    # Close intake first, then stop scheduled jobs before asking active work
    # to cooperate with cancellation.
    try:
        from core.agent_runtime import set_runtime_accepting
        set_runtime_accepting(False)
    except Exception:
        logger.exception("agent_shutdown_gate_failed")

    try:
        from core.interactive import set_accepting_new_tasks, shutdown_interactive_sessions
        set_accepting_new_tasks(False)
    except Exception:
        shutdown_interactive_sessions = None

    _pause_scheduler()

    try:
        from core.agent_runtime import shutdown_agent_runtime
        shutdown_agent_runtime()
    except Exception:
        logger.exception("agent_shutdown_request_failed")

    waits = []
    if shutdown_interactive_sessions is not None:
        waits.append(shutdown_interactive_sessions(deadline))
    try:
        from core.agent_runtime import wait_for_agent_runtime
        waits.append(asyncio.to_thread(wait_for_agent_runtime, _remaining(deadline)))
    except Exception:
        logger.exception("agent_shutdown_wait_setup_failed")

    try:
        from core.data_provider.efinance_fetcher import wait_for_timeout_workers
        waits.append(asyncio.to_thread(wait_for_timeout_workers, deadline))
    except Exception:
        logger.exception("efinance_shutdown_wait_setup_failed")

    if waits:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*waits, return_exceptions=True),
                timeout=_remaining(deadline),
            )
            timed_out = timed_out or any(result is False or isinstance(result, Exception) for result in results)
        except asyncio.TimeoutError:
            timed_out = True

    if _remaining(deadline) <= 0:
        timed_out = True
    else:
        try:
            from core.agent_runtime import close_agent_executors
            if not await _run_sync_with_deadline(close_agent_executors, deadline, "agent_executors"):
                timed_out = True
        except Exception:
            logger.exception("agent_executor_shutdown_failed")
            timed_out = True

        if not await _run_sync_with_deadline(_close_data_sources, deadline, "data_sources"):
            timed_out = True
        if not await _run_sync_with_deadline(_close_database, deadline, "database"):
            timed_out = True

        if scheduler.running:
            if not await _run_sync_with_deadline(lambda: scheduler.shutdown(wait=True), deadline, "scheduler"):
                timed_out = True

    if timed_out or _remaining(deadline) <= 0:
        logger.error("shutdown_timeout")
    logging.shutdown()
    return not timed_out and _remaining(deadline) >= 0


async def _shutdown_once() -> bool:
    global _shutdown_task, _shutdown_complete
    with _shutdown_state_lock:
        if _shutdown_complete:
            return True
        if _shutdown_task is None:
            _shutdown_task = asyncio.create_task(_perform_shutdown())
        task = _shutdown_task
    try:
        result = await task
    except Exception:
        logger.exception("shutdown_failed")
        result = False
    finally:
        with _shutdown_state_lock:
            if task.done():
                _shutdown_complete = True
    return bool(result)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        clear_stale_task_states(db)
        reset_active_task_states(db)
        settings_row = db.query(Settings).first()
        if settings_row:
            settings.apply_tickflow_env_from_settings(settings_row)
        schedule_time = settings_row.schedule_time if settings_row else "15:35"
    finally:
        db.close()

    init_scheduler(schedule_time)
    try:
        yield
    finally:
        await _shutdown_once()


app = FastAPI(title="Stock Analysis Dashboard", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

Base.metadata.create_all(bind=engine)
migrate_settings_schema(engine)
migrate_watchlist_stock_code(engine)
migrate_mail_delivery_record_schema(engine)
migrate_stock_report_current_price(engine)
migrate_notification_log_schema(engine)
migrate_analysis_task_state_schema(engine)

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

app.include_router(watchlist.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(market_data.router, prefix="/api")
app.include_router(agent_chat.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
