<script setup>
import { computed, onMounted, reactive, ref } from "vue";

import BacktestChart from "../components/BacktestChart.vue";
import { apiClient } from "../lib/api";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useTradingStore } from "../stores/trading";

const store = useTradingStore();
const loading = ref(false);
const message = ref("");
const templates = ref([]);
const runResult = ref(null);
const backtestResult = ref(null);

const form = reactive({
  symbolsText: "BTC/USDT,ETH/USDT,SOL/USDT",
  period: "1h",
  limit: 240,
  conflictThreshold: 0.15,
  initialCash: 10000,
  feeRate: 0.001,
  slippageRate: 0.0005,
  minQuantity: 0.000001,
});

const strategyConfigs = reactive([
  {
    strategy_id: "trend_dual_ma",
    type: "dual_ma",
    enabled: true,
    weight: 1,
    symbolsText: "BTC/USDT,ETH/USDT",
    parameters: { fast_period: 12, slow_period: 26, position_ratio: 0.2 },
  },
  {
    strategy_id: "rsi_reversion",
    type: "rsi",
    enabled: true,
    weight: 0.9,
    symbolsText: "BTC/USDT,SOL/USDT",
    parameters: { period: 14, oversold: 30, overbought: 70, position_ratio: 0.2 },
  },
  {
    strategy_id: "macd_trend",
    type: "macd",
    enabled: true,
    weight: 1,
    symbolsText: "BTC/USDT,ETH/USDT,SOL/USDT",
    parameters: { fast_period: 12, slow_period: 26, signal_period: 9, position_ratio: 0.2 },
  },
  {
    strategy_id: "bollinger_mean_reversion",
    type: "bollinger",
    enabled: true,
    weight: 0.8,
    symbolsText: "ETH/USDT,SOL/USDT",
    parameters: { period: 20, stddev_multiplier: 2, position_ratio: 0.2 },
  },
  {
    strategy_id: "momentum_breakout",
    type: "momentum",
    enabled: true,
    weight: 0.7,
    symbolsText: "BTC/USDT,ETH/USDT,SOL/USDT",
    parameters: { lookback_period: 20, buy_threshold: 0.03, sell_threshold: -0.02, position_ratio: 0.2 },
  },
]);

const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];
const enabledCount = computed(() => strategyConfigs.filter((item) => item.enabled).length);
const signalSummary = computed(() => runResult.value?.summary || []);
const strategyResults = computed(() => runResult.value?.strategy_results || []);
const backtests = computed(() => backtestResult.value?.items || []);
const backtestTrades = computed(() =>
  backtests.value.flatMap((item) =>
    (item.trades || []).map((trade) => ({
      ...trade,
      strategy_name: item.strategy_name,
    })),
  ),
);

