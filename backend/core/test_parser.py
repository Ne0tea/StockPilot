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
