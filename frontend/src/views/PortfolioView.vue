<script setup>
import { computed, onMounted, ref } from "vue";

import BacktestChart from "../components/BacktestChart.vue";
import { usePortfolioStore } from "../stores/portfolio";
import { useTradingStore } from "../stores/trading";

const portfolio = usePortfolioStore();
const trading = useTradingStore();
const groupBy = ref("symbol");

const groups = computed(() => (groupBy.value === "symbol" ? portfolio.bySymbol : portfolio.byStrategy));
const equityForChart = computed(() =>
  portfolio.equityCurve.map((item) => ({
    timestamp: item.label || item.timestamp,
    equity: item.equity,
  })),
);
const drawdownForChart = computed(() =>
  portfolio.equityCurve.map((item) => ({
    timestamp: item.label || item.timestamp,
    drawdown: Number(item.drawdown_pct || 0) / 100,
  })),
);

function formatTime(timestamp) {
  if (!timestamp) return "-";
  return new Date(Number(timestamp) * 1000).toLocaleString("zh-CN", { hour12: false });
}

function formatMinutes(value) {
  if (value === null || value === undefined) return "-";
  if (value < 60) return `${Number(value).toFixed(0)} 分钟`;
  return `${(Number(value) / 60).toFixed(1)} 小时`;
}

async function fetchAnalytics() {
  await portfolio.fetchAnalytics();
}

onMounted(fetchAnalytics);
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Portfolio Analytics</span>
          <h3>投资组合收益</h3>
        </div>
        <div class="button-row">
          <select v-model="portfolio.mode" class="compact-select" @change="fetchAnalytics">
            <option value="demo">模拟盘</option>
            <option value="shadow">影子交易</option>
            <option value="live">本地交易记录</option>
          </select>
          <select v-model="portfolio.range" class="compact-select" @change="fetchAnalytics">
            <option value="7d">7 天</option>
            <option value="30d">30 天</option>
            <option value="90d">90 天</option>
            <option value="all">全部</option>
          </select>
          <button class="ghost-button" :disabled="portfolio.loading" @click="fetchAnalytics">
            {{ portfolio.loading ? "加载中" : "刷新" }}
          </button>
        </div>
      </div>
      <p class="helper-text">组合收益来自本地 SQLite 中的模拟交易、持仓和影子交易记录，不会触发任何真实下单。</p>

      <div class="metric-grid">
        <div>
          <span>总盈亏</span>
          <strong :class="Number(portfolio.summary.total_pnl || 0) >= 0 ? 'number-up' : 'number-down'">
            {{ trading.formatCurrency(portfolio.summary.total_pnl || 0) }}
          </strong>
        </div>
        <div>
          <span>账户收益率</span>
          <strong>{{ trading.formatPercent(portfolio.summary.account_return_pct || 0) }}</strong>
        </div>
        <div>
          <span>胜率</span>
          <strong>{{ trading.formatPercent(portfolio.summary.win_rate || 0) }}</strong>
        </div>
        <div>
          <span>盈亏比</span>
          <strong>{{ Number(portfolio.summary.profit_factor || 0).toFixed(2) }}</strong>
        </div>
        <div>
          <span>最大回撤</span>
          <strong class="number-down">{{ trading.formatPercent(portfolio.summary.max_drawdown_pct || 0) }}</strong>
        </div>
      </div>

      <BacktestChart :equity-curve="equityForChart" :drawdown-curve="drawdownForChart" :height="300" />
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Grouping</span>
          <h3>分组统计</h3>
        </div>
        <div class="button-row">
          <button class="ghost-button" :class="{ active: groupBy === 'symbol' }" @click="groupBy = 'symbol'">按标的</button>
          <button class="ghost-button" :class="{ active: groupBy === 'strategy' }" @click="groupBy = 'strategy'">按策略</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{{ groupBy === "symbol" ? "标的" : "策略" }}</th>
              <th>交易数</th>
              <th>已平仓</th>
              <th>总盈亏</th>
              <th>胜率</th>
              <th>盈亏比</th>
              <th>平均 ROI</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in groups" :key="item.key">
              <td>{{ item.key }}</td>
              <td>{{ item.trades }}</td>
              <td>{{ item.closed_trades }}</td>
              <td :class="Number(item.pnl || 0) >= 0 ? 'number-up' : 'number-down'">{{ trading.formatCurrency(item.pnl || 0) }}</td>
              <td>{{ trading.formatPercent(item.win_rate || 0) }}</td>
              <td>{{ Number(item.profit_factor || 0).toFixed(2) }}</td>
              <td>{{ trading.formatPercent(item.avg_trade_roi_pct || 0) }}</td>
            </tr>
            <tr v-if="!groups.length">
              <td colspan="7">暂无组合收益记录。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">History</span>
          <h3>收益明细</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ portfolio.history.length }} 条</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>标的</th>
              <th>方向</th>
              <th>状态</th>
              <th>盈亏</th>
              <th>ROI</th>
              <th>持仓时长</th>
              <th>策略</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in portfolio.history" :key="row.id">
              <td>{{ formatTime(row.timestamp) }}</td>
              <td>{{ row.symbol }}</td>
              <td>{{ row.side }}</td>
              <td><span class="status-chip status-chip--idle">{{ row.status }}</span></td>
              <td :class="Number(row.total_pnl || 0) >= 0 ? 'number-up' : 'number-down'">{{ trading.formatCurrency(row.total_pnl || 0) }}</td>
              <td>{{ trading.formatPercent(row.trade_roi_pct || 0) }}</td>
              <td>{{ formatMinutes(row.hold_minutes) }}</td>
              <td>{{ row.strategy_id || "-" }}</td>
            </tr>
            <tr v-if="!portfolio.history.length">
              <td colspan="8">暂无收益明细。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>
