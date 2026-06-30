from core.parser import parse_report_markdown


def test_reason_uses_body_below_investment_conclusion_heading():
    markdown = """
### 🎯 投资结论

**推荐买入**

基本面强劲，短期回调后具备布局价值。
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == "基本面强劲，短期回调后具备布局价值。"


def test_reason_uses_body_after_inline_investment_conclusion_heading():
    markdown = """
### 投资结论：观望等待

基本面强劲（业绩翻倍增长+机构一致看好），但短期资金面偏弱，建议等待回调至MA20附近布局。
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == "基本面强劲（业绩翻倍增长+机构一致看好），但短期资金面偏弱，建议等待回调至MA20附近布局。"


def test_reason_ignores_heading_numbering_and_bold_rating_line():
    markdown = """
### 7.2 🎯 投资结论

**观望等待**

等待趋势确认后再分批布局，避免在弱势震荡中提前重仓。

### 7.3 买卖价位
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == "等待趋势确认后再分批布局，避免在弱势震荡中提前重仓。"


def test_reason_is_blank_when_investment_conclusion_has_no_body():
    markdown = """
### 🎯 投资结论

**推荐买入**
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == ""


def test_reason_does_not_fallback_to_other_sections_when_investment_conclusion_body_missing():
    markdown = """
### 当前结论：推荐买入

这里是旧模板说明，不应再写入 reason。

### 综合投资建议

这里也是旧模板内容，不应再写入 reason。
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == ""


def test_reason_prefers_explicit_conclusion_line_in_investment_conclusion_section():
    markdown = """
### 🎯 投资结论

**🟡 观望等待**

洛阳钼业基本面极为优秀——ROE 26.61%、净利润近乎翻倍增长、铜金双极战略清晰，是A股有色板块的优质标的。但当前面临三大短期压力：

1. **异动已触发**：6月16日发布异动公告后，短期股价承压，存在回调需求
2. **资金面疲弱**：主力净比接近零，散户资金主导接盘，主力态度谨慎
3. **短期涨幅已大**：20日涨幅+15.30%，从低点16.79反弹至20.04已超19%

**结论**：中长期价值突出，但短期不宜追涨，等待回调至支撑位再分批建仓。
中，中长期价值突出，但短期不宜追涨，等待回调至支撑位再分批建仓。部分内容。
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == "中长期价值突出，但短期不宜追涨，等待回调至支撑位再分批建仓。"


def test_reason_is_blank_when_section_only_contains_rating_with_score_and_next_heading():
    markdown = """
### 🎯 投资结论

**谨慎操作**（评分 3.5/10）

### 操作建议
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == ""


def test_reason_is_blank_when_section_only_contains_rating_with_short_parenthetical_suffix():
    markdown = """
### 🎯 投资结论

⚠️ 谨慎操作（短期）

### 操作建议
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == ""


def test_reason_is_blank_when_section_only_contains_rating_with_dash_score_suffix():
    markdown = """
### 🎯 投资结论

⚠️ 谨慎操作 - 评分 3.5/10

### 操作建议
"""
    summary = parse_report_markdown(markdown)
    assert summary.reason == ""
