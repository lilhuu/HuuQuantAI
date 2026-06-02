<script setup>
import { computed, ref } from "vue";

import CryptoKlineChart from "../components/CryptoKlineChart.vue";
import { useMarketStore } from "../stores/market";
import { useTradingStore } from "../stores/trading";
import { normalizeCryptoSymbol } from "../stores/tradingUtils";

const tradingStore = useTradingStore();
const marketStore = useMarketStore();

const symbolInput = ref(marketStore.selectedCryptoSymbol || "BTC/USDT");
const periodInput = ref(marketStore.selectedCryptoPeriod || "1h");
const limitInput = ref(200);
const orderBookSymbolInput = ref(marketStore.selectedCryptoSymbol || "BTC/USDT");
const orderBookLimitInput = ref(20);
const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];

const quoteFilters = ["USDT", "BTC", "ETH", "BNB"];
const pageSizes = [20, 50, 100];

const latestQuote = computed(() => {
  const symbol = normalizeCryptoSymbol(symbolInput.value);
  return marketStore.cryptoQuotes.find((item) => item.symbol === symbol) || null;
});
const orderBook = computed(() => marketStore.cryptoOrderBook || { bids: [], asks: [] });
const topBids = computed(() => [...(orderBook.value.bids || [])].slice(0, 10));
const topAsks = computed(() => [...(orderBook.value.asks || [])].slice(0, 10));
const candles = computed(() => marketStore.cryptoKlines || []);

const socketTone = computed(() => {
  if (marketStore.marketSocketState === "connected") return "status-chip--connected";
  if (["connecting", "reconnecting", "snapshot_loading"].includes(marketStore.marketSocketState)) return "status-chip--idle";
  if (marketStore.marketSocketState === "error") return "status-chip--error";
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
  return labels[marketStore.marketSocketState] || marketStore.marketSocketState;
});

function sortIcon(field) {
  if (marketStore.quoteSortField !== field) return "";
  return marketStore.quoteSortDir === "asc" ? " ▲" : " ▼";
}

function toggleSort(field) {
  if (marketStore.quoteSortField === field) {
    marketStore.quoteSortDir = marketStore.quoteSortDir === "asc" ? "desc" : "asc";
  } else {
    marketStore.quoteSortField = field;
    marketStore.quoteSortDir = "desc";
  }
}

function onSearchInput() {
  marketStore.quotePage = 1;
}

function onFilterChange() {
  marketStore.quotePage = 1;
  refreshQuotes();
}

function onPageSizeChange() {
  marketStore.quotePage = 1;
}

function goToPage(page) {
  marketStore.quotePage = Math.max(1, Math.min(page, marketStore.totalPages));
}

async function refreshQuotes() {
  await marketStore.fetchCryptoQuotes(null, {
    search: marketStore.quoteSearch || undefined,
    quote: marketStore.quoteFilter || undefined,
    limit: 0,
    offset: 0,
  });
  marketStore.subscribeMarketSocket(marketStore.cryptoWatchSymbols);
}

async function loadKlines() {
  await marketStore.fetchCryptoKlines({
    symbol: symbolInput.value,
    period: periodInput.value,
    limit: Number(limitInput.value || 200),
  });
  orderBookSymbolInput.value = normalizeCryptoSymbol(symbolInput.value);
}

