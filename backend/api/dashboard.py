from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import MailDeliveryRecord, NotificationLog, Watchlist, StockReport, Portfolio

router = APIRouter(tags=["dashboard"])

def _latest_report_item(code, name, report):
    return {
        "code": code, "name": name,
        "score_total": report.score_total,
        "recommendation": report.recommendation,
        "action": report.action, "reason": report.reason,
        "target_price": report.target_price,
        "stop_loss_price": report.stop_loss_price,
        "entry_price": report.entry_price,
        "current_price": report.current_price,
        "date": report.date.isoformat() if report.date else None,
    }

@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    holdings = db.query(Portfolio).filter(Portfolio.status == "holding").all()
    holding_codes = {p.stock_code for p in holdings}

    holding_recommendations = []
    for pos in holdings:
        report = db.query(StockReport).filter(
            StockReport.stock_code == pos.stock_code
        ).order_by(StockReport.date.desc()).first()
        if report:
            holding_recommendations.append(
                {
                    **_latest_report_item(pos.stock_code, pos.stock_name or "", report),
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
                    "action": None, "reason": None,
                    "target_price": None, "stop_loss_price": None,
                    "entry_price": None, "current_price": None,
                    "date": None,
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
        report = db.query(StockReport).filter(
            StockReport.stock_code == stock.stock_code
        ).order_by(StockReport.date.desc()).first()
        if report:
            item = _latest_report_item(stock.stock_code, stock.name, report)
            item["has_report"] = True
            item["price"] = report.current_price
            item["price_date"] = report.date.isoformat() if report.date else None
        else:
            item = {
                "code": stock.stock_code, "name": stock.name,
                "score_total": None, "recommendation": None,
                "action": None, "reason": None,
                "target_price": None, "stop_loss_price": None,
                "entry_price": None, "current_price": None,
                "date": None,
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
    rows = db.query(MailDeliveryRecord).order_by(
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
    rows = db.query(NotificationLog).order_by(
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
