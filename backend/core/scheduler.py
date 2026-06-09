from apscheduler.schedulers.background import BackgroundScheduler
from db.database import SessionLocal
from db.models import MailDeliveryRecord, Settings, Watchlist, StockReport, Portfolio
from core.notify import send_email, send_wechat, build_daily_report_markdown, email_configured, wechat_configured
from core.report_storage import cleanup_old_reports
from datetime import date
import logging

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def daily_report_job():
    db = SessionLocal()
    try:
        today = date.today()
        settings = db.query(Settings).first()
        if not settings:
            return
        if not email_configured(settings) and not wechat_configured(settings):
            return

        holdings = db.query(Portfolio).filter(Portfolio.status == "holding").all()
        holding_codes = {p.stock_code for p in holdings}

        holding_recs = []
        holding_missing = []
        for pos in holdings:
            report = db.query(StockReport).filter(
                StockReport.stock_code == pos.stock_code,
                StockReport.date == today,
            ).first()
            if not report:
                holding_missing.append({
                    "code": pos.stock_code,
                    "name": pos.stock_name or "",
                })
                continue
            holding_recs.append({
                "code": pos.stock_code, "name": pos.stock_name or "",
                "score_total": report.score_total,
                "recommendation": report.recommendation,
                "action": report.action, "reason": report.reason,
                "target_price": report.target_price,
                "stop_loss_price": report.stop_loss_price,
                "entry_price": report.entry_price,
            })

        watchlist = db.query(Watchlist).filter(Watchlist.is_active == True).all()
        watchlist_signals = []
        watchlist_missing = []
        for stock in watchlist:
            if stock.stock_code in holding_codes:
                continue
            report = db.query(StockReport).filter(
                StockReport.stock_code == stock.stock_code,
                StockReport.date == today,
            ).first()
            if not report:
                watchlist_missing.append({
                    "code": stock.stock_code,
                    "name": stock.name,
                })
                continue
            watchlist_signals.append({
                "code": stock.stock_code, "name": stock.name,
                "score_total": report.score_total,
                "recommendation": report.recommendation,
                "action": report.action, "reason": report.reason,
                "target_price": report.target_price,
                "stop_loss_price": report.stop_loss_price,
                "entry_price": report.entry_price,
            })

        has_missing = bool(holding_missing or watchlist_missing)
        subject_prefix = "📊 每日股票分析报告"
        if has_missing:
            subject_prefix += "（部分缺失）"
        subject = f"{subject_prefix} - {today.isoformat()}"
        content = build_daily_report_markdown(
            holding_recs,
            watchlist_signals,
            holding_missing=holding_missing,
            watchlist_missing=watchlist_missing,
        )

        email_ok = True
        if email_configured(settings):
            email_ok, _ = send_email(settings, content=content, subject=subject)

        if wechat_configured(settings):
            send_wechat(settings, content=content, subject=subject)

        if email_ok:
            db.add(
                MailDeliveryRecord(
                    delivery_date=today,
                    report_date=today,
                    subject=subject,
                    holding_codes=",".join(item["code"] for item in holding_recs if item.get("code")),
                    holding_names=",".join(item["name"] for item in holding_recs if item.get("name")),
                    status="sent",
                )
            )
            db.commit()
    except Exception:
        logger.exception("daily_report_job 执行失败")
    finally:
        db.close()


def cleanup_job():
    cleanup_old_reports(days=90)


def init_scheduler(schedule_time: str = "15:35"):
    hour, minute = map(int, schedule_time.split(":"))
    scheduler.add_job(daily_report_job, "cron", hour=hour, minute=minute, id="daily_report", replace_existing=True)
    scheduler.add_job(cleanup_job, "cron", day=1, hour=3, id="cleanup", replace_existing=True)
    scheduler.start()


def reschedule_daily_report(schedule_time: str):
    hour, minute = map(int, schedule_time.split(":"))
    scheduler.reschedule_job("daily_report", trigger="cron", hour=hour, minute=minute)
