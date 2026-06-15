from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import MailDeliveryRecord, NotificationLog, Watchlist, StockReport, Portfolio
from core.report_storage import resolve_stock_report_date

router = APIRouter(tags=["dashboard"])

def _report_reference_date(code):
    return resolve_stock_report_date(code).isoformat()


def _latest_report_item(code, name, report, report_reference_date):
    return {
        "code": code, "name": name,
        "score_total": report.score_total,
        "score_fundamental": report.score_fundamental,
        "score_news": report.score_news,
        "score_capital": report.score_capital,
        "score_technical": report.score_technical,
        "recommendation": report.recommendation,
        "action": report.action, "reason": report.reason,
        "target_price": report.target_price,
        "stop_loss_price": report.stop_loss_price,
        "entry_price": report.entry_price,
        "current_price": report.current_price,
        "report_file_path": report.report_file_path or "",
        "date": report.date.isoformat() if report.date else None,
        "report_reference_date": report_reference_date,
    }

@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    holdings = db.query(Portfolio).filter(Portfolio.status == "holding").all()
    holding_codes = {p.stock_code for p in holdings}

    holding_recommendations = []
    for pos in holdings:
        report_reference_date = _report_reference_date(pos.stock_code)
        report = db.query(StockReport).filter(
            StockReport.stock_code == pos.stock_code
        ).order_by(StockReport.date.desc()).first()
        if report:
            holding_recommendations.append(
                {
                    **_latest_report_item(pos.stock_code, pos.stock_name or "", report, report_reference_date),
                    "cost": round((pos.shares or 0) * (pos.cost_price or 0), 2),
                    "cost_price": pos.cost_price,
                    "has_report": True,
                    "price": report.current_price,
                    "price_date": report.date.isoformat() if report.date else None,
                }
            )
        else:
            holding_recommendations.append(
                {
                    "code": pos.stock_code, "name": pos.stock_name or "",
                    "score_total": None, "recommendation": None,
                    "score_fundamental": None, "score_news": None,
                    "score_capital": None, "score_technical": None,
                    "action": None, "reason": None,
                    "target_price": None, "stop_loss_price": None,
                    "entry_price": None, "current_price": None,
                    "report_file_path": "",
                    "date": None,
                    "report_reference_date": report_reference_date,
                    "cost": round((pos.shares or 0) * (pos.cost_price or 0), 2),
                    "cost_price": pos.cost_price,
                    "has_report": False,
                    "price": None,
                    "price_date": None,
                }
            )

    watchlist = db.query(Watchlist).filter(Watchlist.is_active == True).all()
    watchlist_signals = []
    for stock in watchlist:
        if stock.stock_code in holding_codes:
            continue
        report_reference_date = _report_reference_date(stock.stock_code)
        report = db.query(StockReport).filter(
            StockReport.stock_code == stock.stock_code
        ).order_by(StockReport.date.desc()).first()
        if report:
            item = _latest_report_item(stock.stock_code, stock.name, report, report_reference_date)
            item["has_report"] = True
            item["price"] = report.current_price
            item["price_date"] = report.date.isoformat() if report.date else None
        else:
            item = {
                "code": stock.stock_code, "name": stock.name,
                "score_total": None, "recommendation": None,
                "score_fundamental": None, "score_news": None,
                "score_capital": None, "score_technical": None,
                "action": None, "reason": None,
                "target_price": None, "stop_loss_price": None,
                "entry_price": None, "current_price": None,
                "report_file_path": "",
                "date": None,
                "report_reference_date": report_reference_date,
                "has_report": False,
                "price": None,
                "price_date": None,
            }
        item["market"] = stock.market
        watchlist_signals.append(item)

    total_value = sum(p.shares * p.cost_price for p in holdings)
    return {
        "holding_recommendations": holding_recommendations,
        "watchlist_signals": watchlist_signals,
        "portfolio_summary": {"total_positions": len(holdings), "total_cost": total_value}
    }


@router.get("/dashboard/delivery-records")
def get_delivery_records(db: Session = Depends(get_db)):
    rows = db.query(MailDeliveryRecord).filter(
        MailDeliveryRecord.is_hidden == False
    ).order_by(
        MailDeliveryRecord.delivery_date.desc(),
        MailDeliveryRecord.id.desc(),
    ).limit(30).all()

    return [
        {
            "id": row.id,
            "delivery_date": row.delivery_date.isoformat() if row.delivery_date else None,
            "report_date": row.report_date.isoformat() if row.report_date else None,
            "subject": row.subject,
            "holding_codes": [item for item in (row.holding_codes or "").split(",") if item],
            "holding_names": [item for item in (row.holding_names or "").split(",") if item],
            "status": row.status,
        }
        for row in rows
    ]


@router.get("/dashboard/notifications")
def get_notifications(db: Session = Depends(get_db)):
    rows = db.query(NotificationLog).filter(
        NotificationLog.is_hidden == False
    ).order_by(
        NotificationLog.created_at.desc()
    ).limit(50).all()
    return [
        {
            "id": row.id,
            "channel": row.channel,
            "status": row.status,
            "subject": row.subject,
            "message_preview": row.message_preview,
            "error_message": row.error_message,
            "is_test": row.is_test,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.post("/dashboard/notifications/clear")
def clear_notifications(db: Session = Depends(get_db)):
    hidden_delivery_records = db.query(MailDeliveryRecord).filter(
        MailDeliveryRecord.is_hidden == False
    ).update({MailDeliveryRecord.is_hidden: True}, synchronize_session=False)
    hidden_notification_logs = db.query(NotificationLog).filter(
        NotificationLog.is_hidden == False
    ).update({NotificationLog.is_hidden: True}, synchronize_session=False)
    db.commit()
    return {
        "hidden_delivery_records": hidden_delivery_records,
        "hidden_notification_logs": hidden_notification_logs,
    }
