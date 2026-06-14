export const NOTIFICATION_EMPTY_TEXT = '当前无已推送通知'

const FAILED_STATUSES = new Set(['failed', 'test_failed'])

export function buildNotificationItems({ deliveryRecords = [], notificationLogs = [] } = {}) {
  const items = []

  for (const r of deliveryRecords) {
    items.push({
      _key: `dr-${r.id}`,
      _date: r.report_date || r.delivery_date || '',
      _label: r.holding_names?.join('、') || r.subject || '每日报告',
      _failed: r.status === 'failed',
      _delivery: r,
      channel: 'email',
      error_message: '',
    })
  }

  for (const n of notificationLogs) {
    if (!n.is_test && !FAILED_STATUSES.has(n.status)) continue
    items.push({
      _key: `nl-${n.id}`,
      _date: n.created_at ? n.created_at.slice(0, 16).replace('T', ' ') : '',
      _label: n.is_test ? `[测试] ${n.subject || ''}` : (n.subject || '推送失败'),
      _failed: FAILED_STATUSES.has(n.status),
      _delivery: null,
      channel: n.channel,
      error_message: n.error_message || '',
    })
  }

  items.sort((a, b) => (b._date > a._date ? 1 : -1))
  return items.slice(0, 40)
}

export function hasNotificationFailures(items = []) {
  return items.some((item) => item._failed)
}

export function clearNotificationSources(sources) {
  sources.deliveryRecords = []
  sources.notificationLogs = []
  return sources
}
