<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
            <polyline points="16 7 22 7 22 13" />
          </svg>
        </div>
        <span v-show="!sidebarCollapsed" class="logo-text">股票助手</span>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: $route.path === item.path }"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span v-show="!sidebarCollapsed" class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <span v-show="!sidebarCollapsed" class="sidebar-version">v1.0</span>
      </div>
    </aside>

    <!-- Main Area -->
    <div class="main-area">
      <!-- Header -->
      <header class="top-header">
        <button class="hamburger" @click="sidebarCollapsed = !sidebarCollapsed">
          <el-icon :size="20"><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
        </button>
        <div class="header-right">
          <el-popover placement="bottom-end" :width="380" trigger="click" popper-class="record-popover">
            <template #reference>
              <button class="header-btn">
                <el-icon :size="18"><Bell /></el-icon>
                <span v-if="hasFailures" class="header-badge-dot error"></span>
                <span v-else-if="notifications.length" class="header-badge-dot"></span>
              </button>
            </template>
            <div class="record-panel">
              <div class="record-panel-header">
                <span class="record-title">推送通知</span>
                <div class="record-panel-actions">
                  <span class="record-count">{{ notifications.length }}</span>
                  <button
                    v-if="notifications.length"
                    type="button"
                    class="record-clear-btn"
                    :disabled="clearingNotifications"
                    @click="clearCurrentNotifications"
                  >{{ clearingNotifications ? '清除中' : '清除' }}</button>
                </div>
              </div>
              <button
                v-for="item in notifications"
                :key="item._key"
                class="record-item"
                :class="{ 'record-item--fail': item._failed }"
                @click="item._delivery ? openDeliveryRecord(item) : null"
              >
                <div class="record-item-top">
                  <span class="record-channel-badge" :class="'badge-' + (item.channel || 'email')">
                    {{ item.channel === 'wechat' ? '微信' : '邮件' }}
                  </span>
                  <span class="record-date">{{ item._date }}</span>
                  <span class="record-status-icon" v-if="item._failed">✗ 失败</span>
                  <span class="record-status-icon ok" v-else>✓</span>
                </div>
                <span class="record-text">{{ item._label }}</span>
                <span v-if="item.error_message" class="record-error">{{ item.error_message }}</span>
              </button>
              <div v-if="!notifications.length" class="record-empty">{{ NOTIFICATION_EMPTY_TEXT }}</div>
            </div>
          </el-popover>
        </div>
      </header>

      <!-- Content -->
      <main class="content-area">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { clearNotifications, getDeliveryRecords, getNotifications } from './api'
import {
  buildNotificationItems,
  clearNotificationSources,
  hasNotificationFailures,
  NOTIFICATION_EMPTY_TEXT,
} from './utils/notificationPanelState'
import {
  Odometer,
  TrendCharts,
  Document,
  Suitcase,
  Setting,
  Fold,
  Expand,
  Bell,
} from '@element-plus/icons-vue'

const router = useRouter()
const sidebarCollapsed = ref(false)
const deliveryRecords = ref([])
const notificationLogs = ref([])
const clearingNotifications = ref(false)

const navItems = [
  { path: '/', label: '仪表盘', icon: Odometer },
  { path: '/stocks', label: '股票管理', icon: TrendCharts },
  { path: '/reports', label: '分析报告', icon: Document },
  { path: '/portfolio', label: '持仓管理', icon: Suitcase },
  { path: '/settings', label: '设置', icon: Setting },
]

const notifications = computed(() => buildNotificationItems({
  deliveryRecords: deliveryRecords.value,
  notificationLogs: notificationLogs.value,
}))

const hasFailures = computed(() => hasNotificationFailures(notifications.value))

onMounted(loadAll)

async function loadAll() {
  const [dr, nl] = await Promise.allSettled([getDeliveryRecords(), getNotifications()])
  if (dr.status === 'fulfilled') deliveryRecords.value = dr.value.data || []
  if (nl.status === 'fulfilled') notificationLogs.value = nl.value.data || []
}

function openDeliveryRecord(item) {
  const r = item._delivery
  if (!r) return
  router.push({ path: '/reports', query: { start: r.report_date, end: r.report_date } })
}

