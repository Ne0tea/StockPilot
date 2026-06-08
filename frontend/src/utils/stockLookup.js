const MARKET_LABELS = {
  sh: '沪市',
  sz: '深市',
  hk: '港股',
  us: '美股',
}

function resolveNameKey(form) {
  if (!form) return 'name'
  return 'stock_name' in form ? 'stock_name' : 'name'
}

export function buildLookupQuery(form, field) {
  if (!form) {
    return ''
  }
  const nameKey = resolveNameKey(form)
  return String(field === 'stock_code' ? form.stock_code || '' : form[nameKey] || '').trim()
}

export function buildLookupFailureMessage(form, field) {
  const isCodeField = field === 'stock_code'
  const nameKey = resolveNameKey(form)
  const rawValue = String(isCodeField ? form?.stock_code || '' : form?.[nameKey] || '').trim()
  if (!rawValue) {
    return '无法识别股票，请检查后重新录入'
  }
  return isCodeField
    ? `无法识别股票代码"${rawValue}"，请检查后重新录入`
    : `无法识别股票名称"${rawValue}"，请检查后重新录入`
}

export function applyResolvedStock(form, result, field) {
  if (!form || !result) {
    return false
  }

  const nameKey = resolveNameKey(form)
  form.stock_code = result.code || form.stock_code || ''
  form[nameKey] = result.name || form[nameKey] || ''
  if ('market' in form) {
    form.market = result.market || form.market || ''
  }
  if (field === 'stock_code' && !form[nameKey]) {
    form[nameKey] = result.name || ''
  }
  if (field === 'name' && !form.stock_code) {
    form.stock_code = result.code || ''
  }
  return true
}

export function buildLookupResultSummary(result) {
  if (!result) return ''
  const marketLabel = MARKET_LABELS[result.market] || result.market || '--'
  return `${result.name || '--'} (${result.code || '--'}) / ${marketLabel}`
}
