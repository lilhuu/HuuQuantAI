<script setup>
import { computed, ref } from "vue";

import { useTradingStore } from "../stores/trading";
import { normalizeCryptoSymbol } from "../stores/tradingUtils";

const store = useTradingStore();
const symbolInput = ref(store.selectedCryptoSymbol || "BTC/USDT");
const periodInput = ref(store.selectedCryptoPeriod || "1h");
const limitInput = ref(200);
const quoteInput = ref(store.cryptoWatchSymbols.join(","));
const orderBookSymbolInput = ref(store.selectedCryptoSymbol || "BTC/USDT");
const orderBookLimitInput = ref(20);

const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];

const latestQuote = computed(() => {
  const symbol = normalizeCryptoSymbol(symbolInput.value);
  return store.cryptoQuotes.find((item) => item.symbol === symbol) || null;
});
const orderBook = computed(() => store.cryptoOrderBook || { bids: [], asks: [] });
const topBids = computed(() => [...(orderBook.value.bids || [])].slice(0, 10));
const topAsks = computed(() => [...(orderBook.value.asks || [])].slice(0, 10));
const candles = computed(() => store.cryptoKlines || []);

const socketTone = computed(() => {
  if (store.marketSocketState === "connected") return "status-chip--connected";
  if (["connecting", "reconnecting", "snapshot_loading"].includes(store.marketSocketState)) return "status-chip--idle";
  if (store.marketSocketState === "error") return "status-chip--error";
  return "status-chip--idle";
});

const socketLabel = computed(() => {
  const labels = {
    idle: "未连接",
    connecting: "连接中",
    snapshot_loading: "加载快照",
    connected: "实时中",
    reconnecting: "重连中",
    error: "异常",
  };
  return labels[store.marketSocketState] || store.marketSocketState;
});

const candlePath = computed(() => {
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
      const x = (index / Math.max(values.length - 1, 1)) * 1000;
      const y = 260 - ((value - min) / spread) * 220;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
});

async function refreshQuotes() {
  const symbols = quoteInput.value
    .split(",")
    .map((item) => normalizeCryptoSymbol(item))
    .filter(Boolean);
  await store.fetchCryptoQuotes(symbols.length ? symbols : store.cryptoWatchSymbols);
  store.subscribeMarketSocket(symbols.length ? symbols : store.cryptoWatchSymbols);
}

async function loadKlines() {
  await store.fetchCryptoKlines({
    symbol: symbolInput.value,
    period: periodInput.value,
    limit: Number(limitInput.value || 200),
  });
  orderBookSymbolInput.value = normalizeCryptoSymbol(symbolInput.value);
}

