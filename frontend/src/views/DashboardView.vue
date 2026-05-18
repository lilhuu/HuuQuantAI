<script setup>
import { computed, onMounted } from "vue";

import { useTradingStore } from "../stores/trading";

const store = useTradingStore();

const latestQuote = computed(() => {
  const symbol = store.selectedCryptoSymbol;
  return store.cryptoQuotes.find((item) => item.symbol === symbol) || null;
});

const candles = computed(() => store.cryptoKlines || []);
const recentOrders = computed(() => store.cryptoOrders.slice(0, 5));
const accountCards = computed(() => [
  { label: "账户权益", value: `${Number(store.liveAccountValue || 0).toFixed(2)} USDT` },
  { label: "可用余额", value: `${Number(store.liveCash || 0).toFixed(2)} USDT` },
  { label: "持仓数量", value: String(store.cryptoPositions?.length || 0) },
  { label: "今日盈亏", value: `${Number((store.liveAccountValue || 0) - (store.cryptoAccount?.initial_cash || 0)).toFixed(2)} USDT` },
]);

const chartPeriod = computed(() => store.selectedCryptoPeriod || "15m");

const pricePath = computed(() => {
  const items = candles.value;
  if (!items.length) {
    return "";
  }
  const values = items.map((item) => Number(item.close || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(max - min, 1);
  return values
    .map((value, index) => {
      const x = 32 + (index / Math.max(values.length - 1, 1)) * 636;
      const y = 286 - ((value - min) / spread) * 220;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
});

async function loadPeriod(period) {
  store.selectedCryptoPeriod = period;
  await store.fetchCryptoKlines({
    symbol: store.selectedCryptoSymbol,
    period,
    limit: 200,
  });
  store.subscribeMarketSocket(store.cryptoWatchSymbols);
}

async function scanNow() {
  await Promise.allSettled([
    store.fetchCryptoQuotes(store.cryptoWatchSymbols),
    store.fetchCryptoKlines({
      symbol: store.selectedCryptoSymbol,
      period: chartPeriod.value,
      limit: 200,
    }),
    store.fetchCryptoPaperAccount(),
    store.fetchCryptoPaperOrders(),
  ]);
}

onMounted(() => {
  if (!candles.value.length) {
    store.fetchCryptoKlines({
      symbol: store.selectedCryptoSymbol,
      period: chartPeriod.value,
      limit: 200,
    }).catch(() => {});
  }
});
</script>

<template>
  <section class="cq-page-head">
    <h1>仪表盘</h1>
    <p>账户摘要、运行控制和自动交易扫描配置。</p>
  </section>

  <section class="cq-card-grid cq-card-grid--four">
    <article v-for="item in accountCards" :key="item.label" class="cq-metric-card">
      <span>{{ item.label }}</span>
      <strong>{{ item.value }}</strong>
    </article>
  </section>

  <section class="cq-dashboard-grid">
    <article class="cq-panel cq-run-panel">
      <div class="cq-panel__heading">
        <div>
          <h2>运行控制</h2>
          <p>启动、停止或立即触发一轮自动交易扫描。</p>
        </div>
        <span class="cq-pill">stopped</span>
      </div>

      <div class="cq-health-grid">
        <div>
          <span>Binance 公共接口</span>
          <strong>{{ store.marketSocketState === "connected" ? "已连接" : "未检查" }}</strong>
        </div>
        <div>
          <span>Binance 私有账户</span>
          <strong>未启用</strong>
        </div>
        <div>
          <span>代理链路</span>
          <strong>未配置</strong>
        </div>
      </div>

      <div class="cq-control-row">
        <button class="cq-primary-button" @click="store.connectRealtimeStreams">启动</button>
        <button class="cq-muted-button" @click="store.disconnectRealtimeStreams">停止</button>
        <button class="cq-accent-button" @click="scanNow">立即扫描</button>
      </div>

      <div class="cq-card-grid cq-card-grid--three">
        <article class="cq-metric-card cq-metric-card--compact">
          <span>影子模式</span>
          <strong>关闭</strong>
        </article>
        <article class="cq-metric-card cq-metric-card--compact">
          <span>触发阈值</span>
          <strong>0%</strong>
        </article>
        <article class="cq-metric-card cq-metric-card--compact">
          <span>最近周期</span>
          <strong>{{ chartPeriod }}</strong>
        </article>
      </div>

      <section class="cq-log-box">
        <strong>AI 代理活动日志</strong>
        <div v-if="recentOrders.length" class="cq-log-list">
          <p v-for="order in recentOrders" :key="order.order_id">
            {{ order.symbol }} {{ order.action }} · {{ order.status }} · {{ order.quantity }}
          </p>
        </div>
        <p v-else>暂无自动交易日志。</p>
      </section>
    </article>

    <article class="cq-panel cq-price-panel">
      <div class="cq-panel__heading">
        <div>
          <h2>价格概览</h2>
          <p>{{ store.selectedCryptoSymbol }} {{ chartPeriod }} 价格曲线</p>
        </div>
      </div>

      <div class="cq-period-tabs">
        <button :class="{ active: chartPeriod === '15m' }" @click="loadPeriod('15m')">15m</button>
        <button :class="{ active: chartPeriod === '1h' }" @click="loadPeriod('1h')">1h</button>
      </div>

      <div class="cq-price-chart">
        <svg viewBox="0 0 700 320" role="img" aria-label="价格概览">
          <path v-if="pricePath" :d="pricePath" fill="none" stroke="#7c6cff" stroke-width="3" />
          <text v-if="!pricePath" x="280" y="166" fill="#6f6f7c">暂无价格曲线</text>
        </svg>
      </div>

      <div class="cq-price-footer">
        <span>最新价</span>
        <strong>{{ store.formatPrice(latestQuote?.price || candles.at(-1)?.close || 0) }}</strong>
      </div>
    </article>
  </section>
</template>
