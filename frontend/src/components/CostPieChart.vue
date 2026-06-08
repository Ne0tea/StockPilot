<template>
  <div class="chart-shell">
    <div v-if="!hasData" class="chart-empty">暂无持仓数据</div>
    <div v-else ref="chartRef" class="chart-canvas"></div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { buildCostPieChartOption } from '../utils/dashboardChartOptions'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const hasData = computed(() => props.items.some((item) => Number(item?.cost) > 0))
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

watch(() => props.items, render, { deep: true, flush: 'post' })

function handleResize() {
  chart?.resize()
}

function render() {
  if (!hasData.value) {
    chart?.clear()
    return
  }
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }
  chart.setOption(buildCostPieChartOption(props.items), true)
  chart.resize()
}
</script>

<style scoped>
.chart-shell {
  padding: 16px 18px 18px;
}

.chart-canvas {
  width: 100%;
  height: 252px;
}

.chart-empty {
  min-height: 252px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
  font-size: 13px;
  background: linear-gradient(180deg, #fafafa 0%, #f5f6f7 100%);
  border-radius: var(--radius-sm);
}
</style>
