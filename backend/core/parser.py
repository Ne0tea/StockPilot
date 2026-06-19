import re
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ReportSummary:
    score_total: float = 0
    score_fundamental: float = 0
    score_news: float = 0
    score_capital: float = 0
    score_technical: float = 0
    recommendation: str = ""
    action: str = ""
    reason: str = ""
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    entry_price: Optional[float] = None
    current_price: Optional[float] = None

_NUM = r"[¥￥]?\s*(\d+(?:\.\d+)?)"
_RECOMMENDATION_LEVELS = (
    "强烈推荐",
    "推荐买入",
    "观望等待",
    "谨慎操作",
    "建议回避",
)


def _recommendation_token_pattern(token: str) -> str:
    """Allow optional whitespace/markdown markers between recommendation chars."""
    return r"\s*".join(re.escape(ch) for ch in token)


def _build_recommendation_capture_group() -> str:
    return "(" + "|".join(_recommendation_token_pattern(token) for token in _RECOMMENDATION_LEVELS) + ")"


_RECOMMENDATION_CAPTURE = _build_recommendation_capture_group()


def _normalize_recommendation_label(text: str) -> str:
    collapsed = re.sub(r"\s+", "", text or "")
    for token in _RECOMMENDATION_LEVELS:
        if collapsed == token:
            return token
    return ""


def _map_recommendation_from_score(score_total: float) -> str:
    if score_total >= 8:
        return "强烈推荐"
    if score_total >= 6:
        return "推荐买入"
    if score_total >= 4:
        return "观望等待"
    if score_total >= 2:
        return "谨慎操作"
    if score_total > 0 or score_total == 0:
        return "建议回避"
    return ""


def _extract_recommendation(content: str, score_total: float) -> str:
    explicit_label_patterns = [
        r"(?:投资建议|当前结论|综合评级|评级结论|投资结论|当前评级)\s*[：:]\s*\*{0,2}\s*" + _RECOMMENDATION_CAPTURE,
        r"(?:投资建议|当前结论|综合评级|评级结论|投资结论|当前评级)[^\n]{0,24}?" + _RECOMMENDATION_CAPTURE,
    ]
    for pattern in explicit_label_patterns:
        match = re.search(pattern, content)
        if match:
            recommendation = _normalize_recommendation_label(match.group(1))
            if recommendation:
                return recommendation

    current_marker_patterns = [
        r"[✅☑✔]\s*\*{0,2}[^\n|]{0,24}?[—\-:：]\s*\*{0,2}" + _RECOMMENDATION_CAPTURE,
        r"[✅☑✔][^\n]*?" + _RECOMMENDATION_CAPTURE,
    ]
    for pattern in current_marker_patterns:
        match = re.search(pattern, content)
        if match:
            recommendation = _normalize_recommendation_label(match.group(1))
            if recommendation:
                return recommendation

    table_field_patterns = [
        r"\|\s*\*{0,2}(?:投资建议|当前结论|综合评级|评级结论|投资结论|当前评级)\*{0,2}\s*\|\s*\*{0,2}" + _RECOMMENDATION_CAPTURE + r"\*{0,2}\s*\|",
    ]
    for pattern in table_field_patterns:
        match = re.search(pattern, content)
        if match:
            recommendation = _normalize_recommendation_label(match.group(1))
            if recommendation:
                return recommendation

    if content:
        for line in content.splitlines():
            if not line.strip():
                continue
            recommendation = _normalize_recommendation_label(line)
            if recommendation:
                return recommendation

    return _map_recommendation_from_score(score_total)


def _clean_reason_text(text: str) -> str:
    text = re.sub(r"\n+", " ", text or "")
    text = re.sub(r"\*+", "", text)
    return text.strip()[:200]


def _strip_reason_line_formatting(text: str) -> str:
    text = re.sub(r"\*+", "", text or "")
    text = re.sub(r"^[\-\u2022\s]+", "", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF]", "", text)
    return text.strip()


def _is_recommendation_only_line(text: str) -> bool:
    normalized = _strip_reason_line_formatting(text)
    return normalized in _RECOMMENDATION_LEVELS


def _find_investment_conclusion_section(content: str) -> str:
    heading_pattern = re.compile(
        r"(?m)^#{3,4}\s*"
        r"(?:\d+(?:\.\d+)?\s*)?"
        r"(?:[\U0001F300-\U0001FAFF]\s*)?"
        r"投资结论"
        r"(?:\s*[：:].*)?\s*$"
    )
    match = heading_pattern.search(content)
    if not match:
        return ""

    tail = content[match.end():]
    stop_match = re.search(r"(?m)^##+\s|^---\s*$", tail)
    if stop_match:
        return tail[:stop_match.start()]
    return tail


