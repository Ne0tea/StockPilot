<template>
  <div class="dashboard">
    <PageHeader title="仪表盘" subtitle="您的投资概览" />

    <SummaryCards :cards="summaryCards" />

    <div class="dashboard-grid">
      <SectionCard title="自选股" :badge="`共 ${dashboard.watchlist_signals?.length || 0} 只`" dot-color="var(--accent-orange)">
        <el-table :data="dashboard.watchlist_signals" :header-cell-style="tableHeaderStyle">
          <el-table-column prop="name" label="股票" min-width="100">
            <template #default="{row}">
              <span class="stock-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="score_total" label="评分" min-width="90">
            <template #default="{row}">
              <span class="score-badge" :class="scoreClass(row.score_total)">{{ row.score_total }}/10</span>
            </template>
          </el-table-column>
          <el-table-column prop="recommendation" label="评级" min-width="100">
            <template #default="{row}">
              <span class="action-tag" :class="recTagClass(row.recommendation)">{{ row.recommendation || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="price" label="报告价格" min-width="180">
            <template #default="{row}">
              <ReportPriceCell :row="row" @analyze="goAnalyze(row.code)" />
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="总盈利折线图" dot-color="#00A86B">
        <div class="chart-wrapper">
          <ProfitChart :history="profitHistory" />
        </div>
      </SectionCard>

      <SectionCard title="持仓股操作建议" :badge="`共 ${dashboard.holding_recommendations?.length || 0} 只`" dot-color="var(--primary)">
        <el-table :data="dashboard.holding_recommendations" :header-cell-style="tableHeaderStyle">
          <el-table-column prop="name" label="股票" min-width="100">
            <template #default="{row}">
              <span class="stock-name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="score_total" label="评分" min-width="90">
            <template #default="{row}">
              <span class="score-badge" :class="scoreClass(row.score_total)">{{ row.score_total }}/10</span>
            </template>
          </el-table-column>
          <el-table-column prop="action" label="操作" min-width="90">
            <template #default="{row}">
              <span class="action-tag" :class="actionTagClass(row.action)">{{ row.action || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="cost_price" label="成本价" min-width="100">
            <template #default="{row}">
              <span class="price-neutral">{{ row.cost_price !== null && row.cost_price !== undefined ? `¥${Number(row.cost_price).toFixed(2)}` : '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="target_price" label="目标价" min-width="100">
            <template #default="{row}">
              <span class="price-up">{{ row.target_price ? `¥${row.target_price}` : '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="stop_loss_price" label="止损价" min-width="100">
            <template #default="{row}">
              <span class="price-down">{{ row.stop_loss_price ? `¥${row.stop_loss_price}` : '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="持仓成本占比" dot-color="var(--accent-blue)">
        <div class="chart-wrapper">
          <CostPieChart :items="dashboard.holding_recommendations" />
        </div>
      </SectionCard>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getDashboard, getProfitHistory } from '../api'
import { Suitcase, Money, Star } from '@element-plus/icons-vue'
import PageHeader from '../components/PageHeader.vue'
import SummaryCards from '../components/SummaryCards.vue'
import SectionCard from '../components/SectionCard.vue'
import CostPieChart from '../components/CostPieChart.vue'
import ProfitChart from '../components/ProfitChart.vue'
import ReportPriceCell from '../components/ReportPriceCell.vue'

const router = useRouter()

const tableHeaderStyle = { background: '#F8F9FA', color: '#999', fontSize: '12px', fontWeight: '600' }

const dashboard = ref({ holding_recommendations: [], watchlist_signals: [], portfolio_summary: {} })
const profitHistory = ref([])

const summaryCards = computed(() => [
  {
    icon: Suitcase,
    iconBg: 'var(--accent-orange-light)',
    iconColor: 'var(--accent-orange)',
    value: dashboard.value.portfolio_summary?.total_positions || 0,
    label: '持仓数量',
  },
  {
    icon: Money,
    iconBg: 'var(--color-down-light)',
    iconColor: 'var(--color-down)',
    value: `¥${formatMoney(dashboard.value.portfolio_summary?.total_cost)}`,
    label: '持仓总成本',
  },
  {
    icon: Star,
    iconBg: '#FFF8E6',
    iconColor: '#E6A23C',
    value: dashboard.value.watchlist_signals?.length || 0,
    label: '自选股数',
  },
])

onMounted(async () => {
  const [dashRes, profitRes] = await Promise.all([getDashboard(), getProfitHistory()])
  dashboard.value = dashRes.data || { holding_recommendations: [], watchlist_signals: [], portfolio_summary: {} }
  profitHistory.value = profitRes.data || []
})

function goAnalyze(stockCode) {
  if (!stockCode) return
  router.push({ path: '/stocks', query: { highlight: stockCode } })
}

function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '0.00'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function scoreClass(score) {
  if (score >= 7) return 'score-high'
  if (score >= 4) return 'score-mid'
  return 'score-low'
}

function actionTagClass(action) {
  if (['买入', '加仓'].includes(action)) return 'tag-up'
  if (['卖出', '减仓'].includes(action)) return 'tag-down'
  return 'tag-neutral'
}

function recTagClass(rec) {
  if (['强烈推荐', '推荐买入'].includes(rec)) return 'tag-up'
  if (['谨慎操作', '建议回避'].includes(rec)) return 'tag-down'
  return 'tag-neutral'
}
</script>

<style scoped>
.dashboard-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 20px;
  width: 100%;
}

.chart-wrapper {
  padding: 16px 20px;
}

/* ── Table Cell Styles ── */
.stock-name {
  font-weight: 600;
  color: var(--text-primary);
}
.score-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
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
.reason-text {
  color: var(--text-secondary);
  font-size: 13px;
}
.price-up {
  color: var(--color-up);
  font-weight: 600;
}
.price-down {
  color: var(--color-down);
  font-weight: 600;
}
.price-flat {
  color: var(--text-secondary);
}
.price-neutral {
  color: var(--text-primary);
  font-weight: 500;
}
.date-text {
  color: var(--text-secondary);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
</style>
