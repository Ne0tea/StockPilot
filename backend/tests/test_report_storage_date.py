from datetime import date, datetime
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import report_storage


def test_stock_report_date_uses_notification_report_date_even_before_market_open(monkeypatch):
    assert not hasattr(report_storage, "is_market_open")
    monkeypatch.setattr(report_storage, "get_market_for_stock", lambda code: "cn")
    monkeypatch.setattr(
        report_storage,
        "get_notification_report_date",
        lambda market, current_time=None: date(2026, 6, 11),
    )

    assert report_storage.resolve_stock_report_date("600000") == date(2026, 6, 11)


def test_stock_report_dates_include_precise_minute_report_time(monkeypatch):
    captured = {}

    monkeypatch.setattr(report_storage, "get_market_for_stock", lambda code: "cn")

    def fake_notification_date(market, current_time=None):
        captured["market"] = market
        captured["current_time"] = current_time
        return date(2026, 6, 12)

    monkeypatch.setattr(report_storage, "get_notification_report_date", fake_notification_date)
    report_time = datetime(2026, 6, 14, 18, 37, 59, 123456)

    resolved_time, data_date = report_storage.resolve_stock_report_terms("600000", report_time)

    assert resolved_time == datetime(2026, 6, 14, 18, 37)
    assert data_date == date(2026, 6, 12)
    assert captured["market"] == "cn"
    assert captured["current_time"].hour == 18
    assert captured["current_time"].minute == 37
