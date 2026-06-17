export function normalizeSettingsForSave(settings, getScheduleClockState) {
  const scheduleClock = getScheduleClockState(settings?.schedule_time)
  if (!scheduleClock.isValid) {
    throw new Error('分析时间格式不正确，请输入 24 小时制 HH:MM')
  }

  return {
    ...settings,
    schedule_time: scheduleClock.label,
  }
}

export async function saveSettingsForm(settings, updateSettings, getScheduleClockState) {
  const normalizedSettings = normalizeSettingsForSave(settings, getScheduleClockState)
  await updateSettings(normalizedSettings)
  return normalizedSettings
}

export async function saveThenRunTest(settings, updateSettings, testAction, getScheduleClockState) {
  const normalizedSettings = await saveSettingsForm(settings, updateSettings, getScheduleClockState)
  const testResult = await testAction()
  return { normalizedSettings, testResult }
}
