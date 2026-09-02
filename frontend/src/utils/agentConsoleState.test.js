import test from 'node:test'
import assert from 'node:assert/strict'

import {
  AGENT_CONSOLE_DIAGNOSTIC_LIMIT,
  AGENT_CONSOLE_EVENT_LIMIT,
  AGENT_CONSOLE_TOOL_CALL_LIMIT,
  applyAgentConsoleEvent,
  createAgentConsoleState,
  isAgentConsoleTerminalState,
} from './agentConsoleState.js'

test('creates the default console state', () => {
  assert.deepEqual(createAgentConsoleState(), {
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
  })
})

test('expands details while the console is running', () => {
  const state = applyAgentConsoleEvent(createAgentConsoleState(), {
    type: 'status',
    status: 'running',
    message: '正在分析',
  })

  assert.equal(state.status, 'running')
  assert.equal(state.statusLabel, '正在分析')
  assert.equal(state.detailsExpanded, true)
  assert.equal(isAgentConsoleTerminalState(state), false)
})

test('records prompt stage tool and diagnostic events in a pure append-only way', () => {
  const initialState = createAgentConsoleState()
  const withPrompt = applyAgentConsoleEvent(initialState, {
    type: 'prompt',
    text: '请分析这只股票的风险收益比',
  })
  const withStage = applyAgentConsoleEvent(withPrompt, {
    type: 'stage',
    stage: 'collecting_news',
    title: '收集新闻',
  })
  const withTool = applyAgentConsoleEvent(withStage, {
    type: 'tool',
    toolName: 'news_search',
    status: 'running',
    input: { keyword: '示例' },
  })
  const finalState = applyAgentConsoleEvent(withTool, {
    type: 'diagnostic',
    level: 'warning',
    message: '新闻源部分超时，已使用降级结果',
  })

  assert.equal(initialState.events.length, 0)
  assert.equal(withPrompt.prompt, '请分析这只股票的风险收益比')
  assert.equal(withStage.stage, '收集新闻')
  assert.deepEqual(withTool.toolCalls, [
    {
      type: 'tool',
      toolName: 'news_search',
      status: 'running',
      input: { keyword: '示例' },
    },
  ])
  assert.deepEqual(finalState.diagnostics, [
    {
      type: 'diagnostic',
      level: 'warning',
      message: '新闻源部分超时，已使用降级结果',
    },
  ])
  assert.equal(finalState.events.length, 4)
  assert.equal(finalState.detailsExpanded, true)
})

test('collapses details after a successful final result and session end', () => {
  const state = [
    { type: 'status', status: 'running', message: '正在生成报告' },
    { type: 'final_result', content: '建议继续观察，等待回踩确认。' },
    { type: 'session_end', reason: 'completed' },
  ].reduce(applyAgentConsoleEvent, createAgentConsoleState())

  assert.equal(state.status, 'success')
  assert.equal(state.finalResult, '建议继续观察，等待回踩确认。')
  assert.equal(state.sessionEndReason, 'completed')
  assert.equal(state.terminalKind, 'success')
  assert.equal(state.detailsExpanded, false)
  assert.equal(isAgentConsoleTerminalState(state), true)
})

test('keeps details expanded when the session ends without a result', () => {
  const state = [
    { type: 'status', status: 'running', message: '正在生成报告' },
    { type: 'session_end', reason: 'completed' },
  ].reduce(applyAgentConsoleEvent, createAgentConsoleState())

  assert.equal(state.status, 'empty')
  assert.equal(state.finalResult, '')
  assert.equal(state.terminalKind, 'empty')
  assert.equal(state.detailsExpanded, true)
  assert.equal(isAgentConsoleTerminalState(state), true)
})

