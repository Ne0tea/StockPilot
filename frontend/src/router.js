import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Stocks from './views/Stocks.vue'
import Portfolio from './views/Portfolio.vue'
import Settings from './views/Settings.vue'
import Reports from './views/Reports.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/stocks', component: Stocks },
    { path: '/reports', component: Reports },
    { path: '/portfolio', component: Portfolio },
    { path: '/settings', component: Settings },
  ]
})
