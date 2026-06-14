from datetime import date
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import report_listing


def test_markdown_report_date_uses_filename_date_mapped_to_report_trading_date(tmp_path, monkeypatch):
    monkeypatch.setattr(
        report_listing,
        "parse_report_markdown",
        lambda content: _summary(),
    )
    monkeypatch.setattr(report_listing, "get_market_for_stock", lambda code: "cn")
    monkeypatch.setattr(
        report_listing,
        "get_notification_report_date",
        lambda market, current_time=None: date(2026, 6, 12),
    )
    path = tmp_path / "600000_浦发银行_分析报告_20260614.md"
    path.write_text("# 浦发银行投资分析报告\n\n**报告日期**：2026-06-13\n", encoding="utf-8")

    record = report_listing._parse_markdown_report(path, {})

    assert record["date"] == date(2026, 6, 12)
    assert record["report_time"].isoformat() == "2026-06-14T18:00:00"


def test_markdown_report_time_prefers_precise_time_field(tmp_path, monkeypatch):
    monkeypatch.setattr(
        report_listing,
        "parse_report_markdown",
        lambda content: _summary(),
    )
    monkeypatch.setattr(report_listing, "get_market_for_stock", lambda code: "cn")
    captured = {}

    def fake_notification_date(market, current_time=None):
        captured["current_time"] = current_time
        return date(2026, 6, 12)

    monkeypatch.setattr(report_listing, "get_notification_report_date", fake_notification_date)
    path = tmp_path / "600000_浦发银行_分析报告_20260614.md"
    path.write_text("# 浦发银行投资分析报告\n\n**报告生成时间**：2026-06-14 09:15\n", encoding="utf-8")

    record = report_listing._parse_markdown_report(path, {})

    assert record["report_time"].isoformat() == "2026-06-14T09:15:00"
    assert record["date"] == date(2026, 6, 12)
    assert captured["current_time"].hour == 9
    assert captured["current_time"].minute == 15


def test_markdown_report_date_uses_filename_date_at_18_when_precise_time_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        report_listing,
        "parse_report_markdown",
        lambda content: _summary(),
    )
    monkeypatch.setattr(report_listing, "get_market_for_stock", lambda code: "cn")
    captured = {}

    def fake_notification_date(market, current_time=None):
        captured["market"] = market
        captured["current_time"] = current_time
        return current_time.date()

    monkeypatch.setattr(report_listing, "get_notification_report_date", fake_notification_date)
    path = tmp_path / "600000_浦发银行_分析报告_20260614.md"
    path.write_text("# 浦发银行投资分析报告\n\n暂无日期字段\n", encoding="utf-8")

    record = report_listing._parse_markdown_report(path, {})

    assert record["date"] == date(2026, 6, 14)
    assert captured["market"] == "cn"
    assert captured["current_time"].hour == 18
    assert captured["current_time"].minute == 0


def test_markdown_report_date_falls_back_to_filename_on_calendar_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        report_listing,
        "parse_report_markdown",
        lambda content: _summary(),
    )
    monkeypatch.setattr(report_listing, "get_market_for_stock", lambda code: "cn")
    monkeypatch.setattr(
        report_listing,
        "get_notification_report_date",
        lambda market, current_time=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    path = tmp_path / "600000_浦发银行_分析报告_20260614.md"
    path.write_text("# 浦发银行投资分析报告\n\n暂无日期字段\n", encoding="utf-8")

    record = report_listing._parse_markdown_report(path, {})

    assert record["date"] == date(2026, 6, 14)


def _summary():
    class Summary:
        score_total = 7
        score_fundamental = 7
        score_news = 7
        score_capital = 7
        score_technical = 7
        recommendation = "推荐买入"
        action = "持有"
        reason = "test"
        target_price = 10
        stop_loss_price = 8
        entry_price = 9
        current_price = 9.5

    return Summary()
