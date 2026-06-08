<template>
  <el-dialog
    v-model="visible"
    :title="`专项分析 — ${stock?.stock_name || ''} (${stock?.stock_code || ''})`"
    width="1180px"
    top="4vh"
    :close-on-click-modal="false"
    destroy-on-close
    @close="handleClose"
  >
    <div class="agent-skill-row">
      <span class="label">策略：</span>
      <el-select v-model="selectedSkill" :disabled="hasStarted" filterable placeholder="选择策略">
        <el-option
          v-for="s in skills"
          :key="s.name"
          :label="`${s.display_name}（${s.name}）`"
          :value="s.name"
        >
          <div class="skill-option">
            <span class="skill-option-name">{{ s.display_name }}</span>
            <span class="skill-option-desc">{{ s.description }}</span>
          </div>
        </el-option>
      </el-select>
      <el-button
        type="primary"
        :disabled="!selectedSkill || runLoading || hasStarted"
        :loading="runLoading"
        @click="startChat"
      >
        启动分析
      </el-button>
    </div>

    <section class="result-panel">
      <div class="result-panel-head">
        <div>
          <div class="result-title">分析结论</div>
          <div class="result-subtitle">这里会优先显示最终结论，避免运行结束后出现空白主体。</div>
        </div>
        <span :class="['result-badge', `is-${terminalKindClass}`]">
          {{ resultStatusLabel }}
        </span>
      </div>
      <pre class="result-content">{{ resultText }}</pre>

      <div v-if="followupMessages.length" ref="historyRef" class="followup-thread">
        <div v-for="(message, index) in followupMessages" :key="index" :class="['followup-message', message.role]">
          <div class="followup-role">{{ message.role === 'user' ? '你' : 'Agent' }}</div>
          <pre class="followup-text">{{ message.text }}</pre>
        </div>
      </div>
    </section>

    <div class="console-panel">
      <button type="button" class="console-header" @click="toggleDetails">
        <div class="console-header-main">
          <span class="console-title">执行详情</span>
          <span :class="['console-status', `is-${terminalKindClass}`]">
            {{ detailStatusLabel }}
          </span>
        </div>
        <span class="console-arrow">{{ detailsExpanded ? '收起' : '展开' }}</span>
      </button>

      <div v-show="detailsExpanded" class="console-body">
        <div class="console-grid console-grid-top">
          <section class="console-card">
            <div class="console-card-title">输入 Prompt</div>
            <pre class="console-card-content">{{ promptContent }}</pre>
          </section>

          <section class="console-card">
            <div class="console-card-title">Agent 启动日志</div>
            <div v-if="statusEvents.length" class="console-list">
              <div v-for="(event, index) in statusEvents" :key="`status-${index}`" class="console-list-item">
                {{ formatStatusEvent(event) }}
              </div>
            </div>
            <div v-else class="console-placeholder">启动后会在这里显示会话创建、技能加载和上下文构建日志。</div>
          </section>

          <section class="console-card">
            <div class="console-card-title">阶段进度 / 工具调用</div>
            <div v-if="progressItems.length" class="console-list">
              <div v-for="(item, index) in progressItems" :key="`progress-${index}`" class="console-list-item">
                {{ formatProgressItem(item) }}
              </div>
            </div>
            <div v-else class="console-placeholder">运行中会在这里持续展示阶段推进和工具调用。</div>
          </section>
        </div>

        <div class="console-grid console-grid-bottom">
          <section class="console-card console-card-diagnostic">
            <div class="console-card-title">异常 / 超时 / 空结果诊断</div>
            <div v-if="diagnostics.length" class="console-list">
              <div v-for="(item, index) in diagnostics" :key="`diagnostic-${index}`" class="console-list-item diagnostic-item">
                {{ formatDiagnostic(item) }}
              </div>
            </div>
            <div v-else class="console-placeholder">暂无诊断信息。</div>
          </section>
        </div>
      </div>
    </div>

    <div class="followup-input-row">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="2"
        :disabled="!canFollowup || followupLoading"
        placeholder="专项分析成功后，可继续追问，例如：跌破支撑位后的止损价是多少？"
        @keyup.enter.exact.prevent="sendFollowup"
      />
      <el-button type="primary" :disabled="!canFollowup || !inputText.trim() || followupLoading" :loading="followupLoading" @click="sendFollowup">
        发送
      </el-button>
    </div>

    <template #footer>
      <el-button v-if="analysisRunning" type="danger" plain @click="cancelRun">取消分析</el-button>
      <el-button @click="handleClose">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  cancelAgentStream,
  endAgentChat,
  getAgentSkills,
  sendAgentMessage,
  startAgentChatStream,
} from '../api'
import {
  applyAgentConsoleEvent,
  createAgentConsoleState,
  isAgentConsoleTerminalState,
} from '../utils/agentConsoleState'

