<template>
  <div class="section-card">
    <div v-if="title" class="section-header">
      <h2 class="section-title">
        <span class="title-dot" :style="{ background: dotColor }"></span>
        {{ title }}
      </h2>
      <span v-if="badge" class="section-badge">{{ badge }}</span>
      <slot name="header-extra" />
    </div>
    <div class="section-body">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  badge: { type: String, default: '' },
  dotColor: { type: String, default: 'var(--primary)' },
})
</script>

<style scoped>
.section-card {
  background: var(--bg-white);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border-light);
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.title-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.section-badge {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-main);
  padding: 3px 10px;
  border-radius: 12px;
  font-weight: 500;
}
.section-body {
  width: 100%;
}
</style>
