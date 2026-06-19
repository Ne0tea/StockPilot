import { reactive, ref } from 'vue'

export const CACHE_TTL_MS = 60 * 1000

export const stocksList = ref([])
export const historyMap = reactive({})
export const analysisState = reactive({})
export const todayReportMap = reactive({})
export const reportReferenceDateMap = reactive({})
export const todayLogMap = reactive({})
export const lastSyncedAt = ref(0)
export const overviewCachedAt = ref(0)
export const todayDate = ref('')

export function setStocksList(list) {
  stocksList.value = Array.isArray(list) ? list : []
}

export function setHistoryFor(code, items) {
  if (!code) return
  if (!items) {
    delete historyMap[code]
    return
  }
  historyMap[code] = items
}

export function pruneHistoryMap(validCodes) {
  const allow = new Set(validCodes || [])
  for (const code of Object.keys(historyMap)) {
    if (!allow.has(code)) delete historyMap[code]
  }
}

export function setAnalysisStatus(code, status) {
  if (!code) return
  if (status == null) {
    delete analysisState[code]
    return
  }
  analysisState[code] = status
}

export function clearAnalysisStatus(code) {
  if (!code) return
  delete analysisState[code]
}

export function setTodayReport(code, report) {
  if (!code) return
  if (!report) {
    delete todayReportMap[code]
    return
  }
  todayReportMap[code] = report
}

export function setReportReferenceDate(code, value) {
  if (!code) return
  if (!value) {
    delete reportReferenceDateMap[code]
    return
  }
  reportReferenceDateMap[code] = value
}

export function setTodayLog(code, info) {
  if (!code) return
  if (!info) {
    delete todayLogMap[code]
    return
  }
  todayLogMap[code] = info
}

export function pruneAnalysisStore(validCodes) {
  const allow = new Set(validCodes || [])
  for (const code of Object.keys(analysisState)) {
    if (!allow.has(code)) delete analysisState[code]
  }
  for (const code of Object.keys(todayReportMap)) {
    if (!allow.has(code)) delete todayReportMap[code]
  }
  for (const code of Object.keys(reportReferenceDateMap)) {
    if (!allow.has(code)) delete reportReferenceDateMap[code]
  }
  for (const code of Object.keys(todayLogMap)) {
    if (!allow.has(code)) delete todayLogMap[code]
  }
}

export function resetAnalysisStore() {
  for (const code of Object.keys(analysisState)) delete analysisState[code]
  for (const code of Object.keys(todayReportMap)) delete todayReportMap[code]
  for (const code of Object.keys(reportReferenceDateMap)) delete reportReferenceDateMap[code]
  for (const code of Object.keys(todayLogMap)) delete todayLogMap[code]
  for (const code of Object.keys(historyMap)) delete historyMap[code]
  stocksList.value = []
  lastSyncedAt.value = 0
  overviewCachedAt.value = 0
  todayDate.value = ''
}

export function isOverviewCacheFresh(now = Date.now()) {
  return overviewCachedAt.value > 0 && now - overviewCachedAt.value < CACHE_TTL_MS
}

export function applyOverviewSnapshot(payload) {
  if (!payload || typeof payload !== 'object') return

  const stocks = Array.isArray(payload.stocks) ? payload.stocks : []
  const validCodes = stocks.map((s) => s.stock_code)

  setStocksList(stocks)

  // Update history map
  for (const code of Object.keys(historyMap)) delete historyMap[code]
  const incomingHistory = payload.history_map || {}
  for (const code of Object.keys(incomingHistory)) {
    historyMap[code] = incomingHistory[code] || []
  }

  // Update today report map
  for (const code of Object.keys(todayReportMap)) delete todayReportMap[code]
  const incomingToday = payload.today_report_map || {}
  for (const code of Object.keys(incomingToday)) {
    todayReportMap[code] = incomingToday[code]
  }

  // Update report reference date map
  for (const code of Object.keys(reportReferenceDateMap)) delete reportReferenceDateMap[code]
  const incomingReferenceDates = payload.report_reference_date_map || {}
  for (const code of Object.keys(incomingReferenceDates)) {
    if (validCodes.includes(code) && incomingReferenceDates[code]) {
      reportReferenceDateMap[code] = incomingReferenceDates[code]
    }
  }

  // Update analysis state
  for (const code of Object.keys(analysisState)) delete analysisState[code]
  const incomingState = payload.analysis_state || {}
  for (const code of Object.keys(incomingState)) {
    if (validCodes.includes(code)) {
      analysisState[code] = incomingState[code]
    }
  }

  // Clear today log - will be populated after overview returns
  for (const code of Object.keys(todayLogMap)) delete todayLogMap[code]

  todayDate.value = payload.today_date || todayDate.value
  const now = Date.now()
  overviewCachedAt.value = now
  lastSyncedAt.value = now
}

export function invalidateOverviewCache() {
  overviewCachedAt.value = 0
}
