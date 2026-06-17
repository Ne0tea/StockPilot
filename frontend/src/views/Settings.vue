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

      <!-- Daily Report Claude Config -->
      <div class="settings-card">
        <div class="card-header">
          <div class="card-header-icon" style="background: var(--accent-orange-light); color: var(--accent-orange);">
            <el-icon :size="20"><MagicStick /></el-icon>
          </div>
          <div>
            <h3 class="card-header-title">每日报告LLM配置</h3>
            <p class="card-header-desc">保存后自动重建 backend/reports/.claude/settings.json</p>
          </div>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Cpu /></el-icon>
              model
            </label>
            <el-input v-model="settings.claude_model" placeholder="deepseek-v4-pro[1m]" />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Lock /></el-icon>
              ANTHROPIC_API_KEY
            </label>
            <el-input v-model="settings.claude_api_key" type="password" show-password placeholder="sk-..." />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Lock /></el-icon>
              ANTHROPIC_AUTH_TOKEN
            </label>
            <el-input v-model="settings.claude_auth_token" type="password" show-password placeholder="sk-..." />
          </div>
          <div class="form-group">
            <label class="form-label">
              <el-icon class="label-icon"><Link /></el-icon>
              ANTHROPIC_BASE_URL
            </label>
            <el-input v-model="settings.claude_base_url" placeholder="https://your-gateway.example.com" />
          </div>
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
import { ref, onMounted } from 'vue'
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

onMounted(async () => { settings.value = (await getSettings()).data })

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
