import { getTodayDateString } from './reportHelpers.js'

export function canDeleteAnalysisSession(statusKind) {
  return statusKind === 'running'
}

export function resolveTodayReportRecord(reports, today) {
  if (!Array.isArray(reports) || !today) {
    return null
  }

  const todayRecords = reports.filter((report) => report?.date === today)
  if (!todayRecords.length) {
    return null
  }

  return todayRecords.find((report) =>
    report?.html_status === 'ready' && Boolean(report?.report_file_path)
  ) || todayRecords.find((report) =>
    Boolean(report?.markdown_file_path || report?.report_file_path)
  ) || null
}

export function getStocksStatusKind({ analysisValue, todayReport }) {
  if (analysisValue === 'running') return 'running'
  if (analysisValue === 'done') return 'done'

  const hasTodayResult = Boolean(
    todayReport?.markdown_file_path
    || (todayReport?.html_status === 'ready' && todayReport?.report_file_path),
  )
  if (hasTodayResult) return 'done'

  if (typeof analysisValue === 'string' && analysisValue.startsWith('error')) {
    return 'error'
  }

  return 'idle'
}

export function hasShanghaiDayChanged(cachedToday, now = new Date()) {
  if (!cachedToday) {
    return false
  }
  return getTodayDateString('Asia/Shanghai', now) !== cachedToday
}
