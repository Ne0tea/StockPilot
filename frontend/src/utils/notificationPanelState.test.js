import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildNotificationItems,
  clearNotificationSources,
  hasNotificationFailures,
  NOTIFICATION_EMPTY_TEXT,
} from './notificationPanelState.js'

test('clearNotificationSources removes current notifications and clears failure state', () => {
  const sources = {
    deliveryRecords: [
      {
        id: 1,
        report_date: '2026-06-14',
        delivery_date: '2026-06-14',
        subject: '每日推送',
        holding_names: ['平安银行'],
        status: 'success',
      },
    ],
    notificationLogs: [
      {
        id: 2,
        channel: 'email',
        status: 'failed',
        subject: '推送失败',
        error_message: 'SMTP timeout',
        is_test: false,
        created_at: '2026-06-14T09:30:00',
      },
    ],
  }

  const beforeItems = buildNotificationItems(sources)
  assert.equal(beforeItems.length, 2)
  assert.equal(hasNotificationFailures(beforeItems), true)

  clearNotificationSources(sources)

  const afterItems = buildNotificationItems(sources)
  assert.deepEqual(afterItems, [])
  assert.equal(hasNotificationFailures(afterItems), false)
  assert.equal(NOTIFICATION_EMPTY_TEXT, '当前无已推送通知')
})
