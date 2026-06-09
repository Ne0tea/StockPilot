import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const cfg = error.config || {}
    const isNetwork = !error.response
    const isRetriableStatus = [502, 503, 504].includes(error.response?.status)
    const method = (cfg.method || 'get').toLowerCase()
    const idempotent = method === 'get'
    if (!cfg.__retried && idempotent && (isNetwork || isRetriableStatus)) {
      cfg.__retried = true
      await new Promise((r) => setTimeout(r, 800))
      return api.request(cfg)
    }
    return Promise.reject(error)
  },
)

export { api }

export const getWatchlist = () => api.get('/watchlist')
export const getWatchlistOverview = () => api.get('/watchlist/overview')
export const addStock = (data) => api.post('/watchlist', data)
export const removeStock = (id) => api.delete(`/watchlist/${id}`)
export const checkWatchlist = (stockCode) => api.get(`/watchlist/check?stock_code=${encodeURIComponent(stockCode)}`)
export const resetWatchlist = () => api.post('/watchlist/reset')
export const clearAllAnalysisData = () => api.post('/watchlist/analysis/clear', null, { timeout: 120000 })
export const clearStockAnalysisData = (code) =>
  api.delete(`/watchlist/${encodeURIComponent(code)}/analysis`, { timeout: 60000 })
export const getDashboard = () => api.get('/dashboard', { timeout: 60000 })
export const getDeliveryRecords = () => api.get('/dashboard/delivery-records')
export const getProfitHistory = () => api.get('/portfolio/profit-history')
export const getReports = (code, limit = 30) =>
  code ? api.get(`/reports/${code}?limit=${limit}`) : api.get(`/reports?limit=${limit}`)
export const rescanReports = (code = '') =>
  api.post(`/reports/rescan${code ? `?code=${encodeURIComponent(code)}` : ''}`, null, { timeout: 120000 })
export const getLatestReport = (code) => api.get(`/reports/${code}/latest`)
export const getAnalysisStatus = (code) => api.get(`/analyze/${code}/status`)
export const getTodayLog = (code) => api.get(`/analyze/${code}/log/today`)
export const getPortfolio = () => api.get('/portfolio', { timeout: 60000 })
export const recordTrade = (data) => api.post('/portfolio/trade', data)
export const getTrades = (code) =>
  api.get(`/portfolio/trades${code ? `?stock_code=${encodeURIComponent(code)}` : ''}`)
export const getSettings = () => api.get('/settings')
export const updateSettings = (data) => api.put('/settings', data)
export const testEmail = () => api.post('/settings/test-email', null, { timeout: 30000 })
export const testWechat = () => api.post('/settings/test-wechat', null, { timeout: 30000 })
export const resolveStock = (field, q) =>
  api.get(`/stocks/resolve?field=${encodeURIComponent(field)}&q=${encodeURIComponent(q)}`)
export const getNotifications = () => api.get('/dashboard/notifications')

export const startInteractiveAnalysisWithMode = (code, auto_respond = false) =>
  api.post(`/analyze/${code}/interactive`, { auto_respond })

export const respondToAnalysis = (code, response) =>
  api.post(`/analyze/${code}/respond`, { response })

export const cancelAnalysis = (code) => api.delete(`/analyze/${code}/session`)

export const getAgentSkills = () => api.get('/agent/skills')
export const startAgentChat = (stock_code, skill) =>
  api.post('/agent/chat/start', { stock_code, skill }, { timeout: 180000 })
export const startAgentChatStream = (stock_code, skill) =>
  api.post('/agent/chat/start-stream', { stock_code, skill }, { timeout: 30000 })
export const sendAgentMessage = (session_id, skill, message) =>
  api.post('/agent/chat/message', { session_id, skill, message }, { timeout: 180000 })
export const cancelAgentStream = (session_id) =>
  api.delete(`/agent/chat/${encodeURIComponent(session_id)}`)
export const endAgentChat = (session_id) =>
  api.delete(`/agent/chat/${encodeURIComponent(session_id)}`)
