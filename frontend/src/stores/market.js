import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient } from "../lib/api";
import { createReconnectingSocket } from "../lib/reconnectingSocket";
import { createCryptoSocket } from "../lib/ws";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";

const REQUEST_CACHE_MS = 3000;

export const MARKET_TABS = [
  { label: "现货", value: "spot", quoteFilters: ["ALL", "USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB"] },
  { label: "U本位合约", value: "um_futures", quoteFilters: ["ALL", "USDT", "USDC"] },
  { label: "币本位合约", value: "cm_futures", quoteFilters: ["ALL", "USD", "BTC", "ETH"] },
  { label: "期权", value: "options", quoteFilters: ["ALL", "USDT"] },
];

const MARKET_TYPE_SET = new Set(MARKET_TABS.map((item) => item.value));

/**
 * @param {Array<string | number | null | undefined>} symbols
 * @returns {string[]}
 */
export function uniqueCryptoSymbols(symbols = []) {
  return [...new Set((symbols || []).map((item) => normalizeMarketSymbol(item)).filter(Boolean))];
}

/**
 * @param {string | number | null | undefined} value
 * @param {string=} marketType
 * @returns {string}
 */
export function normalizeMarketSymbol(value, marketType = "spot") {
  const text = String(value || "").trim().toUpperCase();
  if (!text) return "";
  if (marketType === "options" || text.includes("_")) {
    return text;
  }
  return normalizeCryptoSymbol(text);
}

/**
 * @param {string} state
 * @returns {string}
 */
export function cryptoMarketStatusMessage(state) {
  if (state === "connecting") return "正在连接 Binance 实时行情";
  if (state === "connected") return "Binance 实时行情已连接";
  if (state === "snapshot_loading") return "正在加载 REST 行情快照";
  if (state === "reconnecting") return "实时行情断线重连中";
  if (state === "error") return "实时行情连接异常";
  return "实时行情未连接";
}

