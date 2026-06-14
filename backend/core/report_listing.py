from datetime import date, datetime, time
from pathlib import Path
from typing import Optional
import re
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.parser import parse_report_markdown
from core.report_renderer import REPORTS_DIR, move_generated_report_html, relative_report_path
from core.src.core.trading_calendar import get_market_for_stock, get_notification_report_date
from db.models import StockReport, Watchlist

MARKDOWN_REPORT_FILENAME_RE = r"(?P<code>\d{6})_(?P<name>.+?)_分析报告_(?P<date>\d{8})\.md"
MARKDOWN_REPORT_TIME_LABEL_RE = re.compile(
    r"(?:报告生成时间|生成时间|生成日期|报告日期|分析日期)"
    r"\s*(?:\*\*)?\s*[：:]\s*"
    r"(?:\*\*)?\s*"
    r"(?P<time>\d{4}(?:-\d{1,2}-\d{1,2}|年\d{1,2}月\d{1,2}日)"
    r"(?:[ T]\d{1,2}:\d{2}|[ T]\d{1,2}时\d{1,2}分))"
)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def list_reports(
    db: Session,
    code: Optional[str] = None,
    limit: Optional[int] = None,
    reports_root: Optional[str] = None,
):
    reports_root_path = Path(reports_root or REPORTS_DIR)
    stock_names = _load_stock_names(db, code)
    records = [
        _serialize_db_report(row, stock_names, reports_root_path) for row in _query_db_reports(db, code)
    ]
    if limit is not None:
        records = records[:limit]
    return records


def rescan_reports(db: Session, code: Optional[str] = None, reports_root: Optional[str] = None) -> dict:
    reports_root_path = Path(reports_root or REPORTS_DIR)
    stock_names = _load_stock_names(db, code)

    parsed_records: list[dict] = []
    failed_files: list[str] = []

    for path in _iter_markdown_report_paths(reports_root_path, code=code):
        try:
            record = _parse_markdown_report(path, stock_names)
        except Exception:
            failed_files.append(path.name)
            continue

        parsed_records.append(record)

    query = db.query(StockReport)
    if code:
        query = query.filter(StockReport.stock_code == code)
    query.delete(synchronize_session=False)

    for record in parsed_records:
        html_report_path = _resolve_html_report_path_from_record(record, reports_root_path)
        db.add(
            StockReport(
                stock_code=record["stock_code"],
                date=record["date"],
                score_total=record["score_total"],
                score_fundamental=record["score_fundamental"],
                score_news=record["score_news"],
                score_capital=record["score_capital"],
                score_technical=record["score_technical"],
                recommendation=record["recommendation"],
                action=record["action"],
                reason=record["reason"],
                target_price=record["target_price"],
                stop_loss_price=record["stop_loss_price"],
                entry_price=record["entry_price"],
                current_price=record["current_price"],
                report_file_path=html_report_path,
                report_time=record["report_time"],
            )
        )

    db.commit()
    return {
        "ok": True,
        "count": len(parsed_records),
        "code": code,
        "md_total": len(parsed_records) + len(failed_files),
        "parsed_ok": len(parsed_records),
        "parsed_failed": len(failed_files),
        "failed_files": failed_files,
    }


def _query_db_reports(db: Session, code: Optional[str]):
    query = db.query(StockReport)
    if code:
        query = query.filter(StockReport.stock_code == code)
    return query.order_by(
        StockReport.date.desc(),
        StockReport.created_at.desc(),
        StockReport.id.desc(),
    ).all()


def _load_stock_names(db: Session, code: Optional[str]) -> dict[str, str]:
    query = db.query(Watchlist)
    if code:
        query = query.filter(Watchlist.stock_code == code)
    return {row.stock_code: row.name for row in query.all()}


def _iter_markdown_report_paths(reports_root: Path, code: Optional[str]) -> list[Path]:
    if not reports_root.exists():
        return []

    matched_paths: list[Path] = []
    for path in sorted(reports_root.iterdir()):
        if not path.is_file():
            continue
        match = _match_markdown_report_filename(path.name)
        if not match:
            continue
        if code and match.group("code") != code:
            continue
        matched_paths.append(path)
    return matched_paths


