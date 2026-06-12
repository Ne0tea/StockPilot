import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildBulkAnalyzeConfirmationText,
  getReportFreshness,
  buildTodayHtmlReportPreviewUrl,
  formatCompactScore,
  getBulkAnalyzableStocks,
  hasReadyTodayHtmlReport,
} from './reportHelpers.js'

test('bulk analyzable stocks only skip running analyses and existing today reports', () => {
  const stocks = [
    { stock_code: '600021' },
    { stock_code: '159792' },
    { stock_code: '000001' },
  ]

  const todayReportMap = {
    '000001': { report_file_path: 'reports/000001/2026-06-09.html', html_status: 'ready' },
  }

  const analysisState = {
    '600021': 'queued',
    '159792': 'running',
  }

  assert.deepEqual(
    getBulkAnalyzableStocks(stocks, todayReportMap, analysisState),
    [{ stock_code: '600021' }],
  )
})

test('builds the bulk analyze confirmation text', () => {
  assert.equal(
    buildBulkAnalyzeConfirmationText(),
    '同时启动多项分析容易触发Api限制导致分析失败，确认启动？',
  )
})

test('ready today html report can be previewed', () => {
  const report = {
    date: '2026-06-09',
    report_file_path: 'reports/000001/2026-06-09.html',
    html_status: 'ready',
  }

  assert.equal(hasReadyTodayHtmlReport(report, '2026-06-09'), true)
  assert.equal(
    buildTodayHtmlReportPreviewUrl(report, '2026-06-09'),
    '/reports/000001/2026-06-09.html',
  )
})

test('markdown-only or stale report cannot be previewed as today html report', () => {
  assert.equal(
    hasReadyTodayHtmlReport(
      {
        date: '2026-06-09',
        markdown_file_path: 'reports/000001_xxx_分析报告_20260609.md',
      },
      '2026-06-09',
    ),
    false,
  )

  assert.equal(
    buildTodayHtmlReportPreviewUrl(
      {
        date: '2026-06-08',
        report_file_path: 'reports/000001/2026-06-08.html',
        html_status: 'ready',
      },
      '2026-06-09',
    ),
    '',
  )
})

test('formats compact score values for dashboard columns', () => {
  assert.equal(formatCompactScore(6), '6')
  assert.equal(formatCompactScore(6.5), '6.5')
  assert.equal(formatCompactScore('7.0'), '7')
  assert.equal(formatCompactScore(null), '—')
})

test('classifies daily report freshness by report date', () => {
  assert.deepEqual(getReportFreshness('2026-06-12', '2026-06-12'), {
    key: 'today',
    label: '今日',
    title: '报告日期：2026-06-12',
  })

  assert.deepEqual(getReportFreshness('2026-06-11', '2026-06-12'), {
    key: 'yesterday',
    label: '昨日',
    title: '报告日期：2026-06-11',
  })

  assert.deepEqual(getReportFreshness('2026-06-10', '2026-06-12'), {
    key: 'before-yesterday',
    label: '前日',
    title: '报告日期：2026-06-10',
  })

  assert.deepEqual(getReportFreshness('2026-06-09', '2026-06-12'), {
    key: 'stale',
    label: '>3天',
    title: '报告日期：2026-06-09，建议重新生成日报',
  })
})

test('treats invalid or missing report dates as unknown freshness', () => {
  assert.deepEqual(getReportFreshness('', '2026-06-12'), {
    key: 'unknown',
    label: '无报告',
    title: '暂无日报',
  })

  assert.deepEqual(getReportFreshness('not-a-date', '2026-06-12'), {
    key: 'unknown',
    label: '无报告',
    title: '暂无日报',
  })
})
