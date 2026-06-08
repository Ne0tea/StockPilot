from contextlib import asynccontextmanager
from pathlib import Path

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

assert_runtime_dependencies()

from api import watchlist, analyze, portfolio, dashboard, settings, market_data, agent_chat

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
        if scheduler.running:
            scheduler.shutdown(wait=False)


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
