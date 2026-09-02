<template>
  <div class="chart-shell">
    <div class="chart-toolbar">
      <el-segmented
        v-model="mode"
        :options="modeOptions"
        size="small"
      />
    </div>
    <div v-if="!history.length" class="chart-empty">暂无平仓记录</div>
    <div v-else ref="chartRef" class="chart-canvas"></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { buildProfitChartOption } from '../utils/dashboardChartOptions'

const props = defineProps({
  history: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const mode = ref('amount')
const modeOptions = [
  { label: '金额', value: 'amount' },
  { label: '百分比', value: 'percent' },
]
let chart = null

onMounted(() => {
  render()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

watch(() => [props.history, mode.value], render, { deep: true, flush: 'post' })

function handleResize() {
  chart?.resize()
}

function render() {
  if (!props.history.length) {
    if (chart) {
      chart.dispose()
      chart = null
    }
    return
  }
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }
  chart.setOption(buildProfitChartOption(props.history, { mode: mode.value }), true)
  chart.resize()
}
</script>

<style scoped>
.chart-shell {
  padding: 16px 18px 18px;
}

.chart-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.chart-canvas {
  width: 100%;
  height: 240px;
}

.chart-empty {
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
  font-size: 13px;
  background: linear-gradient(180deg, #fafafa 0%, #f5f6f7 100%);
  border-radius: var(--radius-sm);
}
</style>