async function loadOrderBook() {
  await store.fetchCryptoOrderBook(orderBookSymbolInput.value, Number(orderBookLimitInput.value || 20));
}
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Binance WebSocket + REST</span>
          <h3>实时行情</h3>
        </div>
        <div class="button-row">
          <span class="status-chip" :class="socketTone">{{ socketLabel }}</span>
          <button class="ghost-button" @click="store.connectMarketSocket">连接实时流</button>
          <button class="ghost-button" @click="store.disconnectMarketSocket">断开</button>
          <button class="ghost-button" @click="refreshQuotes">REST 刷新</button>
        </div>
      </div>

      <p class="helper-text">
        {{ store.marketStatusMessage }}
        <span v-if="store.lastMarketMessageAt"> · {{ store.lastMarketMessageAt }}</span>
      </p>

      <div class="form-grid">
        <label>
          <span>交易对列表</span>
          <input v-model="quoteInput" placeholder="BTC/USDT,ETH/USDT,SOL/USDT" />
        </label>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>交易对</th>
              <th>最新价</th>
              <th>24h 涨跌</th>
              <th>成交量</th>
              <th>来源</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="quote in store.cryptoQuotes" :key="quote.symbol">
              <td>{{ quote.symbol }}</td>
              <td>{{ store.formatPrice(quote.price) }}</td>
              <td :class="Number(quote.change || 0) >= 0 ? 'number-up' : 'number-down'">
                {{ store.formatPercent((quote.change || 0) * 100) }}
              </td>
              <td>{{ store.formatPrice(quote.volume || quote.amount || 0) }}</td>
              <td>{{ quote.source || "-" }}</td>
              <td>{{ quote.timestamp || "-" }}</td>
            </tr>
            <tr v-if="!store.cryptoQuotes.length">
              <td colspan="6">暂无行情。实时流会先加载 REST 快照，失败时会显示明确错误。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Order Book</span>
          <h3>{{ orderBook.symbol || "BTC/USDT" }} 买卖盘</h3>
        </div>
        <span class="status-chip" :class="orderBook.timestamp ? 'status-chip--connected' : 'status-chip--idle'">
          {{ orderBook.source || "ccxt" }}
        </span>
      </div>

      <div class="form-grid form-grid--three">
        <label>
          <span>交易对</span>
          <input v-model="orderBookSymbolInput" placeholder="BTC/USDT" />
        </label>
        <label>
          <span>深度档位</span>
          <input v-model.number="orderBookLimitInput" type="number" min="5" max="20" />
        </label>
        <button class="primary-button form-button" @click="loadOrderBook">REST 加载深度</button>
      </div>

      <div v-if="orderBook.timestamp" class="orderbook-grid">
        <div class="orderbook-side">
          <div class="orderbook-header bid-header">买盘 Bids</div>
          <div class="orderbook-row orderbook-row--label">
            <span>价格</span>
            <span>数量</span>
            <span>累计</span>
          </div>
          <div v-for="(bid, idx) in topBids" :key="`b${idx}`" class="orderbook-row orderbook-row--bid">
            <span class="number-up">{{ store.formatPrice(bid[0]) }}</span>
            <span>{{ bid[1]?.toFixed(6) || "-" }}</span>
            <span>{{ store.formatPrice(topBids.slice(0, idx + 1).reduce((sum, item) => sum + (item[0] || 0) * (item[1] || 0), 0)) }}</span>
          </div>
        </div>
        <div class="orderbook-side">
          <div class="orderbook-header ask-header">卖盘 Asks</div>
          <div class="orderbook-row orderbook-row--label">
            <span>价格</span>
            <span>数量</span>
            <span>累计</span>
          </div>
          <div v-for="(ask, idx) in topAsks" :key="`a${idx}`" class="orderbook-row orderbook-row--ask">
            <span class="number-down">{{ store.formatPrice(ask[0]) }}</span>
            <span>{{ ask[1]?.toFixed(6) || "-" }}</span>
            <span>{{ store.formatPrice(topAsks.slice(0, idx + 1).reduce((sum, item) => sum + (item[0] || 0) * (item[1] || 0), 0)) }}</span>
          </div>
        </div>
      </div>
      <p v-else class="helper-text">实时流连接后会自动刷新当前交易对的简化盘口，也可以手动使用 REST 加载。</p>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">K 线分析</span>
          <h3>{{ store.selectedCryptoSymbol }} K 线</h3>
        </div>
        <span class="status-chip status-chip--connected">{{ store.cryptoKlineSource }}</span>
      </div>

      <div class="form-grid form-grid--four">
        <label>
          <span>交易对</span>
          <input v-model="symbolInput" placeholder="BTC/USDT" />
        </label>
        <label>
          <span>周期</span>
          <select v-model="periodInput">
            <option v-for="period in periods" :key="period" :value="period">{{ period }}</option>
          </select>
        </label>
        <label>
          <span>数量</span>
          <input v-model.number="limitInput" type="number" min="20" max="1000" />
        </label>
        <button class="primary-button form-button" @click="loadKlines">加载 K 线</button>
      </div>

      <div class="metric-grid">
        <div>
          <span>K 线数量</span>
          <strong>{{ candles.length }}</strong>
        </div>
        <div>
          <span>最新收盘</span>
          <strong>{{ store.formatPrice(candles.at(-1)?.close || latestQuote?.price || 0) }}</strong>
        </div>
        <div>
          <span>最新高点</span>
          <strong>{{ store.formatPrice(candles.at(-1)?.high || 0) }}</strong>
        </div>
      </div>

      <div class="chart-surface">
        <svg viewBox="0 0 1000 300" role="img" aria-label="Crypto kline close price chart">
          <path v-if="candlePath" :d="candlePath" fill="none" stroke="#25d0cf" stroke-width="4" />
          <text v-else x="40" y="160" fill="#8fa7c4">暂无 K 线数据</text>
        </svg>
      </div>
    </article>
  </section>
</template>
