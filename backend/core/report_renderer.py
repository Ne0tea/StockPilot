import glob
import os
import re
from datetime import date
from typing import Optional

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reports",
)


def ensure_reports_root() -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    return REPORTS_DIR


def build_report_paths(stock_code: str, report_date: Optional[date] = None) -> tuple[str, str]:
    report_date = report_date or date.today()
    absolute_dir = os.path.join(ensure_reports_root(), stock_code)
    os.makedirs(absolute_dir, exist_ok=True)
    filename = f"{report_date.isoformat()}.html"
    absolute_path = os.path.join(absolute_dir, filename)
    relative_path = f"reports/{stock_code}/{filename}"
    return absolute_path, relative_path


def build_report_instruction_target(stock_code: str, report_date: Optional[date] = None) -> str:
    """Absolute HTML target path passed to the agent.

    The backend only serves files under ``REPORTS_DIR``; using an absolute path
    avoids the agent resolving ``<code>/<date>.html`` relative to its home dir.
    """
    absolute_path, _ = build_report_paths(stock_code, report_date)
    return absolute_path


_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def build_markdown_report_path(
    stock_code: str, name: str, report_date: Optional[date] = None
) -> tuple[str, str]:
    """Canonical on-disk path for the report markdown.

    Mirrors the ``<code>_<名称>_分析报告_<yyyymmdd>.md`` naming the report
    listing already recognises (see ``MARKDOWN_REPORT_RE`` in
    ``report_listing``), so a persisted file is picked up as the summary source
    on the next scan without any extra wiring.
    """
    report_date = report_date or date.today()
    compact = report_date.strftime("%Y%m%d")
    safe_name = _UNSAFE_FILENAME_RE.sub("", name or "").strip() or stock_code
    filename = f"{stock_code}_{safe_name}_分析报告_{compact}.md"
    absolute_path = os.path.join(ensure_reports_root(), filename)
    return absolute_path, f"reports/{filename}"


def save_report_markdown(
    stock_code: str, name: str, markdown_content: str, report_date: Optional[date] = None
) -> str:
    """Persist the report markdown to disk and return its relative path.

    Returns "" when there is no content to write. Stale same-day markdown files
    for the stock (e.g. an earlier name spelling) are removed first so a
    regenerated report does not leave duplicate entries behind.
    """
    if not markdown_content or not markdown_content.strip():
        return ""

    report_date = report_date or date.today()
    compact = report_date.strftime("%Y%m%d")
    reports_root = ensure_reports_root()
    for stale in glob.glob(
        os.path.join(reports_root, f"{stock_code}_*_分析报告_{compact}.md")
    ):
        try:
            os.remove(stale)
        except OSError:
            pass

    absolute_path, relative_path = build_markdown_report_path(stock_code, name, report_date)
    with open(absolute_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    return relative_path


def relative_report_path(absolute_path: str) -> str:
    normalized = absolute_path.replace("\\", "/")
    reports_root = ensure_reports_root().replace("\\", "/").rstrip("/")
    if normalized.startswith(reports_root + "/"):
        return f"reports/{normalized[len(reports_root) + 1:]}"
    match = re.search(r"(^|/)reports/(.+)$", normalized)
    if match:
        return f"reports/{match.group(2)}"
    return normalized.lstrip("/")


def move_generated_report_html(stock_code: str, report_date: Optional[date] = None) -> str:
    report_date = report_date or date.today()
    absolute_dest, relative_dest = build_report_paths(stock_code, report_date)
    if os.path.exists(absolute_dest):
        return relative_dest

    candidates: list[str] = []
    nested_exact = os.path.join(
        ensure_reports_root(),
        "reports",
        stock_code,
        f"{report_date.isoformat()}.html",
    )
    if os.path.exists(nested_exact):
        candidates.append(nested_exact)

    nested_pattern = os.path.join(ensure_reports_root(), "reports", stock_code, "*.html")
    candidates.extend(sorted(glob.glob(nested_pattern), reverse=True))

    home_exact = os.path.expanduser(
        os.path.join("~", stock_code, f"{report_date.isoformat()}.html")
    )
    if os.path.exists(home_exact):
        candidates.append(home_exact)

    root_pattern = os.path.join(ensure_reports_root(), f"*{stock_code}*.html")
    candidates.extend(sorted(glob.glob(root_pattern), reverse=True))

    seen: set[str] = set()
    for source_path in candidates:
        if source_path in seen:
            continue
        seen.add(source_path)
        if os.path.abspath(source_path) == os.path.abspath(absolute_dest):
            return relative_dest
        try:
            os.replace(source_path, absolute_dest)
        except OSError:
            return relative_report_path(source_path)
        return relative_dest
    return ""


def extract_report_markdown(content: str) -> str:
    if not content:
        return ""

    patterns = [
        r"(?m)^#\s+.+投资分析报告.*$",
        r"(?m)^##\s*一、基本信息\s*$",
        r"(?m)^###\s*📋\s*综合评分\s*$",
    ]
    start_index = 0
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            start_index = match.start()
            break

    report = content[start_index:].strip()
    return report or content.strip()