async function clearCurrentNotifications() {
  if (clearingNotifications.value || !notifications.value.length) return
  clearingNotifications.value = true
  try {
    await clearNotifications()
  } finally {
    clearingNotifications.value = false
  }

  const cleared = clearNotificationSources({
    deliveryRecords: deliveryRecords.value,
    notificationLogs: notificationLogs.value,
  })
  deliveryRecords.value = cleared.deliveryRecords
  notificationLogs.value = cleared.notificationLogs
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ── Sidebar ── */
.sidebar {
  width: 220px;
  min-width: 220px;
  background: var(--bg-sidebar);
  display: flex;
  flex-direction: column;
  transition: width var(--transition), min-width var(--transition);
  z-index: 100;
  overflow: hidden;
}
.sidebar.collapsed {
  width: 64px;
  min-width: 64px;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 18px;
  border-bottom: 1px solid rgba(255,255,255,0.12);
  min-height: 68px;
}
.logo-icon {
  width: 36px;
  height: 36px;
  background: rgba(255,255,255,0.18);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.logo-text {
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 1px;
  white-space: nowrap;
  overflow: hidden;
  transition: opacity var(--transition);
}

/* ── Nav Items ── */
.sidebar-nav {
  flex: 1;
  padding: 12px 0;
  overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  height: 46px;
  color: rgba(255,255,255,0.72);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  position: relative;
  transition: background var(--transition), color var(--transition);
  cursor: pointer;
  white-space: nowrap;
}
.nav-item:hover {
  background: var(--bg-sidebar-hover);
  color: #fff;
}
.nav-item.active {
  background: var(--bg-sidebar-active);
  color: #fff;
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  background: #fff;
  border-radius: 0 3px 3px 0;
}
.nav-icon {
  font-size: 19px;
  flex-shrink: 0;
}
.nav-label {
  white-space: nowrap;
  overflow: hidden;
  transition: opacity var(--transition);
}

.sidebar-footer {
  padding: 14px 18px;
  border-top: 1px solid rgba(255,255,255,0.12);
}
.sidebar-version {
  color: rgba(255,255,255,0.35);
  font-size: 11px;
}

/* ── Main Area ── */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.top-header {
  height: 56px;
  min-height: 56px;
  background: var(--bg-white);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  z-index: 50;
}
.hamburger {
  background: none;
  border: none;
  cursor: pointer;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  transition: background var(--transition);
}
.hamburger:hover {
  background: var(--bg-main);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-btn {
  position: relative;
  background: none;
  border: none;
  cursor: pointer;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: var(--text-secondary);
  transition: background var(--transition);
}
.header-btn:hover {
  background: var(--bg-main);
}
.header-badge-dot {
  position: absolute;
  top: 7px;
  right: 8px;
  width: 7px;
  height: 7px;
  background: var(--primary);
  border-radius: 50%;
  border: 1.5px solid #fff;
}
.header-badge-dot.error {
  background: var(--el-color-danger, #f56c6c);
}

/* ── Content ── */
.content-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background: var(--bg-main);
}

/* ── Notification Panel ── */
.record-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 420px;
  overflow-y: auto;
}

.record-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.record-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.record-count {
  font-size: 12px;
  color: var(--text-secondary);
}

.record-panel-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.record-clear-btn {
  border: 1px solid var(--border-light);
  background: var(--bg-white);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: color var(--transition), border-color var(--transition), background var(--transition);
}
.record-clear-btn:hover {
  background: var(--bg-main);
  border-color: var(--primary);
  color: var(--primary);
}
.record-clear-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.record-item {
  border: none;
  background: #f7f8fa;
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  cursor: default;
  width: 100%;
}
.record-item[onclick], .record-item._delivery {
  cursor: pointer;
}
.record-item:hover {
  background: #eef2f7;
}
.record-item--fail {
  background: #fff5f5;
  border-left: 3px solid var(--el-color-danger, #f56c6c);
}
.record-item--fail:hover {
  background: #ffe8e8;
}

.record-item-top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.record-channel-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}
.badge-email {
  background: #e8f0fe;
  color: #1a73e8;
}
.badge-wechat {
  background: #e6f4ea;
  color: #1e8e3e;
}

.record-date {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  flex: 1;
}

.record-status-icon {
  font-size: 11px;
  color: var(--el-color-danger, #f56c6c);
  font-weight: 600;
}
.record-status-icon.ok {
  color: var(--el-color-success, #67c23a);
}

.record-text {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.record-error {
  font-size: 11px;
  color: var(--el-color-danger, #f56c6c);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.record-empty {
  padding: 16px 8px;
  color: var(--text-placeholder);
  font-size: 12px;
  text-align: center;
}
</style>
