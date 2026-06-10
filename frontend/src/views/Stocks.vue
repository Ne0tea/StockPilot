<template>
  <div class="stocks-page">
    <PageHeader title="股票管理" subtitle="管理您的自选股列表">
      <template #actions>
        <el-button @click="handleAnalyzeAll" class="btn-orange">
          <el-icon style="margin-right:4px"><VideoPlay /></el-icon>
          全部分析
        </el-button>
      </template>
    </PageHeader>

    <!-- Add Stock Form -->
    <div class="action-bar">
      <div class="add-form">
        <el-input v-model="form.stock_code" placeholder="股票代码" @blur="autofillStockForm('stock_code')" class="form-input" />
        <el-input v-model="form.name" placeholder="股票名称" @blur="autofillStockForm('name')" class="form-input" />
        <el-select v-model="form.market" placeholder="市场" class="form-select">
          <el-option label="沪市" value="sh" /><el-option label="深市" value="sz" />
          <el-option label="港股" value="hk" /><el-option label="美股" value="us" />
        </el-select>
        <el-button type="primary" @click="handleAdd">
          <el-icon style="margin-right:4px"><Plus /></el-icon>
          添加
        </el-button>
      </div>
      <div class="reset-actions">
        <el-button :loading="isClearingAll" :disabled="isClearingAll || isResetting" @click="handleClearAllAnalysis" class="btn-outline-warning btn-reset">
          清空全部分析数据
        </el-button>
        <el-button :loading="isResetting" :disabled="isResetting" @click="handleReset" class="btn-outline-danger btn-reset">
          初始化 — 清空自选股与分析数据
        </el-button>
      </div>
    </div>

    <div class="stocks-grid">
      <SectionCard title="自选股列表" dot-color="var(--primary)">
        <el-table
          :data="stocksList"
          :header-cell-style="{ background: '#F8F9FA', color: '#999', fontSize: '12px', fontWeight: '600' }"
        >
          <el-table-column prop="name" label="名称" width="130">
            <template #default="{row}">
              <span class="stock-name" :title="row.name">
                <span v-if="row.is_held" class="held-star" title="持仓股">★</span>
                <span class="stock-name-text">{{ row.name }}</span>
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="stock_code" label="代码" width="100" />
          <el-table-column prop="market" label="市场" width="90">
            <template #default="{row}">
              <span class="market-tag">{{ marketLabel(row.market) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="今日状态" width="120">
            <template #default="{row}">
              <el-tag v-if="statusKind(row.stock_code)==='running'" size="small" type="info" class="status-tag">
                <el-icon class="is-loading" style="margin-right:4px"><Loading /></el-icon>
                分析中
              </el-tag>
              <el-tag
                v-else-if="statusKind(row.stock_code)==='done'"
                size="small"
                class="status-tag"
                :class="{ 'status-done': canPreviewTodayReport(row.stock_code) }"
                @click.stop="openTodayReportPreview(row.stock_code)"
              >
                ✓ 完成
              </el-tag>
              <el-tag v-else-if="statusKind(row.stock_code)==='error'" size="small" type="danger" class="status-tag">
                失败
              </el-tag>
              <span v-else class="status-idle">—</span>
            </template>
          </el-table-column>
          <el-table-column label="今日日志" width="140">
            <template #default="{row}">
              <el-button
                v-if="todayLogMap[row.stock_code]?.is_active"
                size="small"
                class="log-btn log-btn-active"
                @click.stop="openTodayLog(row.stock_code)"
              >
                📝 实时日志
              </el-button>
              <el-button
                v-else-if="todayLogMap[row.stock_code]"
                size="small"
                class="log-btn"
                :class="{ 'log-btn-stale': todayLogMap[row.stock_code].date !== todayDateRef }"
                @click.stop="openTodayLog(row.stock_code)"
              >
                {{ todayLogMap[row.stock_code].date === todayDateRef ? '📄 查看日志' : '📄 历史日志' }}
              </el-button>
              <span v-else class="status-idle">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="220" fixed="right">
            <template #default="{row}">
              <div class="row-actions">
                <div class="row-actions-group">
                  <button
                    class="icon-btn icon-btn-primary"
                    :disabled="analysisState[row.stock_code]==='running'"
                    :title="analysisState[row.stock_code]==='running' ? '分析中' : (hasTodayReport(row.stock_code) ? '重新生成报告（交互分析）' : '交互分析')"
                    @click.stop="startAnalysis(row)"
                  >
                    <el-icon v-if="analysisState[row.stock_code]==='running'" class="is-loading"><Loading /></el-icon>
                    <el-icon v-else><VideoPlay /></el-icon>
                  </button>
                  <button
                    class="icon-btn icon-btn-orange"
                    :disabled="analysisState[row.stock_code]==='running'"
                    :title="hasTodayReport(row.stock_code) ? '⚡ 重新生成报告（一键分析）' : '⚡ 一键分析'"
                    @click.stop="startQuickAnalysis(row)"
                  >
                    ⚡
                  </button>
                  <button
                    v-if="row.is_held"
                    class="icon-btn icon-btn-primary"
                    title="基于持仓的策略专项分析"
                    @click.stop="openAgentDialog(row)"
                  >
                    🤖
                  </button>
                </div>
                <div class="row-actions-spacer"></div>
                <button
                  class="icon-btn icon-btn-warning"
                  :disabled="analysisState[row.stock_code]==='running'"
                  title="清理该股票全部分析报告"
                  @click.stop="handleClearStockAnalysis(row)"
                >
                  <el-icon><Brush /></el-icon>
                </button>
                <button
                  class="icon-btn icon-btn-remove"
                  title="移除"
                  @click.stop="remove(row)"
                >
                  <el-icon><Delete /></el-icon>
                </button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="历史评分趋势" dot-color="var(--accent-orange)">
        <div class="history-list">
          <div v-for="stock in stocksList" :key="stock.stock_code" class="history-row">
            <div class="history-row-header">
              <span class="history-stock-name">{{ stock.name }}</span>
              <span class="history-stock-code">{{ stock.stock_code }}</span>
            </div>
            <div class="history-row-body">
              <ScoreChart
                v-if="historyMap[stock.stock_code]?.length"
                :history="historyMap[stock.stock_code]"
                compact
              />
              <div v-else class="history-empty">暂无历史报告</div>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>

    <!-- Interactive Analysis Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="`分析 ${dialogStock.name} (${dialogStock.stock_code})`"
      width="720px"
      top="5vh"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      destroy-on-close
    >
      <div ref="outputRef" class="analysis-output">
        <div v-for="(msg, idx) in streamMessages" :key="idx" :class="['msg', msg.type]">
          <template v-if="msg.type === 'status'">
            <div class="msg-status">
              <el-icon><Loading /></el-icon> <em>{{ msg.text }}</em>
            </div>
          </template>
          <template v-else-if="msg.type === 'progress'">
            <div class="msg-progress">
              <span class="progress-action">{{ msg.action }}</span>
              <span class="progress-text">{{ msg.text }}</span>
            </div>
          </template>
          <template v-else-if="msg.type === 'output'">
            <div class="msg-output md-text" v-html="renderMd(msg.text)"></div>
          </template>
          <template v-else-if="msg.type === 'user-response'">
            <div class="msg-user-resp">→ {{ msg.text }}</div>
          </template>
          <template v-else-if="msg.type === 'error'">
            <div class="msg-error">{{ msg.text }}</div>
          </template>
        </div>

        <div v-if="isAnalyzing" class="typing-indicator">
          <span></span><span></span><span></span>
        </div>
      </div>

      <div v-if="pendingQuestion" class="input-section">
        <div class="question-box">
          <div class="question-head">
            <p class="question-text">{{ pendingQuestion.question }}</p>
            <el-tag size="small" effect="plain">{{ questionKindLabel(pendingQuestion.kind) }}</el-tag>
          </div>
          <p v-if="pendingQuestion.details" class="question-details">{{ pendingQuestion.details }}</p>
          <div v-if="pendingQuestion.options?.length" class="quick-btns">
            <el-button
              v-for="option in pendingQuestion.options"
              :key="option"
              size="small"
              @click="quickReply(option)"
            >
              {{ option }}
            </el-button>
          </div>
          <div class="input-row">
            <el-input
              v-model="userInput"
              :placeholder="pendingQuestion.default ? `默认: ${pendingQuestion.default}` : '请输入回复'"
              @keyup.enter="sendResponse"
              style="flex:1"
            />
            <el-button type="primary" @click="sendResponse">发送</el-button>
            <el-button v-if="pendingQuestion.default" @click="sendDefault">使用默认</el-button>
          </div>
          <div class="question-footer">
            <span>超时后将自动使用默认值继续</span>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button v-if="isAnalyzing" type="danger" plain @click="cancelAnalysisSession">取消分析</el-button>
        <el-button v-else @click="dialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- Report Preview Dialog -->
    <el-dialog v-model="reportDialogVisible" title="分析报告" width="96%" top="2vh" destroy-on-close class="report-view-dialog">
      <iframe v-if="reportUrl" :src="reportUrl" class="report-frame" />
    </el-dialog>

    <!-- Today Log Preview Dialog -->
    <el-dialog
      v-model="logDialogVisible"
      :title="logDialogTitle"
      width="80%"
      top="6vh"
      destroy-on-close
      class="log-view-dialog"
      @close="stopLogAutoRefresh"
    >
      <pre class="log-viewer">{{ logContent || '（暂无内容）' }}</pre>
      <template #footer>
        <el-button @click="downloadLog">下载</el-button>
        <el-button v-if="logIsActive" :loading="logRefreshing" @click="refreshLog">刷新</el-button>
        <el-button @click="logDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <AgentChatDialog v-model="agentDialogVisible" :stock="agentDialogStock" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted, onUnmounted } from 'vue'
import {
  getWatchlist, addStock, removeStock, resetWatchlist,
  clearAllAnalysisData, clearStockAnalysisData,
  getReports, getAnalysisStatus, resolveStock,
  getWatchlistOverview,
  startInteractiveAnalysisWithMode, respondToAnalysis, cancelAnalysis,
  getTodayLog,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, VideoPlay, Delete, Plus, Brush } from '@element-plus/icons-vue'
import ScoreChart from '../components/ScoreChart.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionCard from '../components/SectionCard.vue'
import AgentChatDialog from '../components/AgentChatDialog.vue'
import {
  buildTodayHtmlReportPreviewUrl,
  buildBulkAnalyzeConfirmationText,
  getBulkAnalyzableStocks,
  hasReadyTodayHtmlReport,
} from '../utils/reportHelpers'
import { applyResolvedStock, buildLookupFailureMessage, buildLookupQuery } from '../utils/stockLookup'
import {
  clearPollingTimers,
  closeAnalysisEventSource,
  createEmptyStockPageState,
  getStockResetConfirmationText,
  getStockResetSuccessMessage,
} from '../utils/stockReset'
import {
  analysisState,
  todayReportMap,
  todayLogMap,
  stocksList,
  historyMap,
  setStocksList,
  setHistoryFor,
  pruneHistoryMap,
  setAnalysisStatus,
  clearAnalysisStatus,
  setTodayReport,
  setTodayLog,
  pruneAnalysisStore,
  resetAnalysisStore,
  isOverviewCacheFresh,
  applyOverviewSnapshot,
  invalidateOverviewCache,
  lastSyncedAt,
  todayDate as todayDateRef,
} from '../stores/analysisStore'
import {
  getStocksStatusKind,
  hasShanghaiDayChanged,
  resolveTodayReportRecord,
} from '../utils/stocksStatus.js'

// ── Stock list state ───────────────────────────────────────────────────────
const form = ref({ stock_code: '', name: '', market: 'sh' })
const pollTimers = ref({})
const reportDialogVisible = ref(false)
const reportUrl = ref('')
const isResetting = ref(false)
const isClearingAll = ref(false)
let statusPollTimer = null
const STATUS_POLL_INTERVAL = 5000

const logDialogVisible = ref(false)
const logDialogTitle = ref('今日日志')
const logContent = ref('')
const logIsActive = ref(false)
const logRefreshing = ref(false)
let currentLogPath = ''
let logDialogCode = ''

// ── Interactive dialog state ───────────────────────────────────────────────
const dialogVisible = ref(false)
const dialogStock = reactive({ stock_code: '', name: '' })
const streamMessages = ref([])
const isAnalyzing = ref(false)
const pendingQuestion = ref(null)
const userInput = ref('')
const outputRef = ref(null)
let eventSource = null

// ── Agent专项分析 dialog state ─────────────────────────────────────────────
const agentDialogVisible = ref(false)
const agentDialogStock = ref(null)
function openAgentDialog(row) {
  agentDialogStock.value = {
    stock_code: row.stock_code,
    stock_name: row.name,
    is_held: row.is_held,
  }
  agentDialogVisible.value = true
}

onMounted(async () => {
  if (!isOverviewCacheFresh() || stocksList.value.length === 0) {
    await loadOverview({ silent: false })
  }
  startStatusPoll()
  startDayChangeWatcher()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  closeSSE()
  closeAllBulkSSE()
  stopLogAutoRefresh()
  pollTimers.value = clearPollingTimers(pollTimers.value)
  stopStatusPoll()
  stopDayChangeWatcher()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

let dayChangeTimer = null
const DAY_CHANGE_POLL_INTERVAL = 60 * 1000

function startDayChangeWatcher() {
  if (dayChangeTimer) return
  dayChangeTimer = setInterval(checkDayChange, DAY_CHANGE_POLL_INTERVAL)
}

function stopDayChangeWatcher() {
  if (dayChangeTimer) {
    clearInterval(dayChangeTimer)
    dayChangeTimer = null
  }
}

async function checkDayChange() {
  if (hasShanghaiDayChanged(todayDateRef.value)) {
    invalidateOverviewCache()
    await loadOverview({ silent: true })
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    checkDayChange()
  }
}

async function loadOverview({ silent = true } = {}) {
  let response
  try {
    response = await getWatchlistOverview()
  } catch (err) {
    if (!silent) {
      ElMessage.error(`无法加载自选股数据：${err.message || err}`)
    }
    return false
  }
  applyOverviewSnapshot(response?.data || {})
  loadTodayLogStates()
  return true
}

// ── Stock CRUD ─────────────────────────────────────────────────────────────
async function handleAdd() {
  if (!form.value.stock_code && !form.value.name) {
    return ElMessage.warning('请填写代码和名称')
  }
  const lookupField = form.value.stock_code ? 'stock_code' : 'name'
  const resolved = await ensureStockFormResolved()
  if (!resolved || !form.value.stock_code || !form.value.name) {
    return ElMessage.error(buildLookupFailureMessage(form.value, lookupField))
  }
  await addStock(form.value)
  invalidateOverviewCache()
  await loadOverview({ silent: false })
  form.value = { stock_code: '', name: '', market: 'sh' }
  ElMessage.success('添加成功')
}
async function remove(row) {
  await removeStock(row.id)
  invalidateOverviewCache()
  setHistoryFor(row.stock_code, null)
  setTodayReport(row.stock_code, null)
  clearAnalysisStatus(row.stock_code)
  await loadOverview({ silent: true })
}

async function handleReset() {
  if (isResetting.value) {
    return
  }

  try {
    await ElMessageBox.confirm(
      getStockResetConfirmationText(),
      '确认初始化',
      {
        confirmButtonText: '确认初始化',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  isResetting.value = true
  try {
    await resetWatchlist()
    resetStockPageState()
    ElMessage.success(getStockResetSuccessMessage())
  } catch (err) {
    ElMessage.error(`初始化失败: ${err.message || err}`)
  } finally {
    isResetting.value = false
  }
}

async function handleClearAllAnalysis() {
  if (isClearingAll.value) {
    return
  }

  try {
    await ElMessageBox.confirm(
      '此操作将删除全部股票的分析报告与报告文件（保留自选股、持仓与设置）。确认后立即执行，且不可撤销。',
      '清空全部分析数据',
      {
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  isClearingAll.value = true
  try {
    closeSSE()
    closeAllBulkSSE()
    stopStatusPoll()
    await clearAllAnalysisData()
    for (const code of Object.keys(analysisState)) clearAnalysisStatus(code)
    for (const stock of stocksList.value) {
      setHistoryFor(stock.stock_code, null)
      setTodayReport(stock.stock_code, null)
      setTodayLog(stock.stock_code, null)
    }
    invalidateOverviewCache()
    await loadOverview({ silent: true })
    ElMessage.success('已清空全部分析数据')
  } catch (err) {
    ElMessage.error(`清空失败: ${err.message || err}`)
  } finally {
    isClearingAll.value = false
  }
}

async function handleClearStockAnalysis(row) {
  try {
    await ElMessageBox.confirm(
      `此操作将删除 ${row.name} 的全部分析报告与报告文件（保留自选股条目）。确认后立即执行，且不可撤销。`,
      '清理分析数据',
      {
        confirmButtonText: '确认清理',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    await clearStockAnalysisData(row.stock_code)
    clearAnalysisStatus(row.stock_code)
    setHistoryFor(row.stock_code, null)
    setTodayReport(row.stock_code, null)
    setTodayLog(row.stock_code, null)
    invalidateOverviewCache()
    await loadOverview({ silent: true })
    ElMessage.success(`已清理 ${row.name} 的分析数据`)
  } catch (err) {
    ElMessage.error(`清理失败: ${err.message || err}`)
  }
}

async function autofillStockForm(field) {
  const query = buildLookupQuery(form.value, field)
  if (!query) {
    return
  }
  try {
    const { data } = await resolveStock(field, query)
    applyResolvedStock(form.value, data, field)
  } catch {
    // Keep manual input untouched when lookup fails.
  }
}

async function ensureStockFormResolved() {
  if (form.value.stock_code && !form.value.name) {
    await autofillStockForm('stock_code')
    return Boolean(form.value.stock_code && form.value.name)
  }
  if (form.value.name && !form.value.stock_code) {
    await autofillStockForm('name')
    return Boolean(form.value.stock_code && form.value.name)
  }
  return Boolean(form.value.stock_code && form.value.name)
}

async function refreshHistories(list = stocksList.value) {
  const settled = await Promise.allSettled(
    (list || []).map(async (stock) => {
      const { data } = await getReports(stock.stock_code)
      return [stock.stock_code, Array.isArray(data) ? data : []]
    }),
  )
  const validCodes = new Set((list || []).map((s) => s.stock_code))
  pruneHistoryMap(validCodes)
  for (const result of settled) {
    if (result.status !== 'fulfilled') continue
    const [code, items] = result.value
    setHistoryFor(code, items)
  }
}

// ── Interactive analysis (弹窗模式) ────────────────────────────────────────

/** 打开交互式分析弹窗 */
async function startAnalysis(row) {
  if (analysisState[row.stock_code] === 'running') {
    dialogStock.stock_code = row.stock_code
    dialogStock.name = row.name
    streamMessages.value = []
    isAnalyzing.value = true
    pendingQuestion.value = null
    userInput.value = ''
    dialogVisible.value = true
    connectSSE(row.stock_code, row.name, false)
    return
  }

  if (hasTodayReport(row.stock_code) && !(await confirmRegenerate(row.name))) {
    return
  }

  // Set up dialog
  dialogStock.stock_code = row.stock_code
  dialogStock.name = row.name
  streamMessages.value = []
  isAnalyzing.value = true
  pendingQuestion.value = null
  userInput.value = ''
  dialogVisible.value = true

  try {
    await startInteractiveAnalysisWithMode(row.stock_code, false)
    connectSSE(row.stock_code, row.name, false)
    await refreshTodayLogState(row.stock_code)
    await refreshAnalysisStatus(row.stock_code)
  } catch (err) {
    ElMessage.error(`启动分析失败: ${err.message || err}`)
    isAnalyzing.value = false
    await refreshAnalysisStatus(row.stock_code)
  }
}

/** 一键快速分析（自动使用所有默认值，不弹交互窗口） */
async function startQuickAnalysis(row) {
  if (analysisState[row.stock_code] === 'running') {
    ElMessage.warning('分析正在进行中…')
    return
  }

  if (hasTodayReport(row.stock_code) && !(await confirmRegenerate(row.name))) {
    return
  }

  ElMessage.info(`⚡ 一键分析 ${row.name}，全程自动…`)

  try {
    await startInteractiveAnalysisWithMode(row.stock_code, true)
    connectSSE(row.stock_code, row.name, true)
    await refreshTodayLogState(row.stock_code)
    await refreshAnalysisStatus(row.stock_code)
  } catch (err) {
    ElMessage.error(`启动分析失败: ${err.message || err}`)
    await refreshAnalysisStatus(row.stock_code)
  }
}

async function confirmRegenerate(name) {
  try {
    await ElMessageBox.confirm(
      `${name} 今日已存在分析报告，是否重新生成并替换已有文件？`,
      '重新生成报告',
      {
        confirmButtonText: '重新生成',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    return true
  } catch {
    return false
  }
}

/** Connect to SSE stream */
let sseReconnectAttempts = 0
let sseReconnectTimer = null
let sseHeartbeatTimer = null
let lastSSEMessageTime = 0

// ── Bulk parallel run state ────────────────────────────────────────────────
let bulkRunning = false
// Independent SSE listeners for parallel bulk runs, keyed by stock code.
// Each value is a teardown fn that closes the stream and clears its timers.
const bulkSessions = new Map()

function closeAllBulkSSE() {
  for (const teardown of bulkSessions.values()) {
    try { teardown() } catch { /* ignore */ }
  }
  bulkSessions.clear()
}

function connectSSE(code, name, autoRespond = false) {
  closeSSE()

  eventSource = new EventSource(`/api/analyze/${code}/stream`)
  lastSSEMessageTime = Date.now()

  // 心跳监控：30秒无消息则认为连接异常
  sseHeartbeatTimer = setInterval(() => {
    if (Date.now() - lastSSEMessageTime > 30000 && eventSource?.readyState === EventSource.OPEN) {
      console.warn('SSE heartbeat timeout, reconnecting...')
      reconnectSSE(code, name, autoRespond)
    }
  }, 10000)

  eventSource.onmessage = async (e) => {
    lastSSEMessageTime = Date.now()
    sseReconnectAttempts = 0

    if (e.data === ':ping') return

    let event
    try {
      event = JSON.parse(e.data)
    } catch { return }

    switch (event.type) {
      case 'status':
      case 'progress':
      case 'output':
      case 'error':
        if (!autoRespond) {
          streamMessages.value.push({ type: event.type, text: event.text, action: event.action })
          scrollOutput()
        }
        break

      case 'question': {
        if (autoRespond) break

        pendingQuestion.value = {
          question: event.question || '请回复：',
          default: event.default || '',
          options: Array.isArray(event.options) ? event.options : [],
          kind: event.kind || 'text_confirmation',
          details: event.details || '',
          timeoutSeconds: event.timeout_seconds || 30,
        }
        userInput.value = ''
        streamMessages.value.push({
          type: 'status',
          text: `❓ ${pendingQuestion.value.question}${pendingQuestion.value.default ? ` (默认: ${pendingQuestion.value.default})` : ''}`,
        })
        scrollOutput()
        break
      }

      case 'user-response':
        if (!autoRespond) {
          streamMessages.value.push({
            type: 'user-response',
            text: event.auto ? `${event.text}${event.text?.includes('自动') ? '' : ' (自动)'}` : event.text,
          })
          pendingQuestion.value = null
          scrollOutput()
        }
        break

      case 'session_end':
        closeSSE()
        isAnalyzing.value = false
        pendingQuestion.value = null
        userInput.value = ''
        await refreshAnalysisStatus(code)
        await refreshTodayReportState(code)
        await refreshTodayLogState(code)
        if (!autoRespond) {
          const statusText = event.status === 'done'
            ? '✅ 分析完成！'
            : event.status === 'cancelled'
              ? '⚠️ 分析已取消'
              : `❌ 分析失败${event.text ? `: ${event.text}` : ''}`
          streamMessages.value.push({ type: event.status === 'error' ? 'error' : 'status', text: statusText })
          scrollOutput()
        } else if (event.status === 'done') {
          ElMessage.success(`${name} 一键分析完成`)
        } else if (event.status === 'cancelled') {
          ElMessage.info(`${name} 分析已取消`)
        } else {
          ElMessage.error(`${name} 分析失败${event.text ? `: ${event.text}` : ''}`)
        }
        break
    }
  }

  eventSource.onerror = () => {
    if (analysisState[code] === 'running') {
      reconnectSSE(code, name, autoRespond)
    } else {
      closeSSE()
      isAnalyzing.value = false
    }
  }
}

function reconnectSSE(code, name, autoRespond) {
  closeSSE()

  if (sseReconnectAttempts >= 5) {
    isAnalyzing.value = false
    refreshAnalysisStatus(code)
    if (!autoRespond) {
      streamMessages.value.push({ type: 'error', text: '连接多次失败，请重试' })
    } else {
      ElMessage.error(`${name} 分析中断`)
    }
    return
  }

  const delay = Math.min(1000 * Math.pow(2, sseReconnectAttempts), 10000)
  sseReconnectAttempts++

  if (!autoRespond) {
    streamMessages.value.push({ type: 'status', text: `连接断开，${delay / 1000}秒后重连 (${sseReconnectAttempts}/5)...` })
    scrollOutput()
  }

  sseReconnectTimer = setTimeout(() => {
    if (analysisState[code] === 'running') {
      connectSSE(code, name, autoRespond)
    }
  }, delay)
}

function closeSSE() {
  if (sseHeartbeatTimer) {
    clearInterval(sseHeartbeatTimer)
    sseHeartbeatTimer = null
  }
  if (sseReconnectTimer) {
    clearTimeout(sseReconnectTimer)
    sseReconnectTimer = null
  }
  eventSource = closeAnalysisEventSource(eventSource)
}

/** Send typed response */
async function sendResponse() {
  const text = userInput.value.trim() || pendingQuestion.value?.default || ''
  if (!text) return
  try {
    await respondToAnalysis(dialogStock.stock_code, text)
  } catch (err) {
    ElMessage.error('发送失败')
  }
}

/** Send default answer immediately */
async function sendDefault() {
  const text = pendingQuestion.value?.default || ''
  if (!text) return
  try {
    await respondToAnalysis(dialogStock.stock_code, text)
  } catch { /* ignore */ }
}

/** Quick reply buttons */
async function quickReply(text) {
  try {
    await respondToAnalysis(dialogStock.stock_code, text)
  } catch { /* ignore */ }
}

/** Cancel current session */
async function cancelAnalysisSession() {
  await cancelAnalysis(dialogStock.stock_code)
  closeSSE()
  isAnalyzing.value = false
  pendingQuestion.value = null
  userInput.value = ''
  await refreshAnalysisStatus(dialogStock.stock_code)
  streamMessages.value.push({ type: 'status', text: '⚠️ 分析已取消' })
}

/** Simple Markdown → HTML (safe subset) */
function renderMd(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

/** Auto-scroll output area */
function scrollOutput() {
  nextTick(() => {
    if (outputRef.value) {
      outputRef.value.scrollTop = outputRef.value.scrollHeight
    }
  })
}

function startStatusPoll() {
  if (statusPollTimer) return
  statusPollTimer = setInterval(pollStatusesOnce, STATUS_POLL_INTERVAL)
}

function stopStatusPoll() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

async function pollStatusesOnce() {
  await Promise.allSettled(stocksList.value.map((stock) => refreshAnalysisStatus(stock.stock_code)))
  lastSyncedAt.value = Date.now()
}

async function refreshAnalysisStatus(code) {
  try {
    const { data } = await getAnalysisStatus(code)
    setAnalysisStatus(code, data.status || 'idle')
  } catch {
    // ignore transient errors; next tick will retry
  }
}

async function analyzeAll() {
  if (bulkRunning) {
    ElMessage.warning('全部分析正在进行中…')
    return
  }

  const analyzableStocks = getBulkAnalyzableStocks(
    stocksList.value,
    todayReportMap,
    analysisState,
  )

  if (!analyzableStocks.length) {
    ElMessage.info('已跳过全部股票：今日报告已存在或分析正在进行中')
    return
  }

  bulkRunning = true
  const total = analyzableStocks.length
  ElMessage.info(`⚡ 全部分析已启动，共 ${total} 只股票并行执行…`)
  try {
    const results = await Promise.all(
      analyzableStocks.map((stock) => runBulkAnalysis(stock.stock_code, stock.name)),
    )
    const doneCount = results.filter((s) => s === 'done').length
    const failCount = total - doneCount
    ElMessage.success(`全部分析完成：成功 ${doneCount} 只${failCount ? `，失败 ${failCount} 只` : ''}`)
  } finally {
    bulkRunning = false
    closeAllBulkSSE()
  }
}

async function handleAnalyzeAll() {
  try {
    await ElMessageBox.confirm(
      buildBulkAnalyzeConfirmationText(),
      '全部分析',
      {
        confirmButtonText: '确认启动',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  await analyzeAll()
}

/**
 * Run one auto-respond analysis with an isolated SSE listener so multiple
 * stocks can stream in parallel without clobbering the shared eventSource.
 * Resolves with the final status ('done' | 'error' | 'cancelled').
 */
function runBulkAnalysis(code, name) {
  return new Promise(async (resolve) => {
    try {
      await startInteractiveAnalysisWithMode(code, true)
      await refreshTodayLogState(code)
      await refreshAnalysisStatus(code)
    } catch (err) {
      ElMessage.error(`启动分析失败 ${name}: ${err.message || err}`)
      await refreshAnalysisStatus(code)
      resolve('error')
      return
    }
    connectBulkSSE(code, name, resolve)
  })
}

/** Isolated SSE connection for parallel bulk runs (auto-respond only). */
function connectBulkSSE(code, name, onEnd) {
  let attempts = 0
  let es = null
  let heartbeatTimer = null
  let reconnectTimer = null
  let lastMessageTime = Date.now()
  let settled = false
  let logActivated = false

  const teardown = () => {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    es = closeAnalysisEventSource(es)
    bulkSessions.delete(code)
  }

  const finish = (status) => {
    if (settled) return
    settled = true
    teardown()
    onEnd(status)
  }

  const open = () => {
    es = new EventSource(`/api/analyze/${code}/stream`)
    lastMessageTime = Date.now()

    heartbeatTimer = setInterval(() => {
      if (Date.now() - lastMessageTime > 30000 && es?.readyState === EventSource.OPEN) {
        reconnect()
      }
    }, 10000)

    es.onmessage = async (e) => {
      lastMessageTime = Date.now()
      attempts = 0
      if (e.data === ':ping') return

      // First real stream event means the per-code log file now exists and
      // the session is live — flip the "📝 实时日志" button on for this stock.
      if (!logActivated) {
        logActivated = true
        refreshTodayLogState(code)
      }

      let event
      try {
        event = JSON.parse(e.data)
      } catch { return }

      if (event.type !== 'session_end') return

      if (event.status === 'done') {
        await refreshAnalysisStatus(code)
        await refreshTodayReportState(code)
        await refreshTodayLogState(code)
        ElMessage.success(`${name} 一键分析完成`)
      } else if (event.status === 'cancelled') {
        await refreshAnalysisStatus(code)
        ElMessage.info(`${name} 分析已取消`)
      } else {
        await refreshAnalysisStatus(code)
        ElMessage.error(`${name} 分析失败${event.text ? `: ${event.text}` : ''}`)
      }
      finish(event.status)
    }

    es.onerror = () => {
      if (analysisState[code] === 'running') {
        reconnect()
      } else {
        finish('error')
      }
    }
  }

  const reconnect = () => {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    es = closeAnalysisEventSource(es)

    if (attempts >= 5) {
      refreshAnalysisStatus(code)
      ElMessage.error(`${name} 分析中断`)
      finish('error')
      return
    }

    const delay = Math.min(1000 * Math.pow(2, attempts), 10000)
    attempts++
    reconnectTimer = setTimeout(() => {
      if (analysisState[code] === 'running') {
        open()
      } else {
        finish('error')
      }
    }, delay)
  }

  bulkSessions.set(code, teardown)
  open()
}
function statusKind(code) {
  return getStocksStatusKind({
    analysisValue: analysisState[code],
    todayReport: todayReportMap[code] || null,
  })
}

function hasTodayReport(code) {
  const report = todayReportMap[code]
  return Boolean(report?.report_file_path && report?.html_status === 'ready')
}

function canPreviewTodayReport(code) {
  return hasReadyTodayHtmlReport(todayReportMap[code], todayDateRef.value)
}

function openTodayReportPreview(code) {
  const previewUrl = buildTodayHtmlReportPreviewUrl(todayReportMap[code], todayDateRef.value)
  if (!previewUrl) {
    return
  }
  reportUrl.value = previewUrl
  reportDialogVisible.value = true
}

function hasTodayMarkdownResult(code) {
  const report = todayReportMap[code]
  return Boolean(report?.markdown_file_path || hasTodayReport(code))
}

function showCompletedState(code) {
  return analysisState[code] === 'done' || hasTodayMarkdownResult(code)
}

async function refreshTodayReportStates() {
  const validCodes = new Set(stocksList.value.map((s) => s.stock_code))
  const settled = await Promise.allSettled(stocksList.value.map(async (stock) => {
    const report = await fetchTodayReport(stock.stock_code)
    return [stock.stock_code, report]
  }))
  for (const code of Object.keys(todayReportMap)) {
    if (!validCodes.has(code)) setTodayReport(code, null)
  }
  for (const result of settled) {
    if (result.status !== 'fulfilled') continue
    const [code, report] = result.value
    setTodayReport(code, report)
  }
}

async function refreshTodayReportState(code) {
  const report = await fetchTodayReport(code)
  setTodayReport(code, report)
}

async function fetchTodayReport(code) {
  const { data } = await getReports(code, 10)
  const today = todayDateRef.value
  return resolveTodayReportRecord(data, today)
}

async function openTodayLog(code) {
  const info = todayLogMap[code]
  if (!info?.path) {
    ElMessage.info('今日尚未生成日志')
    return
  }
  const stock = stocksList.value.find((s) => s.stock_code === code)
  logDialogTitle.value = `今日日志 - ${stock?.name || code} (${code})`
  logIsActive.value = Boolean(info.is_active)
  logDialogCode = code
  currentLogPath = info.path
  logDialogVisible.value = true
  await loadLogContent()
  if (logIsActive.value) startLogAutoRefresh()
}

let logAutoRefreshTimer = null
const LOG_AUTO_REFRESH_INTERVAL = 2000

function startLogAutoRefresh() {
  stopLogAutoRefresh()
  logAutoRefreshTimer = setInterval(async () => {
    if (!logDialogVisible.value) {
      stopLogAutoRefresh()
      return
    }
    await loadLogContent()
    // Stop tailing once the backend reports the session is no longer active.
    if (logDialogCode) {
      const { data } = await getTodayLog(logDialogCode).catch(() => ({ data: null }))
      if (data && !data.is_active) {
        logIsActive.value = false
        stopLogAutoRefresh()
      }
    }
  }, LOG_AUTO_REFRESH_INTERVAL)
}

function stopLogAutoRefresh() {
  if (logAutoRefreshTimer) {
    clearInterval(logAutoRefreshTimer)
    logAutoRefreshTimer = null
  }
}

async function loadLogContent() {
  if (!currentLogPath) return
  try {
    const resp = await fetch(currentLogPath, { cache: 'no-store' })
    if (!resp.ok) {
      logContent.value = `（加载失败：HTTP ${resp.status}）`
      return
    }
    logContent.value = await resp.text()
  } catch (err) {
    logContent.value = `（加载失败：${err.message || err}）`
  }
}

async function refreshLog() {
  logRefreshing.value = true
  try {
    await loadLogContent()
  } finally {
    logRefreshing.value = false
  }
}

function downloadLog() {
  if (currentLogPath) {
    window.open(currentLogPath, '_blank')
  }
}

async function refreshTodayLogState(code) {
  try {
    const { data } = await getTodayLog(code)
    if (data?.exists) {
      setTodayLog(code, data)
    } else {
      setTodayLog(code, null)
    }
  } catch {
    // ignore transient errors
  }
}

async function loadTodayLogStates() {
  await Promise.allSettled(stocksList.value.map((s) => refreshTodayLogState(s.stock_code)))
}

function questionKindLabel(kind) {
  const labels = {
    login_confirmation: '登录确认',
    tool_permission: '权限确认',
  }
  return labels[kind] || '继续确认'
}

function marketLabel(market) {
  const map = { sh: '沪市', sz: '深市', hk: '港股', us: '美股' }
  return map[market] || market
}

function resetStockPageState() {
  closeSSE()
  pollTimers.value = clearPollingTimers(pollTimers.value)
  stopStatusPoll()
  resetAnalysisStore()
  invalidateOverviewCache()

  const emptyState = createEmptyStockPageState()
  setStocksList(emptyState.stocks)
  form.value = emptyState.form
  reportDialogVisible.value = emptyState.reportDialogVisible
  reportUrl.value = emptyState.reportUrl
  dialogVisible.value = emptyState.dialogVisible
  dialogStock.stock_code = emptyState.dialogStock.stock_code
  dialogStock.name = emptyState.dialogStock.name
  streamMessages.value = emptyState.streamMessages
  isAnalyzing.value = emptyState.isAnalyzing
  pendingQuestion.value = emptyState.pendingQuestion
  userInput.value = emptyState.userInput
}
</script>

<style scoped>
/* ── Action Bar ── */
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.add-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.form-input {
  width: 140px;
}
.form-select {
  width: 110px;
}

/* ── Action Bar Buttons ── */
.btn-orange {
  background: var(--accent-orange);
  border-color: var(--accent-orange);
  color: #fff;
}
.btn-orange:hover {
  background: #e05a00;
  border-color: #e05a00;
  color: #fff;
}
.btn-reset {
  flex-shrink: 0;
}
.reset-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.btn-outline-warning {
  background: #fff;
  border: 1px solid var(--accent-orange);
  color: var(--accent-orange);
}
.btn-outline-warning:hover {
  background: var(--accent-orange-light);
}
.btn-outline-danger {
  background: #fff;
  border: 1px solid var(--color-down);
  color: var(--color-down);
}
.btn-outline-danger:hover {
  background: var(--color-down-light);
}

/* ── Stocks Grid ── */
.stocks-grid {
  display: grid;
  grid-template-columns: 2.5fr 1fr;
  gap: 20px;
  width: 100%;
  margin-bottom: 24px;
}

/* ── Market Tag ── */
.market-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
  background: #F4F4F5;
  color: #909399;
}

/* ── Report Button ── */
.report-btn {
  background: var(--accent-blue-light) !important;
  border-color: var(--accent-blue-light) !important;
  color: var(--accent-blue) !important;
  font-size: 12px !important;
}
.report-btn:hover {
  background: #d4e4ff !important;
}

.log-btn {
  background: var(--accent-orange-light) !important;
  border-color: var(--accent-orange-light) !important;
  color: var(--accent-orange) !important;
  font-size: 12px !important;
}
.log-btn:hover {
  background: #ffe4cc !important;
}
.log-btn-active {
  background: var(--color-up-light) !important;
  border-color: var(--color-up-light) !important;
  color: var(--color-up) !important;
}
.log-btn-stale {
  background: #f4f4f5 !important;
  border-color: #e4e7ed !important;
  color: #909399 !important;
  font-style: italic;
}

:deep(.log-view-dialog) {
  max-width: none;
}
.log-viewer {
  max-height: 70vh;
  overflow: auto;
  background: #1e1e1e;
  color: #e8e8e8;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

/* ── History Panel ── */
.history-list {
  padding: 12px 16px 16px;
}
.history-row {
  min-height: 128px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-light);
}
.history-row:last-child {
  border-bottom: none;
}
.history-row-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.history-stock-name {
  font-weight: 600;
  color: var(--text-primary);
}
.history-stock-code {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-main);
  padding: 3px 8px;
  border-radius: 999px;
}
.history-row-body {
  min-height: 80px;
  display: flex;
  align-items: center;
}
.history-empty {
  width: 100%;
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-placeholder);
  font-size: 13px;
  background: linear-gradient(180deg, #fafafa 0%, #f6f7f8 100%);
  border-radius: var(--radius-sm);
}

/* ── Table Row Actions ── */
.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  width: 100%;
}
.row-actions-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.row-actions-spacer {
  flex: 1;
}
.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background var(--transition), transform var(--transition);
  background: var(--bg-main);
  color: var(--text-secondary);
}
.icon-btn:hover:not(:disabled) {
  transform: scale(1.1);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.icon-btn-primary:hover:not(:disabled) {
  background: var(--accent-blue-light);
  color: var(--accent-blue);
}
.icon-btn-orange:hover:not(:disabled) {
  background: var(--accent-orange-light);
  color: var(--accent-orange);
}
.icon-btn-warning {
  background: var(--accent-orange-light);
  color: var(--accent-orange);
}
.icon-btn-warning:hover:not(:disabled) {
  background: var(--accent-orange);
  color: #fff;
}
.icon-btn-remove {
  background: var(--color-up-light);
  color: var(--color-up);
}
.icon-btn-remove:hover:not(:disabled) {
  background: var(--color-up);
  color: #fff;
}

/* ── Held Star ── */
.held-star {
  color: var(--accent-orange);
  margin-right: 4px;
  font-size: 14px;
}

/* ── Stock Name (truncate to ~6 CJK chars) ── */
.stock-name {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
}
.stock-name-text {
  display: inline-block;
  max-width: 6em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

/* ── Status Styles ── */
.status-idle {
  color: var(--text-placeholder);
  font-size: 13px;
}
.status-done {
  color: var(--color-down);
  font-weight: 600;
  cursor: pointer;
}


/* ── Report Dialog ── */
:deep(.report-view-dialog) {
  max-width: none;
}
.report-frame {
  width: 100%;
  height: calc(100vh - 150px);
  min-height: 78vh;
  border: none;
  display: block;
}

/* ── Analysis Dialog ── */
.analysis-output {
  max-height: 50vh;
  overflow-y: auto;
  padding: 16px;
  background: #F8F9FA;
  border-radius: var(--radius-sm);
  font-size: 13px;
  line-height: 1.7;
}
.msg {
  margin-bottom: 8px;
  padding: 4px 0;
}
.msg-status {
  color: var(--text-secondary);
  font-style: italic;
  display: flex;
  align-items: center;
  gap: 6px;
}
.msg-progress {
  color: #909399;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.progress-action {
  background: var(--accent-blue-light);
  color: var(--accent-blue);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}
.progress-text {
  color: var(--text-secondary);
}
.msg-output {
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-output :deep(code) {
  background: #E8E8E8;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
.msg-user-resp {
  color: var(--accent-blue);
  font-weight: 500;
  padding-left: 12px;
  border-left: 3px solid var(--accent-blue);
}
.msg-error {
  background: var(--color-down-light);
  color: var(--color-down);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 13px;
}
.input-section {
  margin-top: 12px;
}
.question-box {
  background: var(--accent-blue-light);
  padding: 16px;
  border-radius: var(--radius-md);
}
.question-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.question-text {
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary);
}
.question-details {
  margin: 0 0 10px;
  color: var(--text-secondary);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.quick-btns {
  margin-top: 10px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.question-footer {
  margin-top: 10px;
  color: var(--text-placeholder);
  font-size: 12px;
}

/* ── Typing Indicator ── */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}
.typing-indicator span {
  width: 6px;
  height: 6px;
  background: #909399;
  border-radius: 50%;
  animation: bounce 1.2s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}

@media (max-width: 1100px) {
  .stocks-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .add-form {
    width: 100%;
  }
  .form-input {
    width: 100%;
    flex: 1;
  }
}
</style>
