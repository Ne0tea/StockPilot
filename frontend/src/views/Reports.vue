<template>
  <div class="reports-page">
    <PageHeader title="分析报告" subtitle="查看和管理股票分析报告">
      <template #actions>
        <el-date-picker
          v-model="selectedDateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          unlink-panels
          class="date-range-picker"
          @change="syncRouteQuery"
          @clear="syncRouteQuery"
        />
        <el-select v-model="selectedCode" clearable placeholder="选择股票" filterable @change="syncRouteQuery" @clear="syncRouteQuery" style="width:240px">
          <el-option v-for="s in stocks" :key="s.stock_code" :label="`${s.name} (${s.stock_code})`" :value="s.stock_code" />
        </el-select>
        <el-button :loading="refreshing" @click="refreshReports" class="btn-outline">
          <el-icon style="margin-right:4px"><RefreshRight /></el-icon>
          重新生成
        </el-button>
      </template>
    </PageHeader>

    <SummaryCards :cards="summaryCardsData" />

    <!-- Report List -->
    <SectionCard>
      <el-table
        v-if="reports.length"
        :data="reports"
        :header-cell-style="tableHeaderStyle"
        @row-click="viewReport"
        row-class-name="clickable-row"
      >
        <el-table-column label="评分" width="80">
          <template #default="{row}">
            <span class="score-circle" :class="scoreCircleClass(row.score_total)">
              {{ formatScore(row.score_total) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="stock_name" label="股票名称" min-width="140">
          <template #default="{row}">
            <span class="stock-name">{{ row.stock_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="date" label="数据日期" width="120">
          <template #default="{row}">
            <span class="date-text">{{ row.date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="recommendation" label="投资结论" width="120">
          <template #default="{row}">
            <span class="action-tag" :class="recTagClass(row.recommendation)">{{ row.recommendation || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="建仓价位" min-width="110">
          <template #default="{row}">
            <span class="price-neutral">{{ formatPrice(row.entry_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="目标位" min-width="110">
          <template #default="{row}">
            <span class="price-up">{{ formatPrice(row.target_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="止损价位" min-width="110">
          <template #default="{row}">
            <span class="price-down">{{ formatPrice(row.stop_loss_price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{row}">
            <button class="icon-btn icon-btn-primary" title="查看报告" @click.stop="viewReport(row)">
              <el-icon><View /></el-icon>
            </button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="empty-state">
        <p>暂无报告数据</p>
      </div>
    </SectionCard>

    <!-- HTML Report Dialog -->
    <el-dialog v-model="dialogVisible" title="分析报告" width="96%" top="2vh" destroy-on-close class="report-view-dialog">
      <iframe v-if="reportUrl" :src="reportUrl" class="report-frame" />
    </el-dialog>

    <!-- Action Dialog (HTML missing) -->
    <el-dialog v-model="actionDialogVisible" title="HTML 报告缺失" width="420px" destroy-on-close>
      <div class="missing-info">
        <p>该报告目前只有 Markdown，没有 HTML 报告。</p>
        <p class="hint">你可以重新进行分析，或者直接查看 Markdown 原文预览。</p>
      </div>
      <template #footer>
        <el-button @click="actionDialogVisible = false">取消</el-button>
        <el-button @click="previewMarkdown" class="btn-outline">Markdown 预览</el-button>
        <el-button type="primary" :loading="reanalyzing" @click="reanalyzeReport">重新分析</el-button>
      </template>
    </el-dialog>

    <!-- Markdown Preview Dialog -->
    <el-dialog v-model="markdownDialogVisible" title="Markdown 预览" width="90%" top="5vh" destroy-on-close>
      <pre class="markdown-preview">{{ markdownPreview }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getWatchlist, getReports, rescanReports, startInteractiveAnalysisWithMode } from '../api'
import { buildReportRouteQuery, filterReportsByCodeAndDateRange } from '../utils/reportFilters'
import { buildReportUrl } from '../utils/reportHelpers'
import { RefreshRight, Document, TrendCharts, Calendar, Star, View } from '@element-plus/icons-vue'
import PageHeader from '../components/PageHeader.vue'
import SummaryCards from '../components/SummaryCards.vue'
import SectionCard from '../components/SectionCard.vue'

const tableHeaderStyle = { background: '#F8F9FA', color: '#999', fontSize: '12px', fontWeight: '600' }

const route = useRoute()
const router = useRouter()
const stocks = ref([])
const selectedCode = ref('')
const selectedDateRange = ref([])
const reports = ref([])
const dialogVisible = ref(false)
const reportUrl = ref('')
const refreshing = ref(false)
const actionDialogVisible = ref(false)
const markdownDialogVisible = ref(false)
const markdownPreview = ref('')
const pendingReport = ref(null)
const reanalyzing = ref(false)

const avgScore = computed(() => {
  if (!reports.value.length) return '0.0'
  const sum = reports.value.reduce((acc, r) => acc + (Number(r.score_total) || 0), 0)
  return (sum / reports.value.length).toFixed(1)
})

const latestDate = computed(() => {
  if (!reports.value.length) return '--'
  return reports.value[0]?.date || '--'
})

const recommendCount = computed(() => {
  return reports.value.filter(r => r.recommendation && r.recommendation.includes('推荐')).length
})

const summaryCardsData = computed(() => [
  {
    icon: Document,
    iconBg: 'var(--accent-blue-light)',
    iconColor: 'var(--accent-blue)',
    value: reports.value.length,
    label: '报告总数',
  },
  {
    icon: TrendCharts,
    iconBg: 'var(--accent-orange-light)',
    iconColor: 'var(--accent-orange)',
    value: avgScore.value,
    label: '平均评分',
  },
  {
    icon: Calendar,
    iconBg: '#F4F4F5',
    iconColor: '#909399',
    value: latestDate.value,
    label: '最新报告',
  },
  {
    icon: Star,
    iconBg: 'var(--color-up-light)',
    iconColor: 'var(--color-up)',
    value: recommendCount.value,
    label: '强烈推荐',
  },
])

onMounted(async () => {
  stocks.value = (await getWatchlist()).data
  if (route.query.code) {
    selectedCode.value = route.query.code
  }
  if (route.query.start && route.query.end) {
    selectedDateRange.value = [route.query.start, route.query.end]
  }
  await loadReports()
})

watch(
  () => [route.query.code || '', route.query.start || '', route.query.end || ''],
  async ([code, start, end]) => {
    selectedCode.value = code
    selectedDateRange.value = start && end ? [start, end] : []
    await loadReports()
  },
)

async function loadReports() {
  const { data } = await getReports()
  reports.value = filterReportsByCodeAndDateRange(data || [], selectedCode.value, selectedDateRange.value)
}

async function syncRouteQuery() {
  await router.replace({ path: '/reports', query: buildReportRouteQuery({ selectedCode: selectedCode.value, dateRange: selectedDateRange.value }) })
}

async function refreshReports() {
  refreshing.value = true
  try {
    const { data } = await rescanReports(selectedCode.value)
    await loadReports()
    const rebuilt = Number(data?.parsed_ok || 0)
    const total = Number(data?.md_total || 0)
    const failed = Number(data?.parsed_failed || 0)
    ElMessage.success(
      selectedCode.value
        ? `已重建当前股票 ${rebuilt}/${total} 份 Markdown 报告${failed ? `，失败 ${failed} 份` : ''}`
        : `已重建 ${rebuilt}/${total} 份 Markdown 报告${failed ? `，失败 ${failed} 份` : ''}`,
    )
  } finally {
    refreshing.value = false
  }
}

function viewReport(row) {
  if (row.html_status === 'ready' && row.report_file_path) {
    reportUrl.value = buildReportUrl(row.report_file_path)
    dialogVisible.value = true
    return
  }

  pendingReport.value = row
  actionDialogVisible.value = true
}

function previewMarkdown() {
  markdownPreview.value = pendingReport.value?.markdown_content || '未找到 Markdown 内容'
  markdownDialogVisible.value = true
  actionDialogVisible.value = false
}

async function reanalyzeReport() {
  if (!pendingReport.value?.stock_code) return
  reanalyzing.value = true
  try {
    await startInteractiveAnalysisWithMode(pendingReport.value.stock_code, true)
    ElMessage.success(`已开始一键重新分析 ${pendingReport.value.stock_name || pendingReport.value.stock_code}`)
    actionDialogVisible.value = false
  } finally {
    reanalyzing.value = false
  }
}

function formatScore(value) {
  if (value === null || value === undefined || value === '') return '--'
  return Number(value).toFixed(1)
}

function formatPrice(value) {
  if (value === null || value === undefined || value === '') return '--'
  return `${Number(value).toFixed(2)}`
}

function scoreCircleClass(score) {
  const num = Number(score)
  if (num >= 7) return 'score-high'
  if (num >= 4) return 'score-mid'
  return 'score-low'
}

function recTagClass(rec) {
  if (['强烈推荐', '推荐买入'].includes(rec)) return 'tag-up'
  if (['谨慎操作', '建议回避'].includes(rec)) return 'tag-down'
  return 'tag-neutral'
}
</script>

<style scoped>
.date-range-picker {
  width: 280px;
}

/* ── Table Cell Styles ── */
.stock-name {
  font-weight: 600;
  color: var(--text-primary);
}
.date-text {
  color: var(--text-secondary);
  font-size: 13px;
}
.score-circle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 700;
}
.score-high {
  background: var(--color-up-light);
  color: var(--color-up);
}
.score-mid {
  background: var(--accent-orange-light);
  color: var(--accent-orange);
}
.score-low {
  background: var(--color-down-light);
  color: var(--color-down);
}
.action-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}
.tag-up {
  background: var(--color-up-light);
  color: var(--color-up);
}
.tag-down {
  background: var(--color-down-light);
  color: var(--color-down);
}
.tag-neutral {
  background: #F4F4F5;
  color: #909399;
}
.price-up {
  color: var(--color-up);
  font-weight: 600;
}
.price-down {
  color: var(--color-down);
  font-weight: 600;
}
.price-neutral {
  color: var(--text-primary);
}

/* ── Icon Button ── */
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
.icon-btn:hover {
  transform: scale(1.1);
}
.icon-btn-primary:hover {
  background: var(--accent-blue-light);
  color: var(--accent-blue);
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

/* ── Empty State ── */
.empty-state {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-placeholder);
  font-size: 14px;
}

/* ── Markdown Preview ── */
.markdown-preview {
  margin: 0;
  max-height: 70vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  background: #F8F9FA;
  padding: 16px;
  border-radius: var(--radius-sm);
}

/* ── Missing Info ── */
.missing-info p {
  margin: 0 0 8px;
  color: var(--text-primary);
}
.missing-info .hint {
  color: var(--text-secondary);
  font-size: 13px;
}

@media (max-width: 768px) {
  .date-range-picker {
    width: 100%;
  }
}
</style>
