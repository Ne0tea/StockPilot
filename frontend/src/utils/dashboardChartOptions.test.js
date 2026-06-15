import test from 'node:test'
import assert from 'node:assert/strict'

import { buildProfitChartOption } from './dashboardChartOptions.js'

const profitHistory = [
  { date: '2026-06-09', cumulative_profit: -4122, cumulative_pct: -6.9 },
  { date: '2026-06-11', cumulative_profit: -4398, cumulative_pct: -6.13 },
]

test('renders profit history as a simple line without area fill', () => {
  const option = buildProfitChartOption(profitHistory, { mode: 'percent' })

  assert.equal(option.series.length, 1)
  assert.equal(option.series[0].type, 'line')
  assert.equal(option.series[0].areaStyle, undefined)
})
