export function getTodayDateString(timeZone = 'Asia/Shanghai', now = new Date()) {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return formatter.format(now)
}

function parseDateOnly(value) {
  if (typeof value !== 'string') {
    return null
  }

  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) {
    return null
  }

  const [, year, month, day] = match
  return Date.UTC(Number(year), Number(month) - 1, Number(day))
}

export function getReportFreshness(reportDate, today) {
  const reportTime = parseDateOnly(reportDate)
  const todayTime = parseDateOnly(today)

  if (reportTime === null || todayTime === null) {
    return {
      key: 'unknown',
      label: '无报告',
      title: '暂无日报',
    }
  }

  const dayDiff = Math.floor((todayTime - reportTime) / 86400000)
  const baseTitle = `数据日期：${reportDate}；基准数据日期：${today}`

  if (dayDiff <= 0) {
    return {
      key: 'today',
      label: '最新',
      title: baseTitle,
    }
  }

  if (dayDiff === 1) {
    return {
      key: 'yesterday',
      label: '早1天',
      title: baseTitle,
    }
  }

  if (dayDiff === 2) {
    return {
      key: 'before-yesterday',
      label: '早2天',
      title: baseTitle,
    }
  }

  return {
    key: 'stale',
    label: '>2天',
    title: `${baseTitle}，建议重新生成日报`,
  }
}

export function resolveDashboardReportReferenceDate(source, fallbackToday = '') {
  const candidate = source?.report_reference_date
  return parseDateOnly(candidate) === null ? fallbackToday : candidate
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

export function hasReadyTodayHtmlReport(report, today = '') {
  return Boolean(
    report
    && report.date
    && (!today || report.date === today)
    && report.html_status === 'ready'
    && report.report_file_path,
  )
}

export function buildTodayHtmlReportPreviewUrl(report, today = '') {
  if (!hasReadyTodayHtmlReport(report, today)) {
    return ''
  }
  return buildReportUrl(report.report_file_path)
}

export function buildBulkAnalyzeConfirmationText() {
  return '同时启动多项分析容易触发Api限制导致分析失败，确认启动？'
}

export function formatCompactScore(value) {
  if (value === null || value === undefined || value === '') {
    return '—'
  }

  const num = Number(value)
  if (Number.isNaN(num)) {
    return '—'
  }

  return Number.isInteger(num) ? String(num) : String(num)
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