export const useMarketStore = defineStore("trading-market", () => {
  const marketType = ref("spot");
  const cryptoQuotes = ref([]);
  const cryptoKlines = ref([]);
  const cryptoWatchSymbols = ref(["BTC/USDT", "ETH/USDT", "SOL/USDT"]);
  const selectedCryptoSymbol = ref("BTC/USDT");
  const selectedCryptoPeriod = ref("1h");
  const cryptoLoading = ref(false);
  const cryptoKlineLoading = ref(false);
  const cryptoKlineSource = ref("ccxt_binance");
  const marketSocketState = ref("idle");
  const marketStatusMessage = ref("实时行情未连接");
  const lastMarketMessageAt = ref("");
  const cryptoOrderBook = ref(
    /** @type {{ bids: unknown[], asks: unknown[], symbol?: string, timestamp?: string, source?: string }} */ ({
      bids: [],
      asks: [],
    }),
  );
  const orderBookLoading = ref(false);
  const marketSocketActive = ref(false);
  const marketSocketAllMarket = ref(false);
  const derivativeMetrics = ref(null);
  const derivativeMetricsLoading = ref(false);

  const cryptoSymbols = ref([]);
  const symbolTotal = ref(0);
  const symbolLoading = ref(false);
  const quoteSearch = ref("");
  const quoteFilter = ref("USDT");
  const quoteSortField = ref("amount");
  const quoteSortDir = ref("desc");
  const quotePage = ref(1);
  const quotePageSize = ref(50);
  const quotesTotal = ref(0);
  const quoteRequestCache = { key: "", completedAt: 0, data: null };
  const klineRequestCache = { key: "", completedAt: 0, data: null };
  const orderBookRequestCache = { key: "", completedAt: 0, data: null };
  const metricsRequestCache = { key: "", completedAt: 0, data: null };

  const activeMarketTab = computed(() => MARKET_TABS.find((item) => item.value === marketType.value) || MARKET_TABS[0]);
  const quoteFilterOptions = computed(() => activeMarketTab.value.quoteFilters.map((value) => ({ label: value === "ALL" ? "全部" : value, value })));

  const marketSocket = createReconnectingSocket({
    createSocket: (options) => createCryptoSocket(options),
    onStateChange: (state) => {
      marketSocketState.value = state;
      marketStatusMessage.value = cryptoMarketStatusMessage(state);
    },
    onMessage: handleMarketSocketMessage,
    onError: () => {
      marketStatusMessage.value = "行情源暂不可用，页面仍可使用 REST 手动刷新";
    },
    onReconnectScheduled: ({ delayMs }) => {
      marketStatusMessage.value = `行情流断开，${Math.round(delayMs / 1000)} 秒后自动重连`;
    },
  });

  const filteredSortedQuotes = computed(() => {
    let result = [...cryptoQuotes.value];
    if (quoteSearch.value) {
      const q = quoteSearch.value.trim().toUpperCase();
      result = result.filter((item) => (item.symbol || "").toUpperCase().includes(q));
    }
    if (quoteFilter.value && quoteFilter.value !== "ALL") {
      const f = quoteFilter.value.toUpperCase();
      result = result.filter((item) => {
        if (item.quote) return String(item.quote).toUpperCase() === f;
        return (item.symbol || "").toUpperCase().endsWith("/" + f);
      });
    }
    const field = quoteSortField.value || "amount";
    const dir = quoteSortDir.value === "asc" ? 1 : -1;
    result.sort((a, b) => {
      const aVal = field === "symbol" ? (a.symbol || "") : Number(a[field] || 0);
      const bVal = field === "symbol" ? (b.symbol || "") : Number(b[field] || 0);
      if (field === "symbol") return dir * aVal.localeCompare(bVal);
      return dir * (aVal - bVal);
    });
    quotesTotal.value = result.length;
    return result;
  });

  const paginatedQuotes = computed(() => {
    const start = (quotePage.value - 1) * quotePageSize.value;
    return filteredSortedQuotes.value.slice(start, start + quotePageSize.value);
  });

  const totalPages = computed(() => Math.max(1, Math.ceil(quotesTotal.value / quotePageSize.value)));

  function setMarketType(nextType) {
    const normalized = MARKET_TYPE_SET.has(nextType) ? nextType : "spot";
    if (marketType.value === normalized) return;
    marketType.value = normalized;
    quoteFilter.value = normalized === "spot" ? "USDT" : "ALL";
    quoteSearch.value = "";
    quotePage.value = 1;
    cryptoQuotes.value = [];
    cryptoSymbols.value = [];
    derivativeMetrics.value = null;
    if (marketSocketActive.value) {
      connectMarketSocket({ allMarket: marketSocketAllMarket.value });
    }
  }

  async function fetchCryptoSymbols(options = {}) {
    const { quote, search, limit = 500, offset = 0, marketType: requestedMarketType = marketType.value } = options;
    symbolLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/symbols", {
        params: { market_type: requestedMarketType, quote, search, limit, offset },
      });
      cryptoSymbols.value = data.items || [];
      symbolTotal.value = data.total || 0;
      return data;
    } finally {
      symbolLoading.value = false;
    }
  }

  async function fetchCryptoQuotes(symbols = null, options = {}) {
    const { search, quote, limit, offset, marketType: requestedMarketType = marketType.value } = options;
    const normalizedSymbols = symbols ? uniqueSymbols(symbols, requestedMarketType) : null;
    const params = { market_type: requestedMarketType };
    if (normalizedSymbols && normalizedSymbols.length) params.symbols = normalizedSymbols.join(",");
    if (search) params.search = search;
    if (quote) params.quote = quote;
    if (limit != null) params.limit = limit;
    if (offset != null) params.offset = offset;
    const requestKey = stableRequestKey(params);
    const cachedQuoteData = readFreshRequestCache(quoteRequestCache, requestKey);
    if (cachedQuoteData) return cachedQuoteData;
    quoteRequestCache.key = requestKey;

    cryptoLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/quotes", { params });
      cryptoQuotes.value = [...(data.items || [])].sort((left, right) => String(left.symbol || "").localeCompare(String(right.symbol || "")));
      if (normalizedSymbols && normalizedSymbols.length) cryptoWatchSymbols.value = normalizedSymbols;
      quoteRequestCache.data = data;
      quoteRequestCache.completedAt = Date.now();
      if (String(data.source || "").startsWith("cache_")) {
        marketStatusMessage.value = "行情源暂不可用，正在显示本地缓存";
      }
      return data;
    } catch (error) {
      marketStatusMessage.value = "REST 行情刷新失败";
      throw error;
    } finally {
      cryptoLoading.value = false;
    }
  }

  async function fetchCryptoKlines({
    symbol = selectedCryptoSymbol.value,
    period = selectedCryptoPeriod.value,
    limit = 200,
    marketType: requestedMarketType = marketType.value,
  } = {}) {
    const normalizedSymbol = normalizeMarketSymbol(symbol, requestedMarketType);
    const requestKey = stableRequestKey({ symbol: normalizedSymbol, period, limit, market_type: requestedMarketType });
    const cachedKlineData = readFreshRequestCache(klineRequestCache, requestKey);
    if (cachedKlineData) return cachedKlineData;
    klineRequestCache.key = requestKey;

    cryptoKlineLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/klines", {
        params: { market_type: requestedMarketType, symbol: normalizedSymbol, period, limit },
      });
      selectedCryptoSymbol.value = normalizedSymbol;
      selectedCryptoPeriod.value = data.period || period;
      cryptoKlines.value = [...(data.items || [])].sort((left, right) => String(left.start_time || "").localeCompare(String(right.start_time || "")));
      cryptoKlineSource.value = data.source || `binance_${requestedMarketType}`;
      if (String(data.source || "").startsWith("cache_")) {
        marketStatusMessage.value = "K 线源不可用，正在显示本地缓存";
      }
      if (marketSocketActive.value) connectMarketSocket();
      klineRequestCache.data = data;
      klineRequestCache.completedAt = Date.now();
      return data;
    } catch (error) {
      marketStatusMessage.value = "历史 K 线刷新失败";
      throw error;
    } finally {
      cryptoKlineLoading.value = false;
    }
  }

  async function fetchCryptoOrderBook(symbol, limit = 20, options = {}) {
    const requestedMarketType = options.marketType || marketType.value;
    const normalizedSymbol = normalizeMarketSymbol(symbol || selectedCryptoSymbol.value, requestedMarketType);
    const requestKey = stableRequestKey({ symbol: normalizedSymbol, limit, market_type: requestedMarketType });
    const cachedOrderBookData = readFreshRequestCache(orderBookRequestCache, requestKey);
    if (cachedOrderBookData) return cachedOrderBookData;
    orderBookRequestCache.key = requestKey;

    orderBookLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/orderbook", {
        params: { market_type: requestedMarketType, symbol: normalizedSymbol, limit },
      });
      upsertOrderBook(data, requestedMarketType);
      orderBookRequestCache.data = data;
      orderBookRequestCache.completedAt = Date.now();
      return data;
    } catch (error) {
      marketStatusMessage.value = "盘口刷新失败";
      throw error;
    } finally {
      orderBookLoading.value = false;
    }
  }

  async function fetchDerivativeMetrics(symbol = selectedCryptoSymbol.value, options = {}) {
    const requestedMarketType = options.marketType || marketType.value;
    if (requestedMarketType === "spot") {
      derivativeMetrics.value = null;
      return null;
    }
    const normalizedSymbol = normalizeMarketSymbol(symbol, requestedMarketType);
    const requestKey = stableRequestKey({ symbol: normalizedSymbol, market_type: requestedMarketType });
    const cachedMetrics = readFreshRequestCache(metricsRequestCache, requestKey);
    if (cachedMetrics) return cachedMetrics;
    metricsRequestCache.key = requestKey;

    derivativeMetricsLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/derivatives/metrics", {
        params: { market_type: requestedMarketType, symbol: normalizedSymbol },
      });
      derivativeMetrics.value = data;
      metricsRequestCache.data = data;
      metricsRequestCache.completedAt = Date.now();
      return data;
    } finally {
      derivativeMetricsLoading.value = false;
    }
  }

  function connectMarketSocket(options = {}) {
    marketSocketActive.value = true;
    marketSocketAllMarket.value = Boolean(options.allMarket ?? marketSocketAllMarket.value);
    const symbols = uniqueSymbols(cryptoWatchSymbols.value, marketType.value);
    marketSocket.connect({
      symbols: marketSocketAllMarket.value ? [] : symbols.length ? symbols : ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
      period: selectedCryptoPeriod.value || "1h",
      selectedSymbol: selectedCryptoSymbol.value || "BTC/USDT",
      depthLimit: 20,
      allMarket: marketSocketAllMarket.value,
      marketType: marketType.value,
    });
  }

  function disconnectMarketSocket() {
    marketSocketActive.value = false;
    marketSocketAllMarket.value = false;
    marketSocket.disconnect();
  }

  function subscribeMarketSocket(symbols = cryptoWatchSymbols.value) {
    const normalizedSymbols = uniqueSymbols(symbols, marketType.value);
    if (normalizedSymbols.length) cryptoWatchSymbols.value = normalizedSymbols;
    if (marketSocketActive.value) connectMarketSocket({ allMarket: marketSocketAllMarket.value });
  }

  function handleMarketSocketMessage(payload) {
    const type = String(payload?.type || "");
    if (type === "crypto_ticker") {
      upsertQuote(payload.item || payload);
      updateMarketStamp();
      return;
    }
    if (type === "crypto_kline") {
      upsertKline(payload.item || payload);
      updateMarketStamp();
      return;
    }
    if (type === "crypto_depth") {
      upsertOrderBook(payload.item || payload);
      updateMarketStamp();
      return;
    }
    if (type === "crypto_status") {
      marketSocketState.value = payload.state || marketSocketState.value;
      marketStatusMessage.value = payload.message || cryptoMarketStatusMessage(marketSocketState.value);
      updateMarketStamp(payload.timestamp);
      return;
    }
    if (type === "crypto_error") {
      marketSocketState.value = payload.recoverable ? "reconnecting" : "error";
      marketStatusMessage.value = payload.message || "行情源不可用";
      updateMarketStamp(payload.timestamp);
    }
  }

  function upsertQuote(item) {
    const itemMarketType = item?.market_type || marketType.value;
    if (itemMarketType !== marketType.value) return;
    const symbol = normalizeMarketSymbol(item?.symbol, itemMarketType);
    if (!symbol) return;
    const nextItem = {
      ...item,
      market_type: itemMarketType,
      symbol,
      source: item?.source || "binance_ws",
      timestamp: item?.timestamp || new Date().toISOString(),
    };
    const index = cryptoQuotes.value.findIndex((quote) => quote.symbol === symbol);
    if (index >= 0) {
      cryptoQuotes.value.splice(index, 1, { ...cryptoQuotes.value[index], ...nextItem });
    } else {
      cryptoQuotes.value.push(nextItem);
      cryptoQuotes.value.sort((left, right) => String(left.symbol || "").localeCompare(String(right.symbol || "")));
    }
  }

  function upsertKline(item) {
    const symbol = normalizeMarketSymbol(item?.symbol, marketType.value);
    if (!symbol || symbol !== selectedCryptoSymbol.value || item.period !== selectedCryptoPeriod.value) return;
    const index = cryptoKlines.value.findIndex((row) => row.start_time === item.start_time);
    if (index >= 0) {
      cryptoKlines.value.splice(index, 1, { ...cryptoKlines.value[index], ...item, symbol });
    } else {
      cryptoKlines.value.push({ ...item, symbol });
      cryptoKlines.value.sort((left, right) => String(left.start_time || "").localeCompare(String(right.start_time || "")));
      if (cryptoKlines.value.length > 1000) cryptoKlines.value = cryptoKlines.value.slice(-1000);
    }
    cryptoKlineSource.value = item.source || "binance_ws";
  }

  function upsertOrderBook(item, requestedMarketType = marketType.value) {
    cryptoOrderBook.value = {
      bids: item?.bids || [],
      asks: item?.asks || [],
      symbol: normalizeMarketSymbol(item?.symbol, requestedMarketType) || item?.symbol,
      timestamp: item?.timestamp || new Date().toISOString(),
      source: item?.source || `binance_${requestedMarketType}`,
    };
  }

  function updateMarketStamp(timestamp) {
    if (!timestamp) {
      lastMarketMessageAt.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      return;
    }
    const parsed = new Date(timestamp);
    lastMarketMessageAt.value = Number.isNaN(parsed.getTime()) ? String(timestamp) : parsed.toLocaleTimeString("zh-CN", { hour12: false });
  }

  function resetMarketState() {
    disconnectMarketSocket();
    cryptoQuotes.value = [];
    cryptoKlines.value = [];
    cryptoOrderBook.value = { bids: [], asks: [] };
    derivativeMetrics.value = null;
    cryptoLoading.value = false;
    cryptoKlineLoading.value = false;
    orderBookLoading.value = false;
    derivativeMetricsLoading.value = false;
    cryptoKlineSource.value = "ccxt_binance";
    marketSocketState.value = "idle";
    marketStatusMessage.value = "实时行情未连接";
    lastMarketMessageAt.value = "";
  }

  function uniqueSymbols(symbols = [], requestedMarketType = marketType.value) {
    return [...new Set((symbols || []).map((item) => normalizeMarketSymbol(item, requestedMarketType)).filter(Boolean))];
  }

  function stableRequestKey(params = {}) {
    return JSON.stringify(
      Object.keys(params)
        .sort()
        .reduce((result, key) => {
          result[key] = params[key];
          return result;
        }, {}),
    );
  }

  function readFreshRequestCache(cache, key) {
    if (cache.key !== key || !cache.data) return null;
    return Date.now() - cache.completedAt < REQUEST_CACHE_MS ? cache.data : null;
  }

  return {
    marketType,
    marketTabs: MARKET_TABS,
    activeMarketTab,
    quoteFilterOptions,
    cryptoQuotes,
    cryptoKlines,
    cryptoOrderBook,
    derivativeMetrics,
    derivativeMetricsLoading,
    cryptoWatchSymbols,
    selectedCryptoSymbol,
    selectedCryptoPeriod,
    cryptoLoading,
    cryptoKlineLoading,
    orderBookLoading,
    cryptoKlineSource,
    marketSocketState,
    marketStatusMessage,
    lastMarketMessageAt,
    marketSocketActive,
    marketSocketAllMarket,
    cryptoSymbols,
    symbolTotal,
    symbolLoading,
    quoteSearch,
    quoteFilter,
    quoteSortField,
    quoteSortDir,
    quotePage,
    quotePageSize,
    quotesTotal,
    filteredSortedQuotes,
    paginatedQuotes,
    totalPages,
    setMarketType,
    fetchCryptoSymbols,
    fetchCryptoQuotes,
    fetchCryptoKlines,
    fetchCryptoOrderBook,
    fetchDerivativeMetrics,
    connectMarketSocket,
    disconnectMarketSocket,
    subscribeMarketSocket,
    resetMarketState,
  };
});
