from datetime import date

from api.watchlist import _build_report_reference_date_map, _resolve_reference_report


def test_build_report_reference_date_map_uses_market_aware_dates(monkeypatch):
    stock_snapshots = [
        {"stock_code": "600519", "market": "sh"},
        {"stock_code": "00700", "market": "hk"},
        {"stock_code": "AAPL", "market": "us"},
    ]

    expected_dates = {
        "600519": "2026-06-19",
        "00700": "2026-06-19",
        "AAPL": "2026-06-18",
    }

    def fake_resolve_stock_report_date(code):
        return date.fromisoformat(expected_dates[code])

    monkeypatch.setattr(
        "api.watchlist.resolve_stock_report_date",
        fake_resolve_stock_report_date,
    )

    assert _build_report_reference_date_map(stock_snapshots) == expected_dates


def test_build_report_reference_date_map_skips_missing_codes(monkeypatch):
    stock_snapshots = [
        {"stock_code": "600519", "market": "sh"},
        {"stock_code": "", "market": "us"},
        {"market": "hk"},
    ]

    monkeypatch.setattr(
        "api.watchlist.resolve_stock_report_date",
        lambda code: date(2026, 6, 19),
    )

    assert _build_report_reference_date_map(stock_snapshots) == {"600519": "2026-06-19"}


def test_resolve_reference_report_matches_reference_date_record():
    history = [
        {"date": "2026-06-19", "markdown_file_path": "reports/600519_a_分析报告_20260619.md"},
        {"date": "2026-06-20", "markdown_file_path": "reports/600519_a_分析报告_20260620.md"},
    ]

    assert _resolve_reference_report(history, "2026-06-19") == {
        "date": "2026-06-19",
        "markdown_file_path": "reports/600519_a_分析报告_20260619.md",
    }


def test_resolve_reference_report_prefers_html_ready_on_reference_date():
    history = [
        {"date": "2026-06-19", "markdown_file_path": "reports/600519_a_分析报告_20260619.md"},
        {
            "date": "2026-06-19",
            "report_file_path": "reports/600519/2026-06-19.html",
            "html_status": "ready",
        },
        {
            "date": "2026-06-20",
            "report_file_path": "reports/600519/2026-06-20.html",
            "html_status": "ready",
        },
    ]

    assert _resolve_reference_report(history, "2026-06-19") == {
        "date": "2026-06-19",
        "report_file_path": "reports/600519/2026-06-19.html",
        "html_status": "ready",
    }