const props = defineProps({
  modelValue: Boolean,
  stock: Object,
})
const emit = defineEmits(['update:modelValue'])

const visible = ref(props.modelValue)
const skills = ref([])
const selectedSkill = ref('')
const sessionId = ref('')
const inputText = ref('')
const runLoading = ref(false)
const followupLoading = ref(false)
const historyRef = ref(null)
const eventSourceRef = ref(null)
const consoleState = ref(createAgentConsoleState())
const followupMessages = ref([])

const hasStarted = computed(() => Boolean(sessionId.value))
const analysisRunning = computed(() => runLoading.value || (hasStarted.value && !isAgentConsoleTerminalState(consoleState.value)))
const canFollowup = computed(() => Boolean(sessionId.value && consoleState.value.status === 'success' && consoleState.value.finalResult))
const detailsExpanded = computed(() => consoleState.value.detailsExpanded)
const promptContent = computed(() => consoleState.value.prompt || '启动后会在这里显示完整输入 Prompt。')
const diagnostics = computed(() => consoleState.value.diagnostics)
const statusEvents = computed(() => consoleState.value.events.filter((event) => event.type === 'status'))
const progressItems = computed(() => consoleState.value.events.filter((event) => event.type === 'stage' || event.type === 'tool'))
const firstDiagnosticText = computed(() => diagnostics.value[0]?.text || diagnostics.value[0]?.message || '')
const terminalKindClass = computed(() => {
  const kind = consoleState.value.terminalKind
  return kind === 'running' ? (analysisRunning.value ? 'running' : 'idle') : kind
})
const detailStatusLabel = computed(() => {
  if (consoleState.value.status === 'success') return '已完成'
  if (consoleState.value.status === 'empty') return '结果为空'
  if (consoleState.value.status === 'error') return '执行异常'
  if (consoleState.value.status === 'timeout') return '执行超时'
  if (consoleState.value.status === 'cancelled') return '已取消'
  if (analysisRunning.value) return consoleState.value.statusLabel || '运行中'
  return '待启动'
})
const resultStatusLabel = computed(() => {
  if (consoleState.value.status === 'success') return '最终结果已生成'
  if (consoleState.value.status === 'empty') return '未生成有效结论'
  if (consoleState.value.status === 'error') return '分析失败'
  if (consoleState.value.status === 'timeout') return '连接超时'
  if (consoleState.value.status === 'cancelled') return '已取消'
  if (analysisRunning.value) return '分析进行中'
  return '尚未启动'
})
const resultText = computed(() => {
  if (consoleState.value.finalResult) return consoleState.value.finalResult
  if (consoleState.value.status === 'empty') {
    return '本次专项分析未生成有效结论，请展开下方执行详情查看阶段进度和诊断信息。'
  }
  if (consoleState.value.status === 'error') {
    return firstDiagnosticText.value || '专项分析执行失败，请查看下方诊断卡片。'
  }
  if (consoleState.value.status === 'timeout') {
    return firstDiagnosticText.value || '专项分析连接超时，未能收到最终结论。'
  }
  if (consoleState.value.status === 'cancelled') {
    return '本次专项分析已取消。'
  }
  if (analysisRunning.value) {
    return '正在生成结论，输入 Prompt、启动日志、阶段进度和工具调用会持续显示在下方。'
  }
  return '选择策略后点击“启动分析”，结果会完整显示在这里。'
})

watch(() => props.modelValue, async (nextValue) => {
  visible.value = nextValue
  if (nextValue) {
    await loadSkills()
    return
  }
  resetState()
})

watch(visible, (nextValue) => {
  emit('update:modelValue', nextValue)
})

function extractErrorMessage(error, fallback) {
  const data = error?.response?.data
  return data?.error || data?.message || data?.detail || error?.message || fallback
}

function pushConsoleEvent(event) {
  consoleState.value = applyAgentConsoleEvent(consoleState.value, event)
}

function closeEventStream() {
  if (eventSourceRef.value) {
    eventSourceRef.value.close()
    eventSourceRef.value = null
  }
}

