<script setup>
import { computed } from "vue";

import { useTradingStore } from "../stores/trading";

const store = useTradingStore();
const latestEquity = computed(() => store.cryptoEquityCurve.at(-1) || null);
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Paper Account</span>
          <h3>加密货币模拟账户</h3>
        </div>
        <button class="ghost-button" @click="store.refreshOverview">刷新账户</button>
      </div>

      <div class="metric-grid">
        <div>
          <span>初始本金</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.initial_cash || 0) }}</strong>
        </div>
        <div>
          <span>可用 USDT</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.cash || 0) }}</strong>
        </div>
        <div>
          <span>持仓市值</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.market_value || 0) }}</strong>
        </div>
        <div>
          <span>总权益</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.equity || 0) }}</strong>
        </div>
        <div>
          <span>累计收益</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.total_profit || 0) }}</strong>
        </div>
        <div>
          <span>收益率</span>
          <strong>{{ store.formatPercent(store.cryptoAccount?.total_return_percent || 0) }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Positions</span>
          <h3>持仓</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>交易对</th>
              <th>数量</th>
              <th>可用</th>
              <th>均价</th>
              <th>现价</th>
              <th>市值</th>
              <th>浮动收益</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in store.cryptoPositions" :key="item.symbol">
              <td>{{ item.symbol }}</td>
              <td>{{ item.quantity }}</td>
              <td>{{ item.available }}</td>
              <td>{{ store.formatPrice(item.avg_price) }}</td>
              <td>{{ store.formatPrice(item.current_price) }}</td>
              <td>{{ store.formatCurrency(item.market_value) }}</td>
              <td :class="Number(item.unrealized_pnl || 0) >= 0 ? 'number-up' : 'number-down'">
                {{ store.formatCurrency(item.unrealized_pnl) }}
              </td>
            </tr>
            <tr v-if="!store.cryptoPositions.length">
              <td colspan="7">暂无持仓。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Equity Curve</span>
          <h3>资金曲线</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ latestEquity?.timestamp || "暂无" }}</span>
      </div>
      <div class="metric-grid">
        <div>
          <span>最新权益</span>
          <strong>{{ store.formatCurrency(latestEquity?.equity || 0) }}</strong>
        </div>
        <div>
          <span>最新现金</span>
          <strong>{{ store.formatCurrency(latestEquity?.cash || 0) }}</strong>
        </div>
        <div>
          <span>曲线点数</span>
          <strong>{{ store.cryptoEquityCurve.length }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Logs</span>
          <h3>模拟实盘日志</h3>
        </div>
      </div>
      <div class="timeline-list">
        <div v-for="item in store.cryptoLogs" :key="`${item.timestamp}-${item.event}`" class="timeline-item">
          <div>
            <strong>{{ item.event }}</strong>
            <p>{{ item.message }}</p>
          </div>
          <span class="timeline-item__side">{{ item.timestamp }}</span>
        </div>
        <div v-if="!store.cryptoLogs.length" class="timeline-item">
          <div>
            <strong>暂无日志</strong>
            <p>提交模拟订单后，这里会记录撮合、拒单和撤单事件。</p>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>