function parseSymbols(text) {
  return [...new Set(String(text || "").split(",").map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
}

function numberValue(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function buildStrategiesPayload() {
  return strategyConfigs.map((item) => ({
    strategy_id: item.strategy_id,
    type: item.type,
    enabled: item.enabled,
    weight: numberValue(item.weight, 1),
    symbols: parseSymbols(item.symbolsText),
    parameters: { ...item.parameters },
  }));
}

function buildBasePayload() {
  return {
    symbols: parseSymbols(form.symbolsText),
    period: form.period,
    limit: numberValue(form.limit, 240),
    conflict_threshold: numberValue(form.conflictThreshold, 0.15),
    strategies: buildStrategiesPayload(),
  };
}

async function loadTemplates() {
  const { data } = await apiClient.get("/crypto/strategies/templates");
  templates.value = data.items || [];
}

async function runStrategies() {
  loading.value = true;
  message.value = "";
  try {
    const { data } = await apiClient.post("/crypto/strategies/run", buildBasePayload());
    runResult.value = data;
    message.value = "策略信号已刷新。";
  } catch (error) {
    store.setError(error, "运行策略信号失败");
  } finally {
    loading.value = false;
  }
}

async function backtestStrategies() {
  loading.value = true;
  message.value = "";
  try {
    const { data } = await apiClient.post("/crypto/strategies/backtest", {
      ...buildBasePayload(),
      initial_cash: numberValue(form.initialCash, 10000),
      fee_rate: numberValue(form.feeRate, 0.001),
      slippage_rate: numberValue(form.slippageRate, 0.0005),
      min_quantity: numberValue(form.minQuantity, 0.000001),
      position_sizing: "strategy_position_ratio",
    });
    backtestResult.value = data;
    message.value = "独立回测已完成，仅用于模拟验证，不会下单。";
  } catch (error) {
    store.setError(error, "策略回测失败");
  } finally {
    loading.value = false;
  }
}

function actionClass(action) {
  if (action === "BUY") return "number-up";
  if (action === "SELL") return "number-down";
  return "";
}

function formatNumber(value, digits = 2) {
  return Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatQuantity(value) {
  return Number(value || 0).toLocaleString("zh-CN", {
    maximumFractionDigits: 8,
  });
}

onMounted(async () => {
  try {
    await loadTemplates();
  } catch (error) {
    store.setError(error, "加载策略模板失败");
  }
});
</script>

<template>
  <section class="workspace-grid">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Crypto Strategy Engine</span>
          <h3>多策略并行</h3>
        </div>
        <span class="status-chip status-chip--idle">只生成模拟信号</span>
      </div>

      <div class="form-grid form-grid--four">
        <label>
          <span>交易对</span>
          <input v-model="form.symbolsText" placeholder="BTC/USDT,ETH/USDT,SOL/USDT" />
        </label>
        <label>
          <span>K 线周期</span>
          <select v-model="form.period">
            <option v-for="period in periods" :key="period" :value="period">{{ period }}</option>
          </select>
        </label>
        <label>
          <span>K 线数量</span>
          <input v-model.number="form.limit" type="number" min="30" max="1000" />
        </label>
        <label>
          <span>冲突阈值</span>
          <input v-model.number="form.conflictThreshold" type="number" min="0" max="10" step="0.01" />
        </label>
      </div>

      <div class="button-row">
        <button class="primary-button" :disabled="loading" @click="runStrategies">
          {{ loading ? "运行中" : "运行信号汇总" }}
        </button>
        <button class="ghost-button" :disabled="loading" @click="backtestStrategies">独立回测</button>
      </div>

      <p class="helper-text">
        已启用 {{ enabledCount }} 个策略。策略信号和回测都只用于模拟验证，不会触发真实下单，也不会自动提交 Paper 订单。
        <span v-if="message"> {{ message }}</span>
      </p>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Built-in Templates</span>
          <h3>内置策略</h3>
        </div>
      </div>
      <div class="metric-grid">
        <div v-for="item in templates" :key="item.type">
          <span>{{ item.name }}</span>
          <strong>{{ item.type }}</strong>
        </div>
      </div>
    </article>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Strategy Configs</span>
        <h3>策略实例</h3>
      </div>
    </div>
    <div class="strategy-list">
      <article v-for="item in strategyConfigs" :key="item.strategy_id" class="strategy-card">
        <div class="timeline-item__main">
          <strong>{{ item.strategy_id }}</strong>
          <p>{{ item.type }} · 权重 {{ item.weight }} · {{ item.symbolsText }}</p>
        </div>
        <div class="timeline-item__meta">
          <label class="inline-check">
            <input v-model="item.enabled" type="checkbox" />
            <span>启用</span>
          </label>
          <input v-model.number="item.weight" class="compact-input" type="number" min="0" max="10" step="0.1" />
        </div>
      </article>
    </div>
  </section>

  <section class="workspace-grid">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Signal Aggregation</span>
          <h3>信号汇总</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>交易对</th>
              <th>汇总动作</th>
              <th>净分</th>
              <th>买入分</th>
              <th>卖出分</th>
              <th>冲突</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in signalSummary" :key="item.symbol">
              <td>{{ item.symbol }}</td>
              <td :class="actionClass(item.action)">{{ item.action }}</td>
              <td>{{ item.net_score.toFixed(3) }}</td>
              <td>{{ item.buy_score.toFixed(3) }}</td>
              <td>{{ item.sell_score.toFixed(3) }}</td>
              <td>{{ item.conflict ? "是" : "否" }}</td>
              <td>{{ item.reason }}</td>
            </tr>
            <tr v-if="!signalSummary.length">
              <td colspan="7">暂无信号汇总，点击“运行信号汇总”。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Strategy Signals</span>
          <h3>策略独立信号</h3>
        </div>
      </div>
      <div class="timeline-list">
        <div v-for="result in strategyResults" :key="result.strategy_id" class="timeline-item">
          <div>
            <strong>{{ result.strategy_name }}</strong>
            <p>{{ result.strategy_id }} · {{ result.signals.length }} 条信号 · 权重 {{ result.weight }}</p>
            <small v-for="signal in result.signals" :key="`${result.strategy_id}-${signal.symbol}`">
              {{ signal.symbol }} {{ signal.action }} · {{ signal.reason }}
            </small>
          </div>
        </div>
        <div v-if="!strategyResults.length" class="timeline-item">
          <div>
            <strong>暂无策略信号</strong>
            <p>运行后会展示每个策略自己的模拟信号。</p>
          </div>
        </div>
      </div>
    </article>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Backtest</span>
        <h3>每个策略独立回测结果</h3>
      </div>
      <div class="button-row">
        <label>
          <span>本金 USDT</span>
          <input v-model.number="form.initialCash" class="compact-input" type="number" min="1" />
        </label>
        <label>
          <span>费率</span>
          <input v-model.number="form.feeRate" class="compact-input" type="number" min="0" max="0.1" step="0.0001" />
        </label>
        <label>
          <span>滑点</span>
          <input v-model.number="form.slippageRate" class="compact-input" type="number" min="0" max="0.1" step="0.0001" />
        </label>
        <label>
          <span>最小数量</span>
          <input v-model.number="form.minQuantity" class="compact-input" type="number" min="0.000001" step="0.000001" />
        </label>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>策略</th>
            <th>交易对</th>
            <th>最终权益</th>
            <th>收益率</th>
            <th>最大回撤</th>
            <th>夏普</th>
            <th>卡玛</th>
            <th>胜率</th>
            <th>盈亏比</th>
            <th>交易数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in backtests" :key="item.strategy_id">
            <td>{{ item.strategy_name }}</td>
            <td>{{ item.symbols.join(", ") }}</td>
            <td>{{ formatNumber(item.final_equity) }} {{ item.quote_currency || "USDT" }}</td>
            <td :class="Number(item.total_return_percent || 0) >= 0 ? 'number-up' : 'number-down'">
              {{ store.formatPercent(item.total_return_percent) }}
            </td>
            <td>{{ store.formatPercent(item.max_drawdown_percent) }}</td>
            <td>{{ formatNumber(item.sharpe_ratio) }}</td>
            <td>{{ formatNumber(item.calmar_ratio) }}</td>
            <td>{{ store.formatPercent(item.win_rate) }}</td>
            <td>{{ formatNumber(item.profit_factor) }}</td>
            <td>{{ item.trade_count }}</td>
          </tr>
          <tr v-if="!backtests.length">
            <td colspan="10">暂无回测结果，点击“独立回测”。</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="backtests.length" class="strategy-list">
      <article v-for="item in backtests" :key="`${item.strategy_id}-chart`" class="strategy-card strategy-card--wide">
        <div class="panel-heading panel-heading--compact">
          <div>
            <span class="eyebrow">{{ item.strategy_type }} · {{ item.period }}</span>
            <h3>{{ item.strategy_name }} 收益 / 回撤曲线</h3>
          </div>
          <span class="status-chip status-chip--idle">{{ item.message }}</span>
        </div>
        <BacktestChart :equity-curve="item.equity_curve" :drawdown-curve="item.drawdown_curve" :height="240" />
      </article>
    </div>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Backtest Trades</span>
        <h3>模拟交易明细</h3>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>策略</th>
            <th>交易对</th>
            <th>方向</th>
            <th>成交价</th>
            <th>数量</th>
            <th>手续费</th>
            <th>滑点成本</th>
            <th>实现盈亏</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="trade in backtestTrades" :key="`${trade.strategy_id}-${trade.index}-${trade.action}`">
            <td>{{ trade.timestamp }}</td>
            <td>{{ trade.strategy_name }}</td>
            <td>{{ trade.symbol }}</td>
            <td :class="actionClass(trade.action)">{{ trade.action }}</td>
            <td>{{ formatNumber(trade.fill_price, 4) }}</td>
            <td>{{ formatQuantity(trade.quantity) }}</td>
            <td>{{ formatNumber(trade.fee, 4) }}</td>
            <td>{{ formatNumber(trade.slippage, 4) }}</td>
            <td :class="Number(trade.realized_pnl || 0) >= 0 ? 'number-up' : 'number-down'">
              {{ formatNumber(trade.realized_pnl, 4) }}
            </td>
          </tr>
          <tr v-if="!backtestTrades.length">
            <td colspan="9">暂无模拟成交明细。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