test('keeps details expanded for timeout and error terminal states', () => {
  const timeoutState = [
    { type: 'status', status: 'running', message: '正在等待工具返回' },
    { type: 'session_end', reason: 'timeout' },
  ].reduce(applyAgentConsoleEvent, createAgentConsoleState())

  const errorState = [
    { type: 'status', status: 'running', message: '正在等待工具返回' },
    { type: 'status', status: 'error', message: '分析失败' },
    { type: 'session_end', reason: 'error' },
  ].reduce(applyAgentConsoleEvent, createAgentConsoleState())

  assert.equal(timeoutState.status, 'timeout')
  assert.equal(timeoutState.detailsExpanded, true)
  assert.equal(timeoutState.terminalKind, 'timeout')

  assert.equal(errorState.status, 'error')
  assert.equal(errorState.detailsExpanded, true)
  assert.equal(errorState.terminalKind, 'error')
})

test('maps raw backend SSE payload fields into the expected terminal state', () => {
  const state = [
    { type: 'prompt', text: '【持仓背景】请分析 600519' },
    { type: 'status', text: '正在启动 specialist 流程' },
    { type: 'stage', stage: 'specialist', status: 'started', text: '阶段开始' },
    { type: 'tool', tool: 'search_news', status: 'completed', duration: 1.2 },
    { type: 'final_result', text: '建议继续持有，等待回踩确认。' },
    { type: 'session_end', status: 'done', text: '建议继续持有，等待回踩确认。' },
  ].reduce(applyAgentConsoleEvent, createAgentConsoleState())

  assert.equal(state.prompt, '【持仓背景】请分析 600519')
  assert.equal(state.status, 'success')
  assert.equal(state.statusLabel, '分析完成')
  assert.equal(state.stage, '阶段开始')
  assert.equal(state.toolCalls.length, 1)
  assert.equal(state.finalResult, '建议继续持有，等待回踩确认。')
  assert.equal(state.sessionEndReason, 'completed')
  assert.equal(state.detailsExpanded, false)
  assert.equal(isAgentConsoleTerminalState(state), true)
})

test('keeps cancelled runs expanded and terminal', () => {
  const state = [
    { type: 'status', text: '正在分析' },
    { type: 'diagnostic', code: 'cancelled', text: '用户已取消本次专项分析' },
    { type: 'session_end', status: 'cancelled', text: '分析已取消' },
  ].reduce(applyAgentConsoleEvent, createAgentConsoleState())

  assert.equal(state.status, 'cancelled')
  assert.equal(state.statusLabel, '分析已取消')
  assert.equal(state.terminalKind, 'cancelled')
  assert.equal(state.detailsExpanded, true)
})

test('ignores unknown events except for recording them in the timeline', () => {
  const state = applyAgentConsoleEvent(createAgentConsoleState(), {
    type: 'unknown_event',
    payload: 123,
  })

  assert.equal(state.status, 'idle')
  assert.equal(state.detailsExpanded, false)
  assert.deepEqual(state.events, [
    {
      type: 'unknown_event',
      payload: 123,
    },
  ])
})

test('bounds timeline, tool call, and diagnostic collections', () => {
  let eventState = createAgentConsoleState()

  for (let index = 0; index < AGENT_CONSOLE_EVENT_LIMIT + 10; index += 1) {
    eventState = applyAgentConsoleEvent(eventState, { type: 'status', text: `status-${index}` })
  }

  let toolState = createAgentConsoleState()
  for (let index = 0; index < AGENT_CONSOLE_TOOL_CALL_LIMIT + 10; index += 1) {
    toolState = applyAgentConsoleEvent(toolState, { type: 'tool', tool: `tool-${index}` })
  }

  let diagnosticState = createAgentConsoleState()
  for (let index = 0; index < AGENT_CONSOLE_DIAGNOSTIC_LIMIT + 10; index += 1) {
    diagnosticState = applyAgentConsoleEvent(diagnosticState, { type: 'diagnostic', text: `diagnostic-${index}` })
  }

  assert.equal(eventState.events.length, AGENT_CONSOLE_EVENT_LIMIT)
  assert.equal(toolState.toolCalls.length, AGENT_CONSOLE_TOOL_CALL_LIMIT)
  assert.equal(diagnosticState.diagnostics.length, AGENT_CONSOLE_DIAGNOSTIC_LIMIT)
  assert.equal(eventState.events[0].text, 'status-10')
  assert.equal(toolState.toolCalls[0].tool, 'tool-10')
  assert.equal(diagnosticState.diagnostics[0].text, 'diagnostic-10')
})