def _serialize_db_report(
    report: StockReport,
    stock_names: dict[str, str],
    reports_root: Path,
) -> dict:
    report_date = report.date.isoformat() if report.date else ""
    report_time = (
        report.report_time.isoformat(timespec="minutes")
        if getattr(report, "report_time", None)
        else ""
    )
    created_at = report.created_at.isoformat() if report.created_at else ""
    normalized_path = _resolve_html_report_path(report, reports_root)
    markdown_path = _resolve_markdown_report_path(report, stock_names, reports_root)
    markdown_content = _read_text_if_exists(reports_root / markdown_path.removeprefix("reports/")) if markdown_path else ""
    return {
        "id": report.id,
        "stock_code": report.stock_code,
        "stock_name": stock_names.get(report.stock_code, ""),
        "date": report_date,
        "report_time": report_time,
        "score_total": report.score_total,
        "score_fundamental": report.score_fundamental,
        "score_news": report.score_news,
        "score_capital": report.score_capital,
        "score_technical": report.score_technical,
        "recommendation": report.recommendation,
        "action": report.action,
        "reason": report.reason,
        "target_price": report.target_price,
        "stop_loss_price": report.stop_loss_price,
        "entry_price": report.entry_price,
        "current_price": report.current_price,
        "report_file_path": normalized_path,
        "created_at": created_at,
        "source": "database",
        "html_status": "ready" if normalized_path else "missing",
        "markdown_file_path": markdown_path,
        "markdown_content": markdown_content,
    }


def _parse_markdown_report(path: Path, stock_names: dict[str, str]) -> dict:
    match = _match_markdown_report_filename(path.name)
    if not match:
        raise ValueError(path.name)

    stock_code = match.group("code")
    stock_name = match.group("name")
    filename_date = _date_from_compact(match.group("date"))
    content = path.read_text(encoding="utf-8")
    report_time = _extract_markdown_report_time(content) or _fallback_report_time_from_filename(filename_date)
    report_date = _resolve_report_date_from_time(stock_code, report_time)
    summary = parse_report_markdown(content)
    return {
        "stock_code": stock_code,
        "stock_name": stock_names.get(stock_code) or stock_name,
        "date": report_date,
        "report_time": report_time,
        "score_total": summary.score_total,
        "score_fundamental": summary.score_fundamental,
        "score_news": summary.score_news,
        "score_capital": summary.score_capital,
        "score_technical": summary.score_technical,
        "recommendation": summary.recommendation,
        "action": summary.action,
        "reason": summary.reason,
        "target_price": summary.target_price,
        "stop_loss_price": summary.stop_loss_price,
        "entry_price": summary.entry_price,
        "current_price": summary.current_price,
    }


def _resolve_html_report_path_from_record(record: dict, reports_root: Path) -> str:
    stock_code = record.get("stock_code")
    report_date = record.get("date")
    if not stock_code or not report_date:
        return ""

    for candidate_date in _report_file_candidate_dates(report_date, record.get("report_time")):
        candidate = reports_root / stock_code / f"{candidate_date.isoformat()}.html"
        if candidate.exists():
            return f"reports/{stock_code}/{candidate.name}"

    for candidate_date in _report_file_candidate_dates(report_date, record.get("report_time")):
        nested_candidate = reports_root / "reports" / stock_code / f"{candidate_date.isoformat()}.html"
        if not nested_candidate.exists():
            continue
        canonical_candidate = reports_root / stock_code / f"{candidate_date.isoformat()}.html"
        canonical_candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            nested_candidate.replace(canonical_candidate)
        except OSError:
            return f"reports/{stock_code}/{nested_candidate.name}"
        return f"reports/{stock_code}/{canonical_candidate.name}"

    return ""


def _match_markdown_report_filename(filename: str):
    return re.fullmatch(MARKDOWN_REPORT_FILENAME_RE, filename)


def _date_from_compact(value: str) -> date:
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")


def _fallback_report_time_from_filename(filename_date: date) -> datetime:
    return datetime.combine(filename_date, time(18, 0))


def _extract_markdown_report_time(content: str) -> Optional[datetime]:
    if not content:
        return None

    for match in MARKDOWN_REPORT_TIME_LABEL_RE.finditer(content):
        parsed = _parse_markdown_time_token(match.group("time"))
        if parsed:
            return parsed
    return None


