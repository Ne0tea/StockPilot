from pathlib import Path
import sys
from datetime import date
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import scheduler


class _Field:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)


class _SettingsModel:
    pass


class _PortfolioModel:
    status = _Field("status")


class _WatchlistModel:
    is_active = _Field("is_active")


class _StockReportModel:
    stock_code = _Field("stock_code")
    date = _Field("date")


class _MailDeliveryRecord:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.predicates = []

    def filter(self, *predicates):
        self.predicates.extend(predicates)
        return self

    def first(self):
        if self.model is _SettingsModel:
            return self.session.settings
        if self.model is _StockReportModel:
            stock_code = None
            report_date = None
            for _, field, value in self.predicates:
                if field == "stock_code":
                    stock_code = value
                if field == "date":
                    report_date = value
            self.session.report_queries.append((stock_code, report_date))
            return self.session.reports.get((stock_code, report_date))
        raise AssertionError(f"unexpected first() model: {self.model}")

    def all(self):
        if self.model is _PortfolioModel:
            return list(self.session.holdings)
        if self.model is _WatchlistModel:
            return list(self.session.watchlist)
        raise AssertionError(f"unexpected all() model: {self.model}")


class _FakeSession:
    def __init__(self):
        self.settings = SimpleNamespace()
        self.holdings = [
            SimpleNamespace(stock_code="600000", stock_name="PF Bank", status="holding"),
        ]
        self.watchlist = [
            SimpleNamespace(stock_code="AAPL", name="Apple", is_active=True),
        ]
        self.reports = {
            ("600000", date(2026, 6, 11)): SimpleNamespace(
                score_total=90,
                recommendation="buy",
                action="hold",
                reason="cn report",
                target_price=10.0,
                stop_loss_price=8.0,
                entry_price=9.0,
            ),
            ("AAPL", date(2026, 6, 12)): SimpleNamespace(
                score_total=85,
                recommendation="watch",
                action="buy",
                reason="us report",
                target_price=200.0,
                stop_loss_price=180.0,
                entry_price=190.0,
            ),
        }
        self.report_queries = []
        self.added = []
        self.commits = 0
        self.closed = False

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_resolve_report_date_for_stock_passes_market_to_notification_date(monkeypatch):
    seen = {}

    monkeypatch.setattr(scheduler, "get_market_for_stock", lambda code: "cn")

    def fake_get_notification_report_date(market):
        seen["market"] = market
        return date(2026, 6, 11)

    monkeypatch.setattr(scheduler, "get_notification_report_date", fake_get_notification_report_date)

    resolved = scheduler._resolve_report_date_for_stock("600000")

    assert resolved == date(2026, 6, 11)
    assert seen["market"] == "cn"


def test_daily_report_job_uses_per_stock_report_date_for_holdings_and_watchlist(monkeypatch):
    session = _FakeSession()
    captured_report_payload = {}

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: session)
    monkeypatch.setattr(scheduler, "Settings", _SettingsModel)
    monkeypatch.setattr(scheduler, "Portfolio", _PortfolioModel)
    monkeypatch.setattr(scheduler, "Watchlist", _WatchlistModel)
    monkeypatch.setattr(scheduler, "StockReport", _StockReportModel)
    monkeypatch.setattr(scheduler, "MailDeliveryRecord", _MailDeliveryRecord)
    monkeypatch.setattr(scheduler, "email_configured", lambda settings: True)
    monkeypatch.setattr(scheduler, "wechat_configured", lambda settings: False)
    def fake_build_daily_report_markdown(holding_recs, watchlist_signals, **kwargs):
        captured_report_payload["holding_recs"] = holding_recs
        captured_report_payload["watchlist_signals"] = watchlist_signals
        captured_report_payload["kwargs"] = kwargs
        return "content"

    monkeypatch.setattr(scheduler, "build_daily_report_markdown", fake_build_daily_report_markdown)
    monkeypatch.setattr(scheduler, "send_email", lambda settings, content, subject: (True, None))
    monkeypatch.setattr(
        scheduler,
        "_resolve_report_date_for_stock",
        lambda code: {
            "600000": date(2026, 6, 11),
            "AAPL": date(2026, 6, 12),
        }[code],
    )

    class _FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 13)

    monkeypatch.setattr(scheduler, "date", _FakeDate)

    scheduler.daily_report_job()

    assert ("600000", date(2026, 6, 11)) in session.report_queries
    assert ("AAPL", date(2026, 6, 12)) in session.report_queries
    assert ("600000", date(2026, 6, 13)) not in session.report_queries
    assert ("AAPL", date(2026, 6, 13)) not in session.report_queries
    assert captured_report_payload["holding_recs"] == [
        {
            "code": "600000",
            "name": "PF Bank",
            "score_total": 90,
            "action": "hold",
            "reason": "cn report",
            "target_price": 10.0,
            "stop_loss_price": 8.0,
        }
    ]
    assert captured_report_payload["watchlist_signals"] == [
        {
            "code": "AAPL",
            "name": "Apple",
            "score_total": 85,
            "recommendation": "watch",
            "entry_price": 190.0,
        }
    ]