async function loadSkills() {
  if (skills.value.length) return
  try {
    const { data } = await getAgentSkills()
    skills.value = data.skills || []
    if (skills.value.length && !selectedSkill.value) {
      selectedSkill.value = skills.value[0].name
    }
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '加载策略列表失败'))
  }
}

function connectStream(currentSessionId) {
  closeEventStream()

  const stream = new EventSource(`/api/agent/chat/${encodeURIComponent(currentSessionId)}/stream`)
  eventSourceRef.value = stream

  stream.onmessage = (rawEvent) => {
    let event
    try {
      event = JSON.parse(rawEvent.data)
    } catch (_) {
      return
    }

    pushConsoleEvent(event)

    if (event.type === 'session_end') {
      runLoading.value = false
      closeEventStream()
    }
  }

  stream.onerror = () => {
    if (isAgentConsoleTerminalState(consoleState.value)) {
      closeEventStream()
      return
    }

    pushConsoleEvent({
      type: 'diagnostic',
      code: 'stream_error',
      text: '专项分析事件流连接中断，请查看当前日志并考虑重新发起分析。',
    })
    pushConsoleEvent({
      type: 'session_end',
      status: 'error',
      text: '事件流连接中断',
    })
    runLoading.value = false
    closeEventStream()
  }
}

async function startChat() {
  if (!props.stock?.stock_code || !selectedSkill.value) return

  resetState({ preserveSkills: true, preserveVisible: true })
  runLoading.value = true
  pushConsoleEvent({ type: 'status', text: '正在创建专项分析会话' })

  try {
    const { data } = await startAgentChatStream(props.stock.stock_code, selectedSkill.value)

    if (data.error) {
      ElMessage.error(data.error)
      pushConsoleEvent({ type: 'diagnostic', code: 'start_error', text: data.error })
      pushConsoleEvent({ type: 'session_end', status: 'error', text: data.error })
      runLoading.value = false
      return
    }

    sessionId.value = data.session_id

    if (data.background_prompt) {
      pushConsoleEvent({ type: 'prompt', text: data.background_prompt })
    }
    pushConsoleEvent({ type: 'status', text: '启动请求已接受，正在连接事件流' })
    connectStream(data.session_id)
  } catch (error) {
    const message = extractErrorMessage(error, '启动分析失败')
    ElMessage.error(message)
    pushConsoleEvent({ type: 'diagnostic', code: 'start_error', text: message })
    pushConsoleEvent({ type: 'session_end', status: 'error', text: message })
    runLoading.value = false
  }
}

async function sendFollowup() {
  const message = inputText.value.trim()
  if (!message || !canFollowup.value) return

  followupMessages.value.push({ role: 'user', text: message })
  inputText.value = ''
  followupLoading.value = true
  await scrollFollowups()

  try {
    const { data } = await sendAgentMessage(sessionId.value, selectedSkill.value, message)
    if (data.error) {
      ElMessage.error(data.error)
      followupMessages.value.push({ role: 'assistant', text: `[失败] ${data.error}` })
    } else {
      followupMessages.value.push({ role: 'assistant', text: data.reply || '（后续追问未返回内容）' })
    }
    await scrollFollowups()
  } catch (error) {
    const failure = extractErrorMessage(error, '发送失败')
    ElMessage.error(failure)
    followupMessages.value.push({ role: 'assistant', text: `[失败] ${failure}` })
    await scrollFollowups()
  } finally {
    followupLoading.value = false
  }
}

async function cancelRun() {
  if (!sessionId.value || isAgentConsoleTerminalState(consoleState.value)) return

  closeEventStream()
  runLoading.value = false
  pushConsoleEvent({ type: 'diagnostic', code: 'cancelled', text: '用户已取消本次专项分析' })
  pushConsoleEvent({ type: 'session_end', status: 'cancelled', text: '分析已取消' })

  try {
    await cancelAgentStream(sessionId.value)
  } catch (_) {
    // The UI has already been switched to cancelled state; ignore teardown failures.
  }
}

async function scrollFollowups() {
  await nextTick()
  if (historyRef.value) {
    historyRef.value.scrollTop = historyRef.value.scrollHeight
  }
}

async function handleClose() {
  closeEventStream()
  if (sessionId.value) {
    try {
      await endAgentChat(sessionId.value)
    } catch (_) {
      // Ignore cleanup failures while closing the dialog.
    }
  }
  resetState({ preserveSkills: true, preserveVisible: true })
  visible.value = false
}

function toggleDetails() {
  consoleState.value = {
    ...consoleState.value,
    detailsExpanded: !consoleState.value.detailsExpanded,
  }
}

