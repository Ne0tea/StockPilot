import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeSettingsForSave, saveThenRunTest } from './settingsSaveFlow.js'

test('normalizeSettingsForSave rewrites schedule_time using validated clock label', () => {
  const result = normalizeSettingsForSave(
    { schedule_time: '9:3', wechat_msg_type: 'markdown' },
    () => ({ isValid: true, label: '09:03' }),
  )

  assert.equal(result.schedule_time, '09:03')
  assert.equal(result.wechat_msg_type, 'markdown')
})

test('normalizeSettingsForSave throws when schedule time is invalid', () => {
  assert.throws(
    () => normalizeSettingsForSave({ schedule_time: '25:99' }, () => ({ isValid: false })),
    /分析时间格式不正确/,
  )
})

test('saveThenRunTest saves normalized settings before running test action', async () => {
  const calls = []
  const settings = { schedule_time: '9:3', smtp_email: 'sender@example.com' }

  const updateSettings = async (payload) => {
    calls.push(['save', payload])
  }

  const testAction = async () => {
    calls.push(['test'])
    return { data: { ok: true, message: 'ok' } }
  }

  const result = await saveThenRunTest(
    settings,
    updateSettings,
    testAction,
    () => ({ isValid: true, label: '09:03' }),
  )

  assert.deepEqual(calls, [
    ['save', { schedule_time: '09:03', smtp_email: 'sender@example.com' }],
    ['test'],
  ])
  assert.equal(result.normalizedSettings.schedule_time, '09:03')
  assert.deepEqual(result.testResult, { data: { ok: true, message: 'ok' } })
})
