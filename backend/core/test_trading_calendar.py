from datetime import date, datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from backend.core.src.core import trading_calendar


class TradingCalendarFallbackTests(TestCase):
    def test_notification_report_date_falls_back_to_previous_business_day_before_open_when_calendar_unavailable(self):
        lookup = SimpleNamespace(
            market="cn",
            market_now=datetime(2026, 7, 2, 8, 30),
            fallback_date=date(2026, 7, 2),
            known_market=True,
            calendar_available=False,
        )

        with patch.object(trading_calendar, "_resolve_market_session_lookup", return_value=lookup):
            result = trading_calendar.get_notification_report_date(
                "cn",
                current_time=datetime(2026, 7, 2, 8, 30),
            )

        self.assertEqual(result, date(2026, 7, 1))

    def test_notification_report_date_keeps_current_day_after_open_when_calendar_unavailable(self):
        lookup = SimpleNamespace(
            market="cn",
            market_now=datetime(2026, 7, 2, 13, 30),
            fallback_date=date(2026, 7, 2),
            known_market=True,
            calendar_available=False,
        )

        with patch.object(trading_calendar, "_resolve_market_session_lookup", return_value=lookup):
            result = trading_calendar.get_notification_report_date(
                "cn",
                current_time=datetime(2026, 7, 2, 13, 30),
            )

        self.assertEqual(result, date(2026, 7, 2))