def _extract_reason(content: str) -> str:
    section = _find_investment_conclusion_section(content)
    if not section:
        return ""

    lines = [line.rstrip() for line in section.splitlines()]
    collected: list[str] = []
    started = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if started and collected:
                break
            continue
        if not started and _is_recommendation_only_line(line):
            continue
        started = True
        collected.append(line)

    text = _clean_reason_text("\n".join(collected))
    return text if len(text) > 10 else ""


def _extract_price(content: str, labels: tuple) -> Optional[float]:
    """Find the first numeric value following any of the given labels.

    Handles all of the following layouts encountered in real reports:
      - "**建仓价位**: 12.5 元"        (colon style, optional bold)
      - "建仓价位：12.5"
      - "| **建仓价位** | 10.30 - 10.45 元 |"  (markdown table, range)
      - "| 🟢 **建仓价（首仓）** | **25.20–25.50 元** |"  (alias + suffix + bold cell)
      - "**止损价位**：**13.20**（…）"   (bold value, parens trailing)
      - "🎯 目标价（短期） | 15.50 - 16.00 元"  (alias, range with em-dash)

    For range expressions ("X - Y", "X~Y", "X–Y"), the lower bound is
    returned, matching the report convention of stating the entry/target/
    stop level as a band starting at the actionable price.
    """
    for label in labels:
        # Match the label, optional parenthesised qualifier (Chinese or ASCII
        # parens), optional bold/whitespace, then a separator that is either
        # ":/：" (colon style) or "|" (table cell), then the first number.
        pattern = (
            r"(?:(?<=^)|(?<=[\n\r|>*\-]))\s*"
            + r"(?:[\U0001F300-\U0001FAFF]\s*)?"
            + r"\*{0,2}\s*"
            + r"(?<![\u4e00-\u9fffA-Za-z0-9])"
            + re.escape(label)
            + r"\s*\*{0,2}"
            + r"(?:\s*[（(][^）)]*[）)])?"
            + r"\s*\*{0,2}\s*"
            + r"(?:[：:]|\|)\s*"
            + r"\*{0,2}\s*"
            + _NUM
        )
        match = re.search(pattern, content)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def parse_report_markdown(content: str) -> ReportSummary:
    """Parse a stock analysis markdown report into a structured summary.

    Regex patterns are designed to be resilient to minor format variations
    (extra spaces, missing bold markers, emoji prefixes, etc.).
    """
    summary = ReportSummary()

    # ── Individual dimension scores ──────────────────────────────────
    # Matches all real-world variants:
    #   "### 📊 基本面评分: 7.5/10"
    #   "基本面评分：7.5/10"
    #   "**基本面评分**: 7.5/10"
    #   "### 基本面评分：**6 / 10**"  (bold value + spaces around slash)
    # The score value may be wrapped in bold markers and the slash may be
    # padded with spaces ("6 / 10").
    def _score_after_label(label_regex: str):
        pattern = (
            label_regex
            + r"\s*[：:]\s*\*{0,2}\s*([\d.]+)\s*/\s*10"
        )
        m = re.search(pattern, content)
        return float(m.group(1)) if m else None

    def _score_from_table_row(label: str):
        pattern = (
            r"\|\s*\*{0,2}"
            + r"(?:[\U0001F300-\U0001FAFF]\s*)?"
            + re.escape(label)
            + r"\*{0,2}\s*\|[^\n]*?\*{0,2}\s*([\d.]+)\s*\*{0,2}\s*/\s*10"
        )
        m = re.search(pattern, content)
        return float(m.group(1)) if m else None

    fund = _score_after_label(r"基本面评分")
    if fund is None:
        fund = _score_from_table_row("基本面")
    if fund is not None:
        summary.score_fundamental = fund

    news = _score_after_label(r"新闻面评分")
    if news is None:
        news = _score_from_table_row("新闻面")
    if news is not None:
        summary.score_news = news

    capital = _score_after_label(r"资金面评分")
    if capital is None:
        capital = _score_from_table_row("资金面")
    if capital is not None:
        summary.score_capital = capital

    # Technical score: matches "技术面参考评分", "技术面评分", "技术面[参考]评分"
    tech = _score_after_label(r"技术面(?:参考)?评分")
    if tech is None:
        tech = _score_from_table_row("技术面")
    if tech is not None:
        summary.score_technical = tech

    # ── Total score ──────────────────────────────────────────────────
    # Strategy: try multiple patterns in order of specificity.
    # The summary row is labelled "总分" or "综合" depending on the template,
    # and the "X/10" value can sit in any later cell of the table row, may be
    # bold, and may have spaces around the slash:
    #   "| **总分** | **5.60/10** | 100% | - |"
    #   "| **综合** | - | 100% | **5.53 / 10** |"
    # Pattern 1: Table row labelled 总分/综合, value in any subsequent cell.
    total_match = re.search(
        r"\|\s*\*{0,2}(?:总分|综合|加权综合)\*{0,2}\s*\|[^\n]*?\*{0,2}([\d.]+)\s*/\s*10",
        content,
    )
    # Pattern 2: "**总分**: X/10" or "总分：X/10" (also 综合评分)
    if not total_match:
        total_match = re.search(r"(?:总分|综合(?:评分)?|加权综合)\s*[：:]\s*\*{0,2}\s*([\d.]+)\s*/\s*10", content)
    # Pattern 2b: "综合加权得分：X / 10"
    if not total_match:
        total_match = re.search(r"综合加权得分\s*[：:]\s*\*{0,2}\s*([\d.]+)\s*/\s*10", content)
    # Pattern 3: Loose "总分/综合" followed by "X/10" within a short window
    if not total_match:
        total_match = re.search(r"(?:总分|综合|加权综合).{0,12}?([\d.]+)\s*/\s*10", content)

    if total_match:
        summary.score_total = float(total_match.group(1))
    else:
        # Fallback: compute weighted average matching report_template.md weights
        # 基本面 35% + 新闻面 20% + 资金面 35% + 技术面 10%
        summary.score_total = round(
            summary.score_fundamental * 0.35 +
            summary.score_news * 0.20 +
            summary.score_capital * 0.35 +
            summary.score_technical * 0.10, 1)

    # ── Recommendation level ─────────────────────────────────────────
    summary.recommendation = _extract_recommendation(content, summary.score_total)

    # ── Action suggestion ────────────────────────────────────────────
    action_patterns = [
        r"(?:^|\n)\s*(?:操作建议|操作|建议)\s*[：:]\s*(买入|卖出|持有|加仓|减仓|观望等待|观望)",
    ]
    for pattern in action_patterns:
        m = re.search(pattern, content)
        if m:
            summary.action = m.group(1)
            break

    if not summary.action and summary.recommendation:
        recommendation_to_action = {
            "强烈推荐": "买入",
            "推荐买入": "买入",
            "观望等待": "观望",
            "谨慎操作": "减仓",
            "建议回避": "卖出",
        }
        summary.action = recommendation_to_action.get(summary.recommendation, summary.action)

    # ── Investment conclusion / reason ───────────────────────────────
    summary.reason = _extract_reason(content)

    # ── Price targets ────────────────────────────────────────────────
    # Reports use heterogeneous formats: colon style, markdown tables,
    # bold value cells, range expressions (X-Y / X~Y / X–Y), parenthesised
    # suffixes ("建仓价（轻仓）"), alias names ("建仓价" vs "建仓价位",
    # "目标价" vs "第一目标位"). The helper below extracts the first numeric
    # value following the label across these variants.
    summary.entry_price = _extract_price(
        content,
        labels=(
            "建仓区间",
            "建仓价位",
            "建仓价",
            "试探建仓区间",
            "买入价位",
            "激进建仓",
            "稳健建仓",
            "试探仓位",
        ),
    )
    summary.target_price = _extract_price(
        content,
        labels=(
            "第一目标",
            "第一目标位",
            "短期目标位",
            "保守目标价",
            "合理目标区间",
            "短期目标",
            "目标价位",
            "目标价",
            "目标价1",
            "目标位",
        ),
    )
    summary.stop_loss_price = _extract_price(
        content,
        labels=(
            "止损位",
            "止损价位",
            "止损价",
            "激进止损",
            "稳健止损",
        ),
    )

    # ── Current price ────────────────────────────────────────────────
    # Reports use a few stable formats:
    #   "| 当前股价 | **96.55 元** |"
    #   "| 当前股价 | **¥14.27** |"
    #   "| 当前股价 | 38.71 元 |"
    #   "| 当前价 | 96.55 | — |"
    # Look for "当前股价" first (header-row style), then "当前价" (compact table).
    current_patterns = [
        r"\|\s*(?:[\U0001F300-\U0001FAFF]\s*)?\*{0,2}(?:当前股价|当前价格|今日价格|最新价格|当前价|当前场内价格)\*{0,2}\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前股价\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前股价\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"最新价格\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"最新价格\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前价格\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前价格\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"今日价格\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"今日价格\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前价\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前价\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前场内价格\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前场内价格\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
    ]
    for pattern in current_patterns:
        current_match = re.search(pattern, content)
        if current_match:
            summary.current_price = float(current_match.group(1))
            break

    return summary
