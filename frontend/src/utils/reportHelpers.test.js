import test from 'node:test'
import assert from 'node:assert/strict'

import { getBulkAnalyzableStocks } from './reportHelpers.js'

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