async function loadOrderBook() {
  await marketStore.fetchCryptoOrderBook(orderBookSymbolInput.value, Number(orderBookLimitInput.value || 20));
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
          <button class="ghost-button" @click="marketStore.connectMarketSocket">连接实时流</button>
          <button class="ghost-button" @click="marketStore.disconnectMarketSocket">断开</button>
          <button class="ghost-button" @click="refreshQuotes">REST 刷新</button>
        </div>
      </div>

      <p class="helper-text">
        {{ marketStore.marketStatusMessage }}
        <span v-if="marketStore.lastMarketMessageAt"> · {{ marketStore.lastMarketMessageAt }}</span>
        <span v-if="marketStore.quotesTotal"> · 共 {{ marketStore.quotesTotal }} 个交易对</span>
      </p>

      <div class="form-grid form-grid--three">
        <label>
          <span>搜索交易对</span>
          <input
            v-model="marketStore.quoteSearch"
            placeholder="搜索交易对..."
            @input="onSearchInput"
          />
        </label>
        <label>
          <span>计价货币</span>
          <select v-model="marketStore.quoteFilter" @change="onFilterChange">
            <option v-for="f in quoteFilters" :key="f" :value="f">{{ f }}</option>
          </select>
        </label>
        <label>
          <span>每页条数</span>
          <select v-model.number="marketStore.quotePageSize" @change="onPageSizeChange">
            <option v-for="size in pageSizes" :key="size" :value="size">{{ size }} 条</option>
          </select>
        </label>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="sortable-header" @click="toggleSort('symbol')">交易对{{ sortIcon("symbol") }}</th>
              <th class="sortable-header" @click="toggleSort('price')">最新价{{ sortIcon("price") }}</th>
              <th class="sortable-header" @click="toggleSort('change')">24h 涨跌{{ sortIcon("change") }}</th>
              <th class="sortable-header" @click="toggleSort('volume')">成交量{{ sortIcon("volume") }}</th>
              <th>来源</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="quote in marketStore.paginatedQuotes" :key="quote.symbol">
              <td>{{ quote.symbol }}</td>
              <td>{{ tradingStore.formatPrice(quote.price) }}</td>
              <td :class="Number(quote.change || 0) >= 0 ? 'number-up' : 'number-down'">
                {{ tradingStore.formatPercent((quote.change || 0) * 100) }}
              </td>
              <td>{{ tradingStore.formatPrice(quote.volume || quote.amount || 0) }}</td>
              <td>{{ quote.source || "-" }}</td>
              <td>{{ quote.timestamp || "-" }}</td>
            </tr>
            <tr v-if="!marketStore.paginatedQuotes.length">
              <td colspan="6">暂无行情。点击 REST 刷新加载币安全部交易对，或连接实时流自动推送。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="pagination-bar" v-if="marketStore.totalPages > 1">
        <button class="ghost-button" :disabled="marketStore.quotePage <= 1" @click="goToPage(marketStore.quotePage - 1)">上一页</button>
        <span class="pagination-info">第 {{ marketStore.quotePage }} / {{ marketStore.totalPages }} 页</span>
        <button class="ghost-button" :disabled="marketStore.quotePage >= marketStore.totalPages" @click="goToPage(marketStore.quotePage + 1)">下一页</button>
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
            <span class="number-up">{{ tradingStore.formatPrice(bid[0]) }}</span>
            <span>{{ bid[1]?.toFixed(6) || "-" }}</span>
            <span>{{ tradingStore.formatPrice(topBids.slice(0, idx + 1).reduce((sum, item) => sum + (item[1] || 0), 0)) }}</span>
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
            <span class="number-down">{{ tradingStore.formatPrice(ask[0]) }}</span>
            <span>{{ ask[1]?.toFixed(6) || "-" }}</span>
            <span>{{ tradingStore.formatPrice(topAsks.slice(0, idx + 1).reduce((sum, item) => sum + (item[1] || 0), 0)) }}</span>
          </div>
        </div>
      </div>
      <p v-else class="helper-text">实时流连接后会自动刷新当前交易对的简化盘口，也可以手动使用 REST 加载。</p>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">K 线分析</span>
          <h3>{{ marketStore.selectedCryptoSymbol }} K 线</h3>
        </div>
        <span class="status-chip status-chip--connected">{{ marketStore.cryptoKlineSource }}</span>
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
          <strong>{{ tradingStore.formatPrice(candles.at(-1)?.close || latestQuote?.price || 0) }}</strong>
        </div>
        <div>
          <span>最新高点</span>
          <strong>{{ tradingStore.formatPrice(candles.at(-1)?.high || 0) }}</strong>
        </div>
      </div>

      <div class="chart-surface chart-surface--kline">
        <CryptoKlineChart :candles="candles" :height="380" />
      </div>
    </article>
  </section>
</template>
