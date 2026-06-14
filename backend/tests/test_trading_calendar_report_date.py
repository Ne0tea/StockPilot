from pathlib import Path
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.src.core import trading_calendar as tc


CALENDAR_REQUIRED = pytest.mark.skipif(
    not tc._XCALS_AVAILABLE,
    reason="exchange-calendars is required for calendar-backed report-date tests",
)


@CALENDAR_REQUIRED
def test_cn_premarket_uses_previous_trading_report_date():
    current_time = datetime(2026, 6, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-11"


@CALENDAR_REQUIRED
def test_cn_intraday_uses_today_report_date_after_open():
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"


@CALENDAR_REQUIRED
def test_cn_lunch_break_still_uses_today_report_date():
    current_time = datetime(2026, 6, 12, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"


@CALENDAR_REQUIRED
def test_cn_postmarket_uses_today_report_date():
    current_time = datetime(2026, 6, 12, 15, 5, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"


@CALENDAR_REQUIRED
def test_cn_non_trading_day_uses_previous_trading_report_date():
    current_time = datetime(2026, 6, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"


@CALENDAR_REQUIRED
def test_cn_exact_open_boundary_uses_today_report_date():
    current_time = datetime(2026, 6, 12, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"


def test_unknown_market_notification_date_falls_back_to_natural_date():
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_notification_report_date("unknown", current_time=current_time)) == "2026-06-12"


def test_unknown_market_effective_date_falls_back_to_natural_date():
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert str(tc.get_effective_trading_date("unknown", current_time=current_time)) == "2026-06-12"


def test_unknown_market_phase_is_unknown():
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert tc.infer_market_phase("unknown", current_time=current_time) == tc.MarketPhase.UNKNOWN


def test_effective_trading_date_fail_opens_to_natural_date_on_lookup_error(monkeypatch):
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def broken_lookup(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tc, "_resolve_market_session_lookup", broken_lookup)

    assert str(tc.get_effective_trading_date("cn", current_time=current_time)) == "2026-06-12"


def test_notification_report_date_fail_opens_to_natural_date_on_lookup_error(monkeypatch):
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def broken_lookup(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tc, "_resolve_market_session_lookup", broken_lookup)

    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"


def test_infer_market_phase_fail_closes_to_unknown_on_lookup_error(monkeypatch):
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    def broken_lookup(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tc, "_resolve_market_session_lookup", broken_lookup)

    assert tc.infer_market_phase("cn", current_time=current_time) == tc.MarketPhase.UNKNOWN


def test_known_market_falls_back_when_xcals_unavailable(monkeypatch):
    current_time = datetime(2026, 6, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    monkeypatch.setattr(tc, "_XCALS_AVAILABLE", False)

    assert str(tc.get_effective_trading_date("cn", current_time=current_time)) == "2026-06-12"
    assert str(tc.get_notification_report_date("cn", current_time=current_time)) == "2026-06-12"
    assert tc.infer_market_phase("cn", current_time=current_time) == tc.MarketPhase.UNKNOWN
