import test from 'node:test'
import assert from 'node:assert/strict'

import { buildScoreChartOption } from './scoreChartOptions.js'

const scoreHistory = [
  { date: '2026-06-11', score_total: 5.8 },
  { date: '2026-06-12', score_total: 6.4 },
]

test('compact score chart keeps axes visible in row-aligned mode', () => {
  const option = buildScoreChartOption(scoreHistory, { compact: true })

  assert.equal(option.legend.show, false)
  assert.equal(option.series.length, 1)
  assert.equal(option.xAxis.axisLabel.show, true)
  assert.equal(option.yAxis.axisLabel.show, true)
  assert.equal(option.grid.containLabel, true)
  assert.ok(option.grid.top <= 8)
  assert.ok(option.grid.bottom <= 14)
})
