export function filterReportsByCodeAndDateRange(reports = [], selectedCode = '', dateRange = []) {
  const [start, end] = Array.isArray(dateRange) ? dateRange : []
  return reports.filter((report) => {
    if (selectedCode && report?.stock_code !== selectedCode) {
      return false
    }
    if (!start || !end) {
      return true
    }
    const reportDate = String(report?.date || '')
    return reportDate >= start && reportDate <= end
  })
}

export function buildReportRouteQuery({ selectedCode = '', dateRange = [] } = {}) {
  const query = {}
  if (selectedCode) {
    query.code = selectedCode
  }
  if (Array.isArray(dateRange) && dateRange[0] && dateRange[1]) {
    query.start = dateRange[0]
    query.end = dateRange[1]
  }
  return query
}
