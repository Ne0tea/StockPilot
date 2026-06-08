const INVALID_CLOCK_STATE = {
  label: '--:--',
  hourAngle: 0,
  minuteAngle: 0,
  isValid: false,
  hour: null,
  minute: null,
}

export function getScheduleClockState(scheduleTime) {
  const value = typeof scheduleTime === 'string' ? scheduleTime.trim() : ''
  const match = /^(\d{2}):(\d{2})$/.exec(value)
  if (!match) {
    return INVALID_CLOCK_STATE
  }

  const hour = Number(match[1])
  const minute = Number(match[2])
  const hasValidTime = !Number.isNaN(hour)
    && !Number.isNaN(minute)
    && hour >= 0
    && hour <= 23
    && minute >= 0
    && minute <= 59
  if (!hasValidTime) {
    return INVALID_CLOCK_STATE
  }

  return {
    label: `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
    hourAngle: ((hour % 12) + minute / 60) * 30,
    minuteAngle: minute * 6,
    isValid: true,
    hour,
    minute,
  }
}
