import test from 'node:test'
import assert from 'node:assert/strict'

import { getScheduleClockState } from './scheduleClock.js'

test('returns hand angles for 15:35', () => {
  assert.deepEqual(getScheduleClockState('15:35'), {
    label: '15:35',
    hourAngle: 107.5,
    minuteAngle: 210,
    isValid: true,
    hour: 15,
    minute: 35,
  })
})

test('returns fallback state for invalid schedule time', () => {
  assert.deepEqual(getScheduleClockState(''), {
    label: '--:--',
    hourAngle: 0,
    minuteAngle: 0,
    isValid: false,
    hour: null,
    minute: null,
  })
})

test('rejects invalid 24 hour input values', () => {
  assert.deepEqual(getScheduleClockState('24:00'), {
    label: '--:--',
    hourAngle: 0,
    minuteAngle: 0,
    isValid: false,
    hour: null,
    minute: null,
  })
})
