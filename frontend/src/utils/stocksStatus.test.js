import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getStocksStatusKind,
  hasShanghaiDayChanged,
  resolveTodayReportRecord,
} from './stocksStatus.js'

test('falls back to done when a non-running stale state still has a today html report', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'queued',
      todayReport: { report_file_path: 'reports/002594/2026-06-04.html', html_status: 'ready' },
    }),
    'done',
  )
})

test('returns running before done', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'running',
      todayReport: { markdown_file_path: 'reports/002594_xxx_分析报告_20260604.md' },
    }),
    'running',
  )
})

test('returns done when analysis finishes explicitly', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'done',
      todayReport: null,
    }),
    'done',
  )
})

test('returns done when markdown-only today report exists', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'idle',
      todayReport: { markdown_file_path: 'reports/002594_xxx_分析报告_20260604.md' },
    }),
    'done',
  )
})

test('returns done when html today report exists', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'idle',
      todayReport: { report_file_path: 'reports/002594/2026-06-04.html', html_status: 'ready' },
    }),
    'done',
  )
})

test('returns error when no today report exists and analysis value is an error', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'error: timeout',
      todayReport: null,
    }),
    'error',
  )
})

test('returns idle when no active or completed state exists', () => {
  assert.equal(
    getStocksStatusKind({
      analysisValue: 'idle',
      todayReport: null,
    }),
    'idle',
  )
})

test('selects a today html report record when one exists', () => {
  const record = resolveTodayReportRecord(
    [
      { date: '2026-06-03', report_file_path: 'reports/002594/2026-06-03.html', html_status: 'ready' },
      { date: '2026-06-04', report_file_path: 'reports/002594/2026-06-04.html', html_status: 'ready' },
    ],
    '2026-06-04',
  )
  assert.deepEqual(record, {
    date: '2026-06-04',
    report_file_path: 'reports/002594/2026-06-04.html',
    html_status: 'ready',
  })
})

test('falls back to a markdown-only today record when html is missing', () => {
  const record = resolveTodayReportRecord(
    [
      { date: '2026-06-04', markdown_file_path: 'reports/002594_xxx_分析报告_20260604.md' },
    ],
    '2026-06-04',
  )
  assert.deepEqual(record, {
    date: '2026-06-04',
    markdown_file_path: 'reports/002594_xxx_分析报告_20260604.md',
  })
})

test('returns null when there is no today record', () => {
  assert.equal(resolveTodayReportRecord([], '2026-06-04'), null)
})

test('detects when cached today date no longer matches Shanghai today', () => {
  const now = new Date('2026-06-05T00:10:00+08:00')
  assert.equal(hasShanghaiDayChanged('2026-06-04', now), true)
})

test('does not flag a change when cached today date still matches Shanghai today', () => {
  const now = new Date('2026-06-04T23:50:00+08:00')
  assert.equal(hasShanghaiDayChanged('2026-06-04', now), false)
})