function resetState(options = {}) {
  const { preserveSkills = false, preserveVisible = false } = options

  closeEventStream()
  sessionId.value = ''
  inputText.value = ''
  runLoading.value = false
  followupLoading.value = false
  followupMessages.value = []
  consoleState.value = createAgentConsoleState()

  if (!preserveSkills) {
    skills.value = []
    selectedSkill.value = ''
  }
  if (!preserveVisible) {
    visible.value = false
  }
}

function formatStatusEvent(event) {
  return event.text || event.message || '状态已更新'
}

function formatProgressItem(event) {
  if (event.type === 'stage') {
    const label = event.text || event.title || event.stage || '未命名阶段'
    return `阶段：${label}${event.status ? ` · ${event.status}` : ''}${event.duration ? ` · ${event.duration}s` : ''}`
  }

  const toolName = event.tool || event.toolName || '未知工具'
  return `工具：${toolName}${event.status ? ` · ${event.status}` : ''}${event.duration ? ` · ${event.duration}s` : ''}`
}

function formatDiagnostic(event) {
  const prefix = event.code || event.level
  const text = event.text || event.message || '诊断信息为空'
  return prefix ? `[${prefix}] ${text}` : text
}
</script>

<style scoped>
.agent-skill-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.agent-skill-row .label {
  color: #4b5563;
  font-size: 13px;
}

.agent-skill-row :deep(.el-select) {
  flex: 1;
}

.skill-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.3;
  padding: 4px 0;
}

.skill-option-name {
  font-weight: 600;
}

.skill-option-desc {
  font-size: 12px;
  color: #9ca3af;
}

.result-panel {
  padding: 16px;
  border-radius: 14px;
  border: 1px solid #dbe4f0;
  background:
    radial-gradient(circle at top right, rgba(37, 99, 235, 0.12), transparent 35%),
    linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
}

.result-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.result-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.result-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.result-badge,
.console-status {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.5;
}

.result-badge.is-running,
.console-status.is-running {
  background: #eff6ff;
  color: #1d4ed8;
}

.result-badge.is-success,
.console-status.is-success {
  background: #ecfdf5;
  color: #047857;
}

.result-badge.is-error,
.result-badge.is-timeout,
.result-badge.is-cancelled,
.result-badge.is-empty,
.console-status.is-error,
.console-status.is-timeout,
.console-status.is-cancelled,
.console-status.is-empty {
  background: #fef2f2;
  color: #b91c1c;
}

.result-badge.is-idle,
.console-status.is-idle {
  background: #f3f4f6;
  color: #4b5563;
}

.result-content {
  margin: 0;
  min-height: 170px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.75;
  color: #111827;
}

.followup-thread {
  max-height: 220px;
  overflow-y: auto;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #e5e7eb;
}

.followup-message + .followup-message {
  margin-top: 12px;
}

.followup-role {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
}

.followup-message.user .followup-role {
  color: #2563eb;
}

.followup-message.assistant .followup-role {
  color: #059669;
}

.followup-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: #ffffff;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.65;
}

.followup-message.user .followup-text {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.console-panel {
  margin-top: 14px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #ffffff;
}

.console-header {
  width: 100%;
  border: 0;
  background: transparent;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.console-header-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.console-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}

.console-arrow {
  font-size: 12px;
  color: #6b7280;
}

.console-body {
  padding: 0 14px 14px;
}

.console-grid {
  display: grid;
  gap: 12px;
}

.console-grid-top {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.console-grid-bottom {
  margin-top: 12px;
  grid-template-columns: minmax(0, 1fr);
}

.console-card {
  min-height: 220px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: linear-gradient(180deg, #fcfcfd 0%, #f8fafc 100%);
}

.console-card-diagnostic {
  min-height: 120px;
}

.console-card-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.console-card-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.7;
  color: #111827;
  font-family: inherit;
}

.console-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow-y: auto;
}

.console-list-item {
  font-size: 12px;
  line-height: 1.6;
  color: #1f2937;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #e5e7eb;
}

.diagnostic-item {
  background: #fff7ed;
  border-color: #fdba74;
  color: #9a3412;
}

.console-placeholder {
  color: #9ca3af;
  font-size: 12px;
  line-height: 1.6;
}

.followup-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-top: 14px;
}

.followup-input-row :deep(.el-textarea) {
  flex: 1;
}

@media (max-width: 1100px) {
  .console-grid-top {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .result-panel-head {
    flex-direction: column;
  }

  .followup-input-row {
    flex-direction: column;
  }
}
</style>
