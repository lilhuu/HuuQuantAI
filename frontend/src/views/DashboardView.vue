<script setup>
import { computed, onMounted } from "vue";

import { useAutoTradingStore } from "../stores/autoTrading";
import { useTradingStore } from "../stores/trading";

const store = useTradingStore();
const autoStore = useAutoTradingStore();

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
  { label: "累计盈亏", value: `${Number((store.liveAccountValue || 0) - (store.cryptoAccount?.initial_cash || 0)).toFixed(2)} USDT` },
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
  await autoStore.scan();
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

onMounted(async () => {
  if (!autoStore.status) {
    autoStore.fetchStatus().catch(() => {});
  }
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
  <section class="workspace-grid workspace-grid--stacked">
    <div class="page-head">
      <h1>仪表盘</h1>
      <p>账户摘要、运行控制和自动交易扫描配置。</p>
    </div>

    <div class="metric-grid">
      <div v-for="item in accountCards" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </div>

    <div class="workspace-grid workspace-grid--columns">
      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <h3>运行控制</h3>
            <p>启动、停止或立即触发一轮自动交易扫描。</p>
          </div>
          <span class="status-chip" :class="autoStore.enabled ? 'status-chip--connected' : 'status-chip--idle'">{{ autoStore.stateLabel }}</span>
        </div>

        <div class="metric-grid">
          <div>
            <span>Binance 公共接口</span>
            <strong>{{ store.marketSocketState === "connected" ? "已连接" : "未检查" }}</strong>
          </div>
          <div>
            <span>真实交易</span>
            <strong>永久关闭</strong>
          </div>
          <div>
            <span>自动模式</span>
            <strong>{{ autoStore.enabled ? "模拟运行中" : "未启动" }}</strong>
          </div>
        </div>

        <div class="button-row">
          <button class="primary-button" @click="autoStore.start()">启动</button>
          <button class="ghost-button" @click="autoStore.stop()">停止</button>
          <button class="ghost-button" @click="scanNow">立即扫描</button>
        </div>

        <div class="metric-grid">
          <div>
            <span>自助交易</span>
            <strong>{{ autoStore.stateLabel }}</strong>
          </div>
          <div>
            <span>信心阈值</span>
            <strong>{{ Number(autoStore.configDraft.confidence_threshold || 0).toFixed(2) }}</strong>
          </div>
          <div>
            <span>最近周期</span>
            <strong>{{ chartPeriod }}</strong>
          </div>
        </div>

        <div class="timeline-list">
          <div class="panel-heading">
            <strong>自动交易活动日志</strong>
          </div>
          <div v-if="autoStore.logs.length" class="timeline-item" v-for="log in autoStore.logs.slice(-5)" :key="`${log.timestamp}-${log.event}`">
            <strong>{{ log.event }}</strong>
            <p>{{ log.message }}</p>
            <small>{{ log.timestamp }}</small>
          </div>
          <div v-else-if="recentOrders.length" v-for="order in recentOrders" :key="order.order_id" class="timeline-item">
            <strong>{{ order.symbol }} {{ order.action }}</strong>
            <p>{{ order.status }} · {{ order.quantity }}</p>
          </div>
          <p v-else class="helper-text">暂无自动交易日志。</p>
        </div>
      </article>

      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <h3>价格概览</h3>
            <p>{{ store.selectedCryptoSymbol }} {{ chartPeriod }} 价格曲线</p>
          </div>
        </div>

        <div class="button-row">
          <button :class="{ active: chartPeriod === '15m' }" @click="loadPeriod('15m')">15m</button>
          <button :class="{ active: chartPeriod === '1h' }" @click="loadPeriod('1h')">1h</button>
        </div>

        <div class="chart-surface">
          <svg viewBox="0 0 700 320" role="img" aria-label="价格概览">
            <path v-if="pricePath" :d="pricePath" fill="none" stroke="#7c6cff" stroke-width="3" />
            <text v-if="!pricePath" x="280" y="166" fill="#6f6f7c">暂无价格曲线</text>
          </svg>
        </div>

        <div class="metric-grid">
          <div>
            <span>最新价</span>
            <strong>{{ store.formatPrice(latestQuote?.price || candles.at(-1)?.close || 0) }}</strong>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