def _parse_markdown_time_token(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None

    chinese_match = re.fullmatch(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日[ T]?(\d{1,2})时(\d{1,2})分",
        text,
    )
    if chinese_match:
        year, month, day, hour, minute = [int(part) for part in chinese_match.groups()]
        return _safe_datetime(year, month, day, hour, minute)

    iso_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})", text)
    if iso_match:
        year, month, day, hour, minute = [int(part) for part in iso_match.groups()]
        return _safe_datetime(year, month, day, hour, minute)
    return None


def _safe_datetime(year: int, month: int, day: int, hour: int, minute: int) -> Optional[datetime]:
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _resolve_report_date_from_time(stock_code: str, report_time: datetime) -> date:
    market = get_market_for_stock(stock_code)
    try:
        reference_time = report_time.replace(tzinfo=SHANGHAI_TZ)
        return get_notification_report_date(market, current_time=reference_time)
    except Exception:
        return report_time.date()


def _resolve_html_report_path(report: StockReport, reports_root: Path) -> str:
    if report.report_file_path:
        normalized_path = relative_report_path(report.report_file_path)
        html_path = reports_root / normalized_path.removeprefix("reports/")
        if html_path.exists():
            return normalized_path

    if not report.stock_code or not report.date:
        return ""

    for candidate_date in _report_file_candidate_dates(report.date, getattr(report, "report_time", None)):
        candidate = reports_root / report.stock_code / f"{candidate_date.isoformat()}.html"
        if candidate.exists():
            return f"reports/{report.stock_code}/{candidate.name}"

    moved_path = _repair_nested_html_path(report, reports_root)
    if moved_path:
        return moved_path
    return ""


def _repair_nested_html_path(report: StockReport, reports_root: Path) -> str:
    default_reports_root = Path(REPORTS_DIR).resolve()
    if reports_root.resolve() != default_reports_root:
        candidate_dates = _report_file_candidate_dates(report.date, getattr(report, "report_time", None))
        nested_candidate = reports_root / "reports" / report.stock_code / f"{candidate_dates[0].isoformat()}.html"
        canonical_candidate = reports_root / report.stock_code / f"{candidate_dates[0].isoformat()}.html"
        for candidate_date in candidate_dates:
            candidate = reports_root / "reports" / report.stock_code / f"{candidate_date.isoformat()}.html"
            if candidate.exists():
                nested_candidate = candidate
                canonical_candidate = reports_root / report.stock_code / f"{candidate_date.isoformat()}.html"
                break
        if not nested_candidate.exists():
            return ""
        canonical_candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            nested_candidate.replace(canonical_candidate)
        except OSError:
            return ""
        return f"reports/{report.stock_code}/{canonical_candidate.name}"

    for candidate_date in _report_file_candidate_dates(report.date, getattr(report, "report_time", None)):
        moved_path = move_generated_report_html(report.stock_code, candidate_date)
        if moved_path:
            return moved_path
    return ""


def _resolve_markdown_report_path(
    report: StockReport,
    stock_names: dict[str, str],
    reports_root: Path,
) -> str:
    if not report.stock_code or not report.date:
        return ""

    candidates = []
    for candidate_date in _report_file_candidate_dates(report.date, getattr(report, "report_time", None)):
        compact_date = candidate_date.strftime("%Y%m%d")
        candidates.extend(sorted(reports_root.glob(f"{report.stock_code}_*_分析报告_{compact_date}.md")))
    if not candidates:
        return ""

    preferred_name = (stock_names.get(report.stock_code) or "").strip()
    if preferred_name:
        for candidate_date in _report_file_candidate_dates(report.date, getattr(report, "report_time", None)):
            compact_date = candidate_date.strftime("%Y%m%d")
            preferred = reports_root / f"{report.stock_code}_{preferred_name}_分析报告_{compact_date}.md"
            if preferred.exists():
                return f"reports/{preferred.name}"

    return f"reports/{candidates[0].name}"


def _report_file_candidate_dates(report_date: date, report_time: Optional[datetime]) -> list[date]:
    dates = [report_date]
    if report_time and report_time.date() not in dates:
        dates.append(report_time.date())
    return dates


def _read_text_if_exists(path: Path) -> str:
    try:
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""
