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
    # Matches bold text like "**推荐买入**" or plain "推荐买入"
    rec_match = re.search(
        r"\*{0,2}(强烈推荐|推荐买入|观望等待|谨慎操作|建议回避)\*{0,2}", content
    )
    if rec_match:
        summary.recommendation = rec_match.group(1)

    # ── Action suggestion ────────────────────────────────────────────
    action_patterns = [
        (r"建议\s*[：:]\s*(买入|卖出|持有|加仓|减仓|观望)", None),
        (r"(强烈推荐|推荐买入)", "买入"),
        (r"(观望等待)", "观望"),
        (r"(谨慎操作)", "减仓"),
        (r"(建议回避)", "卖出"),
    ]
    for pattern, override in action_patterns:
        m = re.search(pattern, content)
        if m:
            summary.action = override or m.group(1)
            break

    # ── Investment conclusion / reason ───────────────────────────────
    # The template format is:
    #   ### 🎯 投资结论
    #   **{投资建议等级}**
    #
    #   {投资结论详细说明}
    #
    #   ### 💡 操作建议
    #
    # We capture everything between the recommendation line and the next section.
    # Terminator: "---", "### ", or 2+ blank lines (whitespace-only lines included)
    reason_patterns = [
        # Pattern 1: After "投资结论" section, capture text until next heading/separator
        r"投资结论\s*\n+[*\s]*\n+(.+?)(?:\n\s*\n|\n\s*\n\s*\n|\n###|\n---|\Z)",
        # Pattern 2: More flexible — after the bold recommendation line
        r"\*{0,2}(?:强烈推荐|推荐买入|观望等待|谨慎操作|建议回避)\*{0,2}\s*\n+(.+?)(?:\n\s*\n|\n###|\n---|\Z)",
        # Pattern 3: Very loose — "投资结论" block up to "操作建议" or next heading
        r"投资结论.*?\n+(.+?)(?=###\s*[💡⚡]|###\s*操作|###\s*风险|\n---|\Z)",
    ]
    for pat in reason_patterns:
        reason_match = re.search(pat, content, re.DOTALL)
        if reason_match:
            text = reason_match.group(1).strip()
            # Clean up: remove markdown formatting, trailing whitespace
            text = re.sub(r'\n+', ' ', text)
            text = re.sub(r'\*+', '', text)
            text = text.strip()[:200]
            if len(text) > 10:  # Only accept if meaningful content
                summary.reason = text
                break

    if not summary.reason:
        current_reason_patterns = [
            r"当前结论\s*[：:]\s*([^。\n]+[。\n]?)\s*\n+\s*(.+?)(?=\n###|\n##|\n---|\Z)",
            r"综合判断\s*\n+\*{0,2}当前结论\s*[：:][^\n]*\*{0,2}\s*\n+(.+?)(?=\n###|\n##|\n---|\Z)",
        ]
        for pat in current_reason_patterns:
            reason_match = re.search(pat, content, re.DOTALL)
            if reason_match:
                text = " ".join(group.strip() for group in reason_match.groups() if group and group.strip())
                text = re.sub(r"\n+", " ", text)
                text = re.sub(r"\*+", "", text)
                text = text.strip()[:200]
                if len(text) > 10:
                    summary.reason = text
                    break

    if not summary.reason:
        suggestion_reason_match = re.search(
            r"综合投资建议\s*\n+\s*###\s*[^\n]*\n+\s*(.+?)(?=\n\s*\| 价位类型 |\n###|\n##|\n---|\Z)",
            content,
            re.DOTALL,
        )
        if suggestion_reason_match:
            text = suggestion_reason_match.group(1).strip()
            text = re.sub(r"\n+", " ", text)
            text = re.sub(r"\*+", "", text)
            text = text.strip()[:200]
            if len(text) > 10:
                summary.reason = text

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
            "短期目标",
            "目标价位",
            "目标价",
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
        r"当前股价\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前价\s*\|\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前股价\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
        r"当前价\s*[：:]\s*\*{0,2}\s*[¥￥]?\s*([\d.]+)",
    ]
    for pattern in current_patterns:
        current_match = re.search(pattern, content)
        if current_match:
            summary.current_price = float(current_match.group(1))
            break

    return summary
