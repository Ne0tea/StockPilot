<template>
  <div class="settings-page">
    <PageHeader title="设置" subtitle="配置推送通知和定时任务" />

    <div v-if="settings" class="settings-grid">
      <!-- Email Config -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-blue-light); color: var(--accent-blue);">
            <el-icon :size="20"><Message /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">邮件推送配置</h3>
            <p class="card-header-desc">自动识别 SMTP 服务器，支持 QQ/163/Gmail/Outlook 等</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Promotion /></el-icon>
              发件邮箱
            </label>
            <el-input v-model="settings.smtp_email" placeholder="sender@example.com" />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Lock /></el-icon>
              授权码
            </label>
            <el-input v-model="settings.smtp_password" type="password" show-password placeholder="输入授权码" />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><User /></el-icon>
              收件邮箱
            </label>
            <el-input v-model="settings.receiver_email" placeholder="receiver@example.com（多个用逗号分隔）" />
          </div>
          <div class="form-footer">
            <el-button size="small" :loading="testingEmail" @click="doTestEmail">
              <el-icon style="margin-right:4px"><Promotion /></el-icon>
              发送测试邮件
            </el-button>
            <span v-if="emailTestResult" :class="['test-result', emailTestResult.ok ? 'ok' : 'fail']">
              {{ emailTestResult.message }}
            </span>
          </div>
        </div>
      </div>

      <!-- WeChat Config -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-green-light); color: var(--accent-green);">
            <el-icon :size="20"><ChatDotRound /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">企业微信推送</h3>
            <p class="card-header-desc">通过企业微信机器人 Webhook 推送分析报告</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Link /></el-icon>
              Webhook URL
            </label>
            <el-input v-model="settings.wechat_webhook_url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Document /></el-icon>
              消息类型
            </label>
            <el-select v-model="settings.wechat_msg_type" style="width:100%">
              <el-option label="Markdown（企业微信内显示格式）" value="markdown" />
              <el-option label="Markdown_v2（企业微信新格式）" value="markdown_v2" />
              <el-option label="Text（纯文本，微信也可查看）" value="text" />
            </el-select>
          </div>
          <div class="form-footer">
            <el-button size="small" :loading="testingWechat" @click="doTestWechat">
              <el-icon style="margin-right:4px"><ChatDotRound /></el-icon>
              发送测试消息
            </el-button>
            <span v-if="wechatTestResult" :class="['test-result', wechatTestResult.ok ? 'ok' : 'fail']">
              {{ wechatTestResult.message }}
            </span>
          </div>
        </div>
      </div>

      <!-- Schedule Config -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-orange-light); color: var(--accent-orange);">
            <el-icon :size="20"><Clock /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">定时任务</h3>
            <p class="card-header-desc">设置每日自动分析的执行时间</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Timer /></el-icon>
              分析时间
            </label>
            <el-input
              v-model="settings.schedule_time"
              placeholder="15:35"
              maxlength="5"
              inputmode="numeric"
            />
            <p class="field-hint">请输入 24 小时制时间，格式 `HH:MM`，例如 `09:30`、`15:35`。</p>
          </div>
        </div>
      </div>

      <!-- Specialist Analysis LLM Config -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-blue-light); color: var(--accent-blue);">
            <el-icon :size="20"><Cpu /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">专项分析LLM配置</h3>
            <p class="card-header-desc">为持仓专项分析配置 OpenAI 兼容接口</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Lock /></el-icon>
              API Key
            </label>
            <el-input v-model="settings.agent_api_key" type="password" show-password placeholder="sk-..." />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Link /></el-icon>
              Base URL
            </label>
            <el-input v-model="settings.agent_base_url" placeholder="https://api.openai.com/v1" />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><MagicStick /></el-icon>
              模型
            </label>
            <el-input v-model="settings.agent_model" placeholder="gpt-4o-mini" />
          </div>
        </div>
      </div>

      <!-- TickFlow Kline Config -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-green-light); color: var(--accent-green);">
            <el-icon :size="20"><Link /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">K线配置</h3>
            <p class="card-header-desc">保存后立即生效于 TickFlow K 线获取能力</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Lock /></el-icon>
              K线获取Api
            </label>
            <el-input
              v-model="settings.tickflow_api_key"
              type="password"
              show-password
              placeholder="tk_..."
            />
          </div>
        </div>
      </div>

      <!-- Daily Report LLM Config (OpenCode) -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-orange-light); color: var(--accent-orange);">
            <el-icon :size=20><MagicStick /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">每日报告LLM配置 (OpenCode)</h3>
            <p class="card-header-desc">保存后自动 patch ~/.config/opencode/opencode.jsonc</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Cpu /></el-icon>
              Provider
            </label>
            <el-select v-model="settings.opencode_provider" style="width:100%" @change="onProviderChange">
              <el-option
                v-for="p in opencodeProviderPresets"
                :key="p.value"
                :label="p.label"
                :value="p.value"
              >
                <div style="display:flex; flex-direction:column; gap:2px;">
                  <span style="font-weight:500;">{{ p.label }}</span>
                  <span style="font-size:11px; color: var(--text-secondary);">{{ p.hint }}</span>
                </div>
              </el-option>
            </el-select>
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><MagicStick /></el-icon>
              Model
            </label>
            <el-select
              v-model="settings.opencode_model"
              style="width:100%"
              filterable
              allow-create
              default-first-option
              :placeholder="modelPlaceholder"
            >
              <el-option
                v-for="m in currentModelOptions"
                :key="m"
                :label="m"
                :value="m"
              />
            </el-select>
            <p class="field-hint">格式：<code>provider/model-id</code>。可下拉选择推荐模型，也可手输任意 opencode 支持的模型。</p>
          </div>
          <template v-if="showCustomCreds">
            <div class="form-group">
              <label class="form-label">
                <el-icon class="label-icon"><Link /></el-icon>
                Base URL
              </label>
              <el-input
                v-model="settings.opencode_base_url"
                :placeholder="baseUrlPlaceholder"
              />
            </div>
            <div class="form-group">
              <label class="form-label">
                <el-icon class="label-icon"><Lock /></el-icon>
                API Key
              </label>
              <el-input
                v-model="settings.opencode_api_key"
                type="password"
                show-password
                placeholder="sk-..."
              />
            </div>
            <p class="field-hint">用于 Anthropic/OpenAI 兼容网关（如 kuaipao.pro）。opencode-go 不需要凭据。</p>
          </template>
          <details v-if="hasLegacyClaudeConfig" class="legacy-collapse">
            <summary>已弃用的 claude_* 字段（旧版兼容）</summary>
            <div class="legacy-grid">
              <div class="form-group">
                <label class="form-label">claude_model</label>
                <el-input v-model="settings.claude_model" placeholder="claude-sonnet-4-6" />
              </div>
              <div class="form-group">
                <label class="form-label">claude_api_key</label>
                <el-input v-model="settings.claude_api_key" type="password" show-password />
              </div>
              <div class="form-group">
                <label class="form-label">claude_auth_token</label>
                <el-input v-model="settings.claude_auth_token" type="password" show-password />
              </div>
              <div class="form-group">
                <label class="form-label">claude_base_url</label>
                <el-input v-model="settings.claude_base_url" />
              </div>
            </div>
            <p class="field-hint">仍会同步写入 <code>backend/reports/.claude/settings.json</code>（兼容旧版 Claude Code 调用路径），可留空让其自然失效。</p>
          </details>
        </div>
      </div>
    </div>

    <!-- Save Button -->
    <div v-if="settings" class="settings-footer">
      <el-button type="primary" @click="save" :loading="saving">
        <el-icon style="margin-right:4px"><Check /></el-icon>
        保存全部设置
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getSettings, updateSettings, testEmail, testWechat } from '../api'
import { ElMessage } from 'element-plus'
import {
  Message, Promotion, Lock, User,
  Clock, Timer, Check,
  Cpu, Link, MagicStick,
  ChatDotRound, Document,
} from '@element-plus/icons-vue'
import PageHeader from '../components/PageHeader.vue'
import { getScheduleClockState } from '../utils/scheduleClock'
import { saveSettingsForm, saveThenRunTest } from '../utils/settingsSaveFlow'

