<template>
  <div class="summary-cards">
    <div v-for="(card, idx) in cards" :key="idx" class="summary-card">
      <div class="card-icon" :style="{ background: card.iconBg, color: card.iconColor }">
        <el-icon :size="22"><component :is="card.icon" /></el-icon>
      </div>
      <div class="card-body">
        <span class="card-value">{{ card.value }}</span>
        <span class="card-label">{{ card.label }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  cards: {
    type: Array,
    required: true,
  },
})
</script>

<style scoped>
.summary-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  width: 100%;
  margin-bottom: 24px;
}
.summary-card {
  background: var(--bg-white);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: box-shadow var(--transition), transform var(--transition);
}
.summary-card:hover {
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-2px);
}
.card-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.card-body {
  display: flex;
  flex-direction: column;
}
.card-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}
.card-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

@media (max-width: 1200px) {
  .summary-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 600px) {
  .summary-cards {
    grid-template-columns: 1fr;
  }
}
</style>
