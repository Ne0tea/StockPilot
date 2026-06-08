from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date as date_type, date
from db.database import get_db
from db.models import Portfolio, StockReport, TradeLog

router = APIRouter(tags=["portfolio"])

class TradeIn(BaseModel):
    stock_code: str
    stock_name: str
    action: str
    price: float
    shares: int
    date: date_type

@router.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    holdings = db.query(Portfolio).filter(Portfolio.status == "holding").all()
    holding_positions = [
        {
            "id": row.id,
            "stock_code": row.stock_code,
            "stock_name": row.stock_name or "",
            "shares": row.shares,
            "buy_date": row.buy_date.isoformat() if row.buy_date else None,
            "holding_cost": round((row.shares or 0) * (row.cost_price or 0), 2),
            "status": row.status,
        }
        for row in holdings
    ]
    closed_positions = _build_closed_positions(
        db.query(TradeLog).order_by(TradeLog.date.asc(), TradeLog.id.asc()).all()
    )

    price_map = _build_report_price_map(db, holding_positions + closed_positions)
    _attach_report_prices(holding_positions, price_map)
    _attach_report_prices(closed_positions, price_map)
    return {
        "holding_positions": holding_positions,
        "closed_positions": closed_positions,
    }


@router.get("/portfolio/profit-history")
def get_profit_history(db: Session = Depends(get_db)):
    trades = db.query(TradeLog).order_by(TradeLog.date.asc(), TradeLog.id.asc()).all()
    return _build_profit_history(trades)

@router.post("/portfolio/trade")
def record_trade(trade: TradeIn, db: Session = Depends(get_db)):
    log = TradeLog(
        stock_code=trade.stock_code, stock_name=trade.stock_name,
        action=trade.action, price=trade.price,
        shares=trade.shares, date=trade.date
    )
    db.add(log)

    pos = db.query(Portfolio).filter(
        Portfolio.stock_code == trade.stock_code,
        Portfolio.status == "holding"
    ).first()

    if trade.action == "buy":
        if pos:
            total_cost = pos.cost_price * pos.shares + trade.price * trade.shares
            pos.shares += trade.shares
            pos.cost_price = total_cost / pos.shares
        else:
            pos = Portfolio(
                stock_code=trade.stock_code, stock_name=trade.stock_name,
                shares=trade.shares, cost_price=trade.price, buy_date=trade.date
            )
            db.add(pos)
    elif trade.action == "sell" and pos:
        pos.shares -= trade.shares
        if pos.shares <= 0:
            pos.status = "closed"

    db.commit()
    return {"ok": True}

@router.get("/portfolio/trades")
def get_trades(stock_code: str = None, db: Session = Depends(get_db)):
    q = db.query(TradeLog).order_by(TradeLog.date.desc())
    if stock_code:
        q = q.filter(TradeLog.stock_code == stock_code)
    return q.limit(100).all()


def _build_closed_positions(trades: list[TradeLog]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    closed_positions: list[dict] = []

    for trade in trades:
        stock_code = trade.stock_code
        if trade.action == "buy":
            buckets.setdefault(stock_code, []).append(
                {
                    "shares": trade.shares,
                    "price": trade.price,
                    "date": trade.date,
                    "stock_name": trade.stock_name or "",
                }
            )
            continue

        if trade.action != "sell":
            continue

        remaining = trade.shares
        lots = buckets.setdefault(stock_code, [])
        realized_profit = 0.0
        matched_shares = 0
        buy_dates: list[str] = []
        stock_name = trade.stock_name or ""

        while remaining > 0 and lots:
            lot = lots[0]
            matched = min(remaining, lot["shares"])
            realized_profit += (trade.price - lot["price"]) * matched
            matched_shares += matched
            stock_name = stock_name or lot["stock_name"]
            if lot["date"]:
                buy_dates.append(lot["date"].isoformat())
            lot["shares"] -= matched
            remaining -= matched
            if lot["shares"] <= 0:
                lots.pop(0)

        if matched_shares:
            closed_positions.append(
                {
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "shares": matched_shares,
                    "buy_date": buy_dates[0] if buy_dates else None,
                    "close_date": trade.date.isoformat() if trade.date else None,
                    "realized_profit": round(realized_profit, 2),
                    "status": "closed",
                }
            )

    return list(reversed(closed_positions))


def _build_profit_history(trades: list[TradeLog]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    total_buy_cost = 0.0
    cumulative_profit = 0.0
    history: list[dict] = []
    first_buy_date = None

    for trade in trades:
        if trade.action == "buy":
            if first_buy_date is None and trade.date:
                first_buy_date = trade.date
            buckets.setdefault(trade.stock_code, []).append(
                {
                    "shares": trade.shares,
                    "price": trade.price,
                }
            )
            total_buy_cost += (trade.price or 0) * (trade.shares or 0)
            continue

        if trade.action != "sell":
            continue

        remaining = trade.shares or 0
        realized_profit = 0.0
        lots = buckets.setdefault(trade.stock_code, [])

        while remaining > 0 and lots:
            lot = lots[0]
            matched = min(remaining, lot["shares"])
            realized_profit += ((trade.price or 0) - (lot["price"] or 0)) * matched
            lot["shares"] -= matched
            remaining -= matched
            if lot["shares"] <= 0:
                lots.pop(0)

        if realized_profit or (trade.shares or 0):
            cumulative_profit += realized_profit
            cumulative_pct = round((cumulative_profit / total_buy_cost) * 100, 2) if total_buy_cost else 0.0
            history.append(
                {
                    "date": trade.date.isoformat() if trade.date else None,
                    "cumulative_profit": round(cumulative_profit, 2),
                    "cumulative_pct": cumulative_pct,
                }
            )

    if first_buy_date is not None and not history:
        today = date.today()
        history.append(
            {
                "date": first_buy_date.isoformat(),
                "cumulative_profit": 0.0,
                "cumulative_pct": 0.0,
            }
        )
        if today != first_buy_date:
            history.append(
                {
                    "date": today.isoformat(),
                    "cumulative_profit": 0.0,
                    "cumulative_pct": 0.0,
                }
            )

    return history


def _build_report_price_map(db: Session, positions: list[dict]) -> dict[str, dict]:
    """Look up the latest StockReport row per stock code and return its price snapshot."""
    codes = {item.get("stock_code") for item in positions if item.get("stock_code")}
    if not codes:
        return {}

    price_map: dict[str, dict] = {}
    for code in codes:
        report = (
            db.query(StockReport)
            .filter(StockReport.stock_code == code)
            .order_by(StockReport.date.desc(), StockReport.created_at.desc(), StockReport.id.desc())
            .first()
        )
        if report is None:
            price_map[code] = {"has_report": False}
            continue
        price_map[code] = {
            "has_report": True,
            "price": report.current_price,
            "price_date": report.date.isoformat() if report.date else None,
        }
    return price_map


def _attach_report_prices(positions: list[dict], price_map: dict[str, dict]):
    for item in positions:
        info = price_map.get(item.get("stock_code"), {"has_report": False})
        item["has_report"] = bool(info.get("has_report"))
        item["price"] = info.get("price")
        item["price_date"] = info.get("price_date")