const settings = ref(null)
const saving = ref(false)
const testingEmail = ref(false)
const testingWechat = ref(false)
const emailTestResult = ref(null)
const wechatTestResult = ref(null)

const opencodeProviderPresets = [
  { value: 'opencode-go', label: 'opencode-go (Coding Plan 订阅)', hint: '走 opencode-go 计费，无需填写 API Key' },
  { value: 'anthropic', label: 'anthropic (官方/兼容网关)', hint: '需要 Base URL + API Key' },
  { value: 'openai', label: 'openai (官方/兼容网关)', hint: '需要 Base URL + API Key' },
  { value: 'custom', label: 'custom (自定义 provider)', hint: '需要 Base URL + API Key' },
]

const opencodeModelOptions = {
  'opencode-go': [
    'opencode-go/minimax-m3',
    'opencode-go/deepseek-v4-pro',
    'opencode-go/deepseek-v4-flash',
    'opencode-go/glm-5.3-flash',
    'opencode-go/kimi-k2.7-code',
    'opencode-go/gpt-6-luna',
  ],
  'anthropic': [
    'anthropic/claude-sonnet-4-6',
    'anthropic/claude-opus-4-6',
    'anthropic/claude-haiku-4-5',
  ],
  'openai': [
    'openai/gpt-5.5',
    'openai/gpt-5.4-mini',
    'openai/o4-mini',
  ],
  'custom': [],
}

