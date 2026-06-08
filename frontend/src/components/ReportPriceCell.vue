<template>
  <div class="report-price-cell">
    <template v-if="row.has_report && row.price !== null && row.price !== undefined">
      <span class="price-value">¥{{ formatMoney(row.price) }}</span>
      <span v-if="row.price_date" class="price-date">{{ row.price_date }}</span>
    </template>
    <template v-else>
      <el-tag size="small" type="info" class="no-report-tag">未分析</el-tag>
      <el-button
        size="small"
        type="primary"
        link
        class="analyze-link"
        @click="$emit('analyze')"
      >立即分析</el-button>
    </template>
  </div>
</template>

<script setup>
defineProps({
  row: { type: Object, required: true },
})
defineEmits(['analyze'])

function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '--'
  return Number(value).toFixed(2)
}
</script>

<style scoped>
.report-price-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.price-value {
  font-weight: 500;
  color: var(--text-primary);
}
.price-date {
  color: var(--text-secondary);
  font-size: 12px;
}
.no-report-tag {
  background: #F4F4F5;
  color: #909399;
  border-color: transparent;
}
.analyze-link {
  padding: 0;
  font-size: 12px;
}
</style>
