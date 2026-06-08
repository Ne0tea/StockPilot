<template>
  <div ref="chartRef" :style="chartStyle"></div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { buildScoreChartOption } from '../utils/scoreChartOptions'

const props = defineProps({
  history: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
})
const chartRef = ref(null)
const chartStyle = computed(() => ({
  width: '100%',
  height: props.compact ? '80px' : '320px',
}))
let chart = null

onMounted(() => {
  chart = echarts.init(chartRef.value)
  render()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

watch(() => [props.history, props.compact], render, { deep: true })

function handleResize() {
  chart?.resize()
}

function render() {
  if (!chart) return
  if (!props.history?.length) {
    chart.clear()
    return
  }
  chart.setOption(buildScoreChartOption(props.history, { compact: props.compact }), true)
  chart.resize()
}
</script>
