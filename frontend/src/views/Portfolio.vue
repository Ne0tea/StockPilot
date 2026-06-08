<template>
  <div class="portfolio-page">
    <PageHeader title="持仓管理" subtitle="管理您的持仓和交易记录">
      <template #actions>
        <el-button type="primary" @click="drawerVisible = true">
          <el-icon style="margin-right:4px"><Plus /></el-icon>
          录入交易
        </el-button>
      </template>
    </PageHeader>

    <SummaryCards :cards="summaryCardsData" />

    <div class="portfolio-grid">
      <SectionCard title="当前持仓" :badge="`${holdingPositions.length} 条`" dot-color="var(--primary)">
        <el-table :data="holdingPositions" :header-cell-style="tableHeaderStyle">
          <el-table-column prop="stock_name" label="股票" min-width="120">
            <template #default="{row}">
              <span class="stock-name">{{ row.stock_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="stock_code" label="代码" width="110" />
          <el-table-column prop="shares" label="持股数" width="100" />
          <el-table-column label="持仓成本" width="120">
            <template #default="{row}"><span class="price-neutral">¥{{ formatMoney(row.holding_cost) }}</span></template>
          </el-table-column>
          <el-table-column label="报告价格" min-width="180">
            <template #default="{row}">
              <ReportPriceCell :row="row" @analyze="goAnalyze(row.stock_code)" />
            </template>
          </el-table-column>
          <el-table-column prop="buy_date" label="买入日期" width="120" />
          <el-table-column label="专项分析" width="110">
            <template #default="{row}">
              <el-button size="small" type="primary" plain @click="openAgentDialog(row)">
                🤖 分析
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="历史已平仓" :badge="`${closedPositions.length} 条`" dot-color="var(--accent-orange)">
        <el-table :data="closedPositions" :header-cell-style="tableHeaderStyle">
          <el-table-column prop="stock_name" label="股票" min-width="120">
            <template #default="{row}">
              <span class="stock-name">{{ row.stock_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="stock_code" label="代码" width="110" />
          <el-table-column prop="shares" label="成交股数" width="100" />
          <el-table-column prop="buy_date" label="买入日期" width="120" />
          <el-table-column prop="close_date" label="平仓日期" width="120" />
          <el-table-column label="历史利润" width="120">
            <template #default="{row}">
              <span :class="profitClass(row.realized_profit)">¥{{ formatMoney(row.realized_profit) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="报告价格" min-width="180">
            <template #default="{row}">
              <ReportPriceCell :row="row" @analyze="goAnalyze(row.stock_code)" />
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>
    </div>

    <!-- Trade Entry Drawer -->
    <el-drawer v-model="drawerVisible" title="录入交易" direction="rtl" size="420px" destroy-on-close>
      <el-form label-position="top" class="trade-form">
        <div class="form-row">
          <el-form-item label="股票代码">
            <el-input v-model="trade.stock_code" placeholder="输入代码" @blur="autofillTrade('stock_code')" />
          </el-form-item>
          <el-form-item label="股票名称">
            <el-input v-model="trade.stock_name" placeholder="输入名称" @blur="autofillTrade('name')" />
          </el-form-item>
        </div>
        <el-form-item label="交易方向">
          <el-radio-group v-model="trade.action" class="action-radio">
            <el-radio-button value="buy">
              <span style="color: var(--color-up); font-weight: 600;">买入</span>
            </el-radio-button>
            <el-radio-button value="sell">
              <span style="color: var(--color-down); font-weight: 600;">卖出</span>
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <div class="form-row">
          <el-form-item label="价格">
            <el-input-number v-model="trade.price" :precision="2" :min="0" placeholder="价格" style="width:100%" />
          </el-form-item>
          <el-form-item label="数量">
            <el-input-number v-model="trade.shares" :min="100" :step="100" placeholder="数量" style="width:100%" />
          </el-form-item>
        </div>
        <el-form-item label="交易日期">
          <el-date-picker v-model="trade.date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width:100%" />
        </el-form-item>
        <div class="drawer-footer">
          <el-button @click="drawerVisible = false">取消</el-button>
          <el-button type="primary" @click="submitTrade">提交</el-button>
        </div>
      </el-form>
    </el-drawer>

    <AgentChatDialog v-model="agentDialogVisible" :stock="agentDialogStock" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getPortfolio, recordTrade, resolveStock, checkWatchlist, addStock, removeStock } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Suitcase, Document } from '@element-plus/icons-vue'
import { applyResolvedStock, buildLookupFailureMessage, buildLookupQuery } from '../utils/stockLookup'
import PageHeader from '../components/PageHeader.vue'
import SummaryCards from '../components/SummaryCards.vue'
import SectionCard from '../components/SectionCard.vue'
import ReportPriceCell from '../components/ReportPriceCell.vue'
import AgentChatDialog from '../components/AgentChatDialog.vue'

const router = useRouter()

const tableHeaderStyle = { background: '#F8F9FA', color: '#999', fontSize: '12px', fontWeight: '600' }

const holdingPositions = ref([])
const closedPositions = ref([])
const trade = ref({ stock_code: '', stock_name: '', action: 'buy', price: 0, shares: 100, date: '' })
const drawerVisible = ref(false)

const agentDialogVisible = ref(false)
const agentDialogStock = ref(null)
function openAgentDialog(row) {
  agentDialogStock.value = {
    stock_code: row.stock_code,
    stock_name: row.stock_name,
    is_held: true,
  }
  agentDialogVisible.value = true
}

const summaryCardsData = computed(() => [
  {
    icon: Suitcase,
    iconBg: 'var(--accent-orange-light)',
    iconColor: 'var(--accent-orange)',
    value: holdingPositions.value.length,
    label: '当前持仓',
  },
  {
    icon: Document,
    iconBg: '#F4F4F5',
    iconColor: '#909399',
    value: closedPositions.value.length,
    label: '历史已平仓',
  },
])

onMounted(loadPortfolio)

async function submitTrade() {
  if (!trade.value.stock_code && !trade.value.stock_name) {
    ElMessage.warning('请填写完整信息')
    return
  }
  const lookupField = trade.value.stock_code ? 'stock_code' : 'name'
  const resolved = await ensureTradeResolved()
  if (!resolved || !trade.value.stock_code || !trade.value.stock_name) {
    ElMessage.error(buildLookupFailureMessage(trade.value, lookupField))
    return
  }
  if (!trade.value.date) return ElMessage.warning('请填写完整信息')
  const tradeData = { ...trade.value }
  await recordTrade(tradeData)
  await loadPortfolio()
  trade.value = { stock_code: '', stock_name: '', action: 'buy', price: 0, shares: 100, date: '' }
  drawerVisible.value = false
  ElMessage.success('交易已记录')

  if (tradeData.action === 'buy') {
    await promptAddToWatchlist(tradeData.stock_code, tradeData.stock_name)
  } else if (tradeData.action === 'sell') {
    await promptRemoveFromWatchlist(tradeData.stock_code, tradeData.stock_name)
  }
}

async function promptAddToWatchlist(stockCode, stockName) {
  try {
    const { data } = await checkWatchlist(stockCode)
    if (data.in_watchlist) return
    await ElMessageBox.confirm(
      `${stockName}（${stockCode}）不在自选股中，是否同时加入自选股？`,
      '加入自选股',
      { confirmButtonText: '加入', cancelButtonText: '跳过', type: 'info' },
    )
    await addStock({ stock_code: stockCode, name: stockName, market: 'sh' })
    ElMessage.success('已加入自选股')
  } catch { /* user cancelled */ }
}

async function promptRemoveFromWatchlist(stockCode, stockName) {
  const stillHeld = holdingPositions.value.some(p => p.stock_code === stockCode)
  if (stillHeld) return
  try {
    const { data } = await checkWatchlist(stockCode)
    if (!data.in_watchlist || !data.id) return
    await ElMessageBox.confirm(
      `${stockName}（${stockCode}）已清仓，是否从自选股中移除？`,
      '移除自选股',
      { confirmButtonText: '移除', cancelButtonText: '保留', type: 'warning' },
    )
    await removeStock(data.id)
    ElMessage.success('已从自选股中移除')
  } catch { /* user cancelled */ }
}

async function loadPortfolio() {
  const { data } = await getPortfolio()
  holdingPositions.value = data.holding_positions || []
  closedPositions.value = data.closed_positions || []
}

async function autofillTrade(field) {
  const query = buildLookupQuery(trade.value, field)
  if (!query) {
    return false
  }
  try {
    const { data } = await resolveStock(field, query)
    return applyResolvedStock(trade.value, data, field)
  } catch {
    return false
  }
}

async function ensureTradeResolved() {
  if (trade.value.stock_code && !trade.value.stock_name) {
    await autofillTrade('stock_code')
    return Boolean(trade.value.stock_code && trade.value.stock_name)
  }
  if (trade.value.stock_name && !trade.value.stock_code) {
    await autofillTrade('name')
    return Boolean(trade.value.stock_code && trade.value.stock_name)
  }
  return Boolean(trade.value.stock_code && trade.value.stock_name)
}

function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '--'
  return Number(value).toFixed(2)
}

function goAnalyze(stockCode) {
  if (!stockCode) return
  router.push({ path: '/stocks', query: { highlight: stockCode } })
}

function profitClass(value) {
  if (value === null || value === undefined || value === '') return ''
  const num = Number(value)
  if (num > 0) return 'price-up'
  if (num < 0) return 'price-down'
  return 'price-flat'
}
</script>

<style scoped>
/* ── Portfolio Grid ── */
.portfolio-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  width: 100%;
}

/* ── Table Cell Styles ── */
.stock-name {
  font-weight: 600;
  color: var(--text-primary);
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
}

/* ── Drawer Form ── */
.trade-form {
  padding-top: 8px;
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.action-radio {
  width: 100%;
}
.action-radio .el-radio-button {
  flex: 1;
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}

@media (max-width: 1200px) {
  .portfolio-grid {
    grid-template-columns: 1fr;
  }
}
</style>
