export function buildProfitChartOption(history = [], { mode = 'amount' } = {}) {
  const isPercentMode = mode === 'percent'
  const valueKey = isPercentMode ? 'cumulative_pct' : 'cumulative_profit'

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: '#EBEBEB',
      borderWidth: 1,
      textStyle: { color: '#1A1A1A', fontSize: 12 },
      valueFormatter: (value) => (isPercentMode ? `${value}%` : `¥${value}`),
    },
    grid: {
      top: 24,
      left: 12,
      right: 16,
      bottom: 24,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: history.map((item) => item.date),
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#EBEBEB' } },
      axisLabel: { color: '#999', fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#F3F3F3', type: 'dashed' } },
      axisLabel: {
        color: '#999',
        fontSize: 11,
        formatter: (value) => (isPercentMode ? `${value}%` : `¥${value}`),
      },
    },
    series: [
      {
        name: isPercentMode ? '累计收益率' : '累计收益',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 3, color: '#00A86B' },
        itemStyle: { color: '#00A86B' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(0, 168, 107, 0.28)' },
              { offset: 1, color: 'rgba(0, 168, 107, 0.02)' },
            ],
          },
        },
        data: history.map((item) => item[valueKey]),
      },
    ],
  }
}

export function buildCostPieChartOption(items = []) {
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fff',
      borderColor: '#EBEBEB',
      borderWidth: 1,
      textStyle: { color: '#1A1A1A', fontSize: 12 },
      formatter: ({ name, value, percent }) => `${name}<br/>¥${value} (${percent}%)`,
    },
    series: [
      {
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '54%'],
        avoidLabelOverlap: true,
        label: {
          color: '#666',
          fontSize: 12,
          formatter: '{b}',
        },
        labelLine: {
          length: 10,
          length2: 8,
        },
        data: items
          .filter((item) => Number(item?.cost) > 0)
          .map((item) => ({
            name: item.name,
            value: Number(item.cost),
          })),
      },
    ],
  }
}
