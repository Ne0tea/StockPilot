export function getTodayDateString(timeZone = 'Asia/Shanghai', now = new Date()) {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return formatter.format(now)
}

export function resolveTodayHtmlReport(reports, today) {
  if (!Array.isArray(reports) || !today) {
    return null
  }

  return reports.find((report) =>
    report?.date === today &&
    report?.html_status === 'ready' &&
    Boolean(report?.report_file_path)
  ) || null
}

export function buildReportUrl(reportFilePath) {
  if (!reportFilePath) {
    return ''
  }

  const normalized = String(reportFilePath).replace(/\\/g, '/')
  const reportsIndex = normalized.indexOf('/reports/')
  if (reportsIndex >= 0) {
    return normalized.slice(reportsIndex)
  }
  return `/${normalized.replace(/^\/+/, '')}`
}

export function buildBulkAnalyzeConfirmationText() {
  return '同时启动多项分析容易触发Api限制导致分析失败，确认启动？'
}

export function getBulkAnalyzableStocks(stocks, todayReportMap, analysisState) {
  if (!Array.isArray(stocks)) {
    return []
  }

  return stocks.filter((stock) => {
    const code = stock?.stock_code
    if (!code) return false
    if (todayReportMap?.[code]) return false
    const state = analysisState?.[code]
    return state !== 'running'
  })
}
