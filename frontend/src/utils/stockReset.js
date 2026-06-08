export function getStockResetConfirmationText() {
  return [
    '此操作将删除全部自选股票，删除全部分析报告和报告索引，删除全部持仓与交易记录，保留系统设置。',
    '确认后将立即执行初始化，且不可撤销。',
  ].join('\n')
}

export function getStockResetSuccessMessage() {
  return '初始化完成'
}

export function clearPollingTimers(timerMap, clearTimer = clearInterval) {
  for (const timerId of Object.values(timerMap || {})) {
    clearTimer(timerId)
  }
  return {}
}

export function closeAnalysisEventSource(eventSource) {
  if (eventSource?.close) {
    eventSource.close()
  }
  return null
}

export function createEmptyStockPageState() {
  return {
    stocks: [],
    form: { stock_code: '', name: '', market: 'sh' },
    historyMap: {},
    analysisState: {},
    todayReportMap: {},
    reportDialogVisible: false,
    reportUrl: '',
    dialogVisible: false,
    dialogStock: { stock_code: '', name: '' },
    streamMessages: [],
    isAnalyzing: false,
    pendingQuestion: null,
    userInput: '',
  }
}
