export const AGENT_CONSOLE_EVENT_LIMIT = 256
export const AGENT_CONSOLE_TOOL_CALL_LIMIT = 256
export const AGENT_CONSOLE_DIAGNOSTIC_LIMIT = 128

export function createAgentConsoleState() {
  return {
    status: 'idle',
    statusLabel: '',
    stage: '',
    prompt: '',
    finalResult: '',
    sessionEndReason: '',
    events: [],
    toolCalls: [],
    diagnostics: [],
    detailsExpanded: false,
    terminalKind: 'running',
  }
}

export function applyAgentConsoleEvent(state, event) {
  const nextState = {
    ...state,
    events: appendBounded(state.events, event, AGENT_CONSOLE_EVENT_LIMIT),
    toolCalls: [...state.toolCalls],
    diagnostics: [...state.diagnostics],
  }

  switch (event?.type) {
    case 'prompt':
      nextState.prompt = readText(event.text, event.prompt)
      if (!isTerminalStatus(nextState.status)) {
        nextState.status = 'running'
      }
      if (!nextState.statusLabel) {
        nextState.statusLabel = '已接收分析输入'
      }
      break
    case 'status':
      nextState.status = resolveStatus(nextState.status, event.status)
      nextState.statusLabel = readText(event.text, event.message, event.label, state.statusLabel)
      break
    case 'stage':
      nextState.stage = readText(event.text, event.title, event.stage, state.stage)
      if (!isTerminalStatus(nextState.status)) {
        nextState.status = 'running'
      }
      break
    case 'tool':
      nextState.toolCalls = appendBounded(state.toolCalls, event, AGENT_CONSOLE_TOOL_CALL_LIMIT)
      if (!isTerminalStatus(nextState.status)) {
        nextState.status = 'running'
      }
      break
    case 'diagnostic':
      nextState.diagnostics = appendBounded(state.diagnostics, event, AGENT_CONSOLE_DIAGNOSTIC_LIMIT)
      nextState.statusLabel = readText(event.text, event.message, state.statusLabel)
      break
    case 'final_result':
      nextState.finalResult = readText(event.text, event.content, event.result, event.message)
      if (nextState.finalResult) {
        nextState.status = 'success'
        nextState.statusLabel = '分析完成'
      }
      break
    case 'session_end':
      nextState.sessionEndReason = normalizeSessionEndReason(readText(event.reason, event.status))
      applySessionEnd(nextState, readText(event.text, event.message))
      break
    default:
      break
  }

  nextState.terminalKind = getTerminalKind(nextState)
  nextState.detailsExpanded = shouldKeepDetailsExpanded(nextState)
  return nextState
}

function appendBounded(items, item, limit) {
  const next = [...items, item]
  return next.length > limit ? next.slice(-limit) : next
}

export function isAgentConsoleTerminalState(state) {
  return state.terminalKind !== 'running'
}

function resolveStatus(previousStatus, status) {
  const normalized = normalizeStatus(status)
  if (normalized) return normalized
  return isTerminalStatus(previousStatus) ? previousStatus : 'running'
}

function normalizeStatus(status) {
  if (status === 'error' || status === 'failed') return 'error'
  if (status === 'timeout') return 'timeout'
  if (status === 'cancelled') return 'cancelled'
  if (status === 'success' || status === 'completed' || status === 'done') return 'success'
  if (status === 'running') return 'running'
  if (status === 'idle') return 'idle'
  return ''
}

function normalizeSessionEndReason(reason) {
  if (reason === 'done') return 'completed'
  return reason || ''
}

function applySessionEnd(state, messageText) {
  if (state.sessionEndReason === 'timeout') {
    state.status = 'timeout'
    state.statusLabel = messageText || state.statusLabel || '执行超时'
    return
  }

  if (state.sessionEndReason === 'cancelled') {
    state.status = 'cancelled'
    state.statusLabel = messageText || state.statusLabel || '分析已取消'
    return
  }

  if (state.sessionEndReason === 'error') {
    state.status = 'error'
    state.statusLabel = messageText || state.statusLabel || '执行异常'
    return
  }

  if (state.sessionEndReason === 'completed') {
    state.status = state.finalResult ? 'success' : 'empty'
    state.statusLabel = state.finalResult
      ? '分析完成'
      : messageText || '本次专项分析未生成有效结论'
  }
}

function getTerminalKind(state) {
  if (state.status === 'success') return 'success'
  if (state.status === 'error') return 'error'
  if (state.status === 'timeout') return 'timeout'
  if (state.status === 'cancelled') return 'cancelled'
  if (state.status === 'empty') return 'empty'
  return 'running'
}

function shouldKeepDetailsExpanded(state) {
  if (state.terminalKind === 'success') return false
  if (state.terminalKind === 'error') return true
  if (state.terminalKind === 'timeout') return true
  if (state.terminalKind === 'cancelled') return true
  if (state.terminalKind === 'empty') return true
  if (state.status === 'running') return true
  return state.prompt !== '' || state.stage !== '' || state.toolCalls.length > 0 || state.diagnostics.length > 0
}

function isTerminalStatus(status) {
  return ['success', 'error', 'timeout', 'cancelled', 'empty'].includes(status)
}

function readText(...values) {
  for (const value of values) {
    if (typeof value === 'string') return value
  }

  return ''
}