const customProviders = new Set(['anthropic', 'openai', 'custom'])

onMounted(async () => { settings.value = (await getSettings()).data })

const currentModelOptions = computed(() => {
  const p = settings.value?.opencode_provider || 'opencode-go'
  return opencodeModelOptions[p] || []
})

const showCustomCreds = computed(() => customProviders.has(settings.value?.opencode_provider))

const modelPlaceholder = computed(() => {
  const p = settings.value?.opencode_provider || 'opencode-go'
  const def = opencodeModelOptions[p]?.[0]
  return def || 'provider/model-id'
})

const baseUrlPlaceholder = computed(() => {
  const p = settings.value?.opencode_provider
  if (p === 'anthropic') return 'https://api.anthropic.com'
  if (p === 'openai') return 'https://api.openai.com/v1'
  return 'https://your-gateway.example.com'
})

const hasLegacyClaudeConfig = computed(() => {
  const s = settings.value || {}
  return Boolean(s.claude_model || s.claude_api_key || s.claude_auth_token || s.claude_base_url)
})

function onProviderChange() {
  const p = settings.value?.opencode_provider
  const opts = opencodeModelOptions[p] || []
  if (!settings.value.opencode_model && opts.length) {
    settings.value.opencode_model = opts[0]
  }
}

async function save() {
  saving.value = true
  try {
    settings.value = await saveSettingsForm(settings.value, updateSettings, getScheduleClockState)
    ElMessage.success('保存成功')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function doTestEmail() {
  testingEmail.value = true
  emailTestResult.value = null
  try {
    const { normalizedSettings, testResult } = await saveThenRunTest(
      settings.value,
      updateSettings,
      testEmail,
      getScheduleClockState,
    )
    settings.value = normalizedSettings
    const { data } = testResult
    emailTestResult.value = data
    if (data.ok) ElMessage.success(data.message)
    else ElMessage.error(data.message)
  } catch (e) {
    emailTestResult.value = { ok: false, message: e.message || '请求失败' }
    ElMessage.error('测试请求失败')
  } finally {
    testingEmail.value = false
  }
}

async function doTestWechat() {
  testingWechat.value = true
  wechatTestResult.value = null
  try {
    const { normalizedSettings, testResult } = await saveThenRunTest(
      settings.value,
      updateSettings,
      testWechat,
      getScheduleClockState,
    )
    settings.value = normalizedSettings
    const { data } = testResult
    wechatTestResult.value = data
    if (data.ok) ElMessage.success(data.message)
    else ElMessage.error(data.message)
  } catch (e) {
    wechatTestResult.value = { ok: false, message: e.message || '请求失败' }
    ElMessage.error('测试请求失败')
  } finally {
    testingWechat.value = false
  }
}
</script>

<style scoped>
.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  max-width: 960px;
}

.settings-card {
  background: var(--bg-white);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px;
  border-bottom: 1px solid var(--border-light);
}
.card-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.card-header-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}
.card-header-desc {
  font-size: 12px;
  color: var(--text-secondary);
}

.card-body {
  padding: 20px;
}

.settings-footer {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border-light);
  display: flex;
  justify-content: flex-end;
  max-width: 960px;
}

.form-group {
  margin-bottom: 18px;
}
.form-group:last-child {
  margin-bottom: 0;
}
.form-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.label-icon {
  font-size: 14px;
  color: var(--text-placeholder);
}

.field-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.legacy-collapse {
  margin-top: 16px;
  padding: 12px 14px;
  background: var(--bg-color, #f8f9fa);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.legacy-collapse summary {
  cursor: pointer;
  font-weight: 500;
  color: var(--text-secondary);
  user-select: none;
}
.legacy-collapse[open] summary {
  margin-bottom: 12px;
}
.legacy-grid .form-group {
  margin-bottom: 12px;
}

.form-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}
.test-result {
  font-size: 12px;
}
.test-result.ok {
  color: var(--accent-green, #67c23a);
}
.test-result.fail {
  color: var(--el-color-danger, #f56c6c);
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
