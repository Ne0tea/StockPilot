const SCORE_COLORS = {
  总分: '#C0161D',
  基本面: '#1677FF',
  资金面: '#FF6B00',
  新闻面: '#00A86B',
  技术面: '#909399',
}

const DEFAULT_SERIES = [
  { name: '总分', key: 'score_total' },
  { name: '基本面', key: 'score_fundamental' },
  { name: '资金面', key: 'score_capital' },
  { name: '新闻面', key: 'score_news' },
  { name: '技术面', key: 'score_technical' },
]

export function buildScoreChartOption(history = [], { compact = false } = {}) {
  const dates = history.map((item) => item.date)
  const seriesDefs = compact ? DEFAULT_SERIES.slice(0, 1) : DEFAULT_SERIES

  const series = seriesDefs.map(({ name, key }) => {
    const isTotal = name === '总分'
    const color = SCORE_COLORS[name]
    return {
      name,
      type: 'line',
      smooth: true,
      symbol: compact ? 'none' : 'circle',
      symbolSize: isTotal ? 6 : 4,
      lineStyle: {
        width: compact ? 2 : isTotal ? 3 : 1.5,
        color,
      },
      itemStyle: { color },
      areaStyle: !compact && isTotal
        ? {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(192, 22, 29, 0.25)' },
                { offset: 1, color: 'rgba(192, 22, 29, 0.02)' },
              ],
            },
          }
        : undefined,
      emphasis: {
        focus: 'series',
        itemStyle: { borderWidth: 2, borderColor: '#fff' },
      },
      data: history.map((item) => item[key]),
    }
  })

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: '#EBEBEB',
      borderWidth: 1,
      textStyle: { color: '#1A1A1A', fontSize: 12 },
      axisPointer: { type: 'cross', lineStyle: { color: '#EBEBEB' } },
    },
    legend: compact
      ? { show: false }
      : {
          show: true,
          data: seriesDefs.map((item) => item.name),
          bottom: 0,
          icon: 'roundRect',
          itemWidth: 12,
          itemHeight: 3,
          textStyle: { color: '#666', fontSize: 12 },
        },
    grid: compact
      ? { top: 6, left: 4, right: 4, bottom: 10, containLabel: true }
      : { top: 20, left: 10, right: 16, bottom: 40, containLabel: true },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#EBEBEB' } },
      axisLabel: compact
        ? { show: true, color: '#B0B5BD', fontSize: 9, margin: 2, hideOverlap: true }
        : { color: '#999', fontSize: 11 },
      axisTick: { show: false },
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 10,
      splitLine: { lineStyle: { color: '#F5F5F5', type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: compact
        ? { show: true, color: '#B0B5BD', fontSize: 9, margin: 2, hideOverlap: true }
        : { color: '#999', fontSize: 11 },
    },
    series,
  }
}
