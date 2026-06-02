import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient } from "../lib/api";
import { createReconnectingSocket } from "../lib/reconnectingSocket";
import { createCryptoSocket } from "../lib/ws";
import { normalizeCryptoSymbol } from "./tradingUtils";

/**
 * @typedef {Object} CryptoQuote
 * @property {string} symbol
 * @property {number=} price
 * @property {string=} source
 * @property {string=} timestamp
 */

/**
 * @param {Array<string | number | null | undefined>} symbols
 * @returns {string[]}
 */
export function uniqueCryptoSymbols(symbols = []) {
  return [...new Set((symbols || []).map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
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

  const cryptoSymbols = ref([]);
  const symbolTotal = ref(0);
  const symbolLoading = ref(false);
  const quoteSearch = ref("");
  const quoteFilter = ref("USDT");
  const quoteSortField = ref("volume");
  const quoteSortDir = ref("desc");
  const quotePage = ref(1);
  const quotePageSize = ref(50);
  const quotesTotal = ref(0);

  const marketSocket = createReconnectingSocket({
    createSocket: (options) => createCryptoSocket(options),
    onStateChange: (state) => {
      marketSocketState.value = state;
      marketStatusMessage.value = statusMessageForState(state);
    },
    onMessage: handleMarketSocketMessage,
    onError: () => {
      marketStatusMessage.value = "行情源不可用，页面仍可使用 REST 手动刷新";
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
    if (quoteFilter.value) {
      const f = quoteFilter.value.toUpperCase();
      result = result.filter((item) => (item.symbol || "").toUpperCase().endsWith("/" + f));
    }
    const field = quoteSortField.value || "volume";
    const dir = quoteSortDir.value === "asc" ? 1 : -1;
    result.sort((a, b) => {
      const aVal = field === "symbol" ? (a.symbol || "") : Number(a[field] || 0);
      const bVal = field === "symbol" ? (b.symbol || "") : Number(b[field] || 0);
      if (field === "symbol") return dir * aVal.localeCompare(bVal);
      return dir * (bVal - aVal);
    });
    quotesTotal.value = result.length;
    return result;
  });

  const paginatedQuotes = computed(() => {
    const start = (quotePage.value - 1) * quotePageSize.value;
    return filteredSortedQuotes.value.slice(start, start + quotePageSize.value);
  });

  const totalPages = computed(() => Math.max(1, Math.ceil(quotesTotal.value / quotePageSize.value)));

  async function fetchCryptoSymbols({ quote, search, limit = 500, offset = 0 } = {}) {
    symbolLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/symbols", { params: { quote, search, limit, offset } });
      cryptoSymbols.value = data.items || [];
      symbolTotal.value = data.total || 0;
      return data;
    } finally {
      symbolLoading.value = false;
    }
  }

  async function fetchCryptoQuotes(symbols = null, { search, quote, limit, offset } = {}) {
    const normalizedSymbols = symbols ? uniqueSymbols(symbols) : null;
    const params = {};
    if (normalizedSymbols && normalizedSymbols.length) {
      params.symbols = normalizedSymbols.join(",");
    }
    if (search) params.search = search;
    if (quote) params.quote = quote;
    if (limit != null) params.limit = limit;
    if (offset != null) params.offset = offset;

    cryptoLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/quotes", { params });
      cryptoQuotes.value = [...(data.items || [])].sort((left, right) => left.symbol.localeCompare(right.symbol));
      if (normalizedSymbols && normalizedSymbols.length) {
        cryptoWatchSymbols.value = normalizedSymbols;
      }
      if (data.source === "cache_binance") {
        marketStatusMessage.value = "行情源不可用，正在显示本地缓存快照";
      }
      return data;
    } catch (error) {
      marketStatusMessage.value = "行情源不可用，REST 行情刷新失败";
      throw error;
    } finally {
      cryptoLoading.value = false;
    }
  }

  async function fetchCryptoKlines({
    symbol = selectedCryptoSymbol.value,
    period = selectedCryptoPeriod.value,
    limit = 200,
  } = {}) {
    const normalizedSymbol = normalizeCryptoSymbol(symbol);
    cryptoKlineLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/klines", {
        params: { symbol: normalizedSymbol, period, limit },
      });
      selectedCryptoSymbol.value = normalizedSymbol;
      selectedCryptoPeriod.value = data.period || period;
      cryptoKlines.value = [...(data.items || [])].sort((left, right) =>
        String(left.start_time || "").localeCompare(String(right.start_time || "")),
      );
      cryptoKlineSource.value = data.source || "ccxt_binance";
      if (data.source === "cache_binance") {
        marketStatusMessage.value = "K 线源不可用，正在显示本地缓存";
      }
      if (marketSocketActive.value) {
        connectMarketSocket();
      }
      return data;
    } catch (error) {
      marketStatusMessage.value = "K 线源不可用，历史 K 线刷新失败";
      throw error;
    } finally {
      cryptoKlineLoading.value = false;
    }
  }

  async function fetchCryptoOrderBook(symbol, limit = 20) {
    const normalizedSymbol = normalizeCryptoSymbol(symbol || selectedCryptoSymbol.value);
    orderBookLoading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/orderbook", {
        params: { symbol: normalizedSymbol, limit },
      });
      upsertOrderBook(data);
      return data;
    } catch (error) {
      marketStatusMessage.value = "盘口源不可用，深度刷新失败";
      throw error;
    } finally {
      orderBookLoading.value = false;
    }
  }

  function connectMarketSocket() {
    marketSocketActive.value = true;
    const symbols = uniqueSymbols(cryptoWatchSymbols.value);
    marketSocket.connect({
      symbols: symbols.length ? symbols : ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
      period: selectedCryptoPeriod.value || "1h",
      selectedSymbol: selectedCryptoSymbol.value || "BTC/USDT",
      depthLimit: 20,
    });
  }

  function disconnectMarketSocket() {
    marketSocketActive.value = false;
    marketSocket.disconnect();
  }

  function subscribeMarketSocket(symbols = cryptoWatchSymbols.value) {
    const normalizedSymbols = uniqueSymbols(symbols);
    if (normalizedSymbols.length) {
      cryptoWatchSymbols.value = normalizedSymbols;
    }
    if (marketSocketActive.value) {
      connectMarketSocket();
    }
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
      marketStatusMessage.value = payload.message || statusMessageForState(marketSocketState.value);
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
    const symbol = normalizeCryptoSymbol(item?.symbol);
    if (!symbol) {
      return;
    }
    const nextItem = {
      ...item,
      symbol,
      source: item?.source || "binance_ws",
      timestamp: item?.timestamp || new Date().toISOString(),
    };
    const index = cryptoQuotes.value.findIndex((quote) => quote.symbol === symbol);
    if (index >= 0) {
      cryptoQuotes.value.splice(index, 1, { ...cryptoQuotes.value[index], ...nextItem });
    } else {
      cryptoQuotes.value.push(nextItem);
      cryptoQuotes.value.sort((left, right) => left.symbol.localeCompare(right.symbol));
    }
  }

  function upsertKline(item) {
    const symbol = normalizeCryptoSymbol(item?.symbol);
    if (!symbol || symbol !== selectedCryptoSymbol.value || item.period !== selectedCryptoPeriod.value) {
      return;
    }
    const index = cryptoKlines.value.findIndex((row) => row.start_time === item.start_time);
    if (index >= 0) {
      cryptoKlines.value.splice(index, 1, { ...cryptoKlines.value[index], ...item, symbol });
    } else {
      cryptoKlines.value.push({ ...item, symbol });
      cryptoKlines.value.sort((left, right) =>
        String(left.start_time || "").localeCompare(String(right.start_time || "")),
      );
      if (cryptoKlines.value.length > 1000) {
        cryptoKlines.value = cryptoKlines.value.slice(-1000);
      }
    }
    cryptoKlineSource.value = item.source || "binance_ws";
  }

  function upsertOrderBook(item) {
    cryptoOrderBook.value = {
      bids: item?.bids || [],
      asks: item?.asks || [],
      symbol: normalizeCryptoSymbol(item?.symbol) || item?.symbol,
      timestamp: item?.timestamp || new Date().toISOString(),
      source: item?.source || "binance",
    };
  }

  function updateMarketStamp(timestamp) {
    if (!timestamp) {
      lastMarketMessageAt.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      return;
    }
    const parsed = new Date(timestamp);
    lastMarketMessageAt.value = Number.isNaN(parsed.getTime())
      ? String(timestamp)
      : parsed.toLocaleTimeString("zh-CN", { hour12: false });
  }

  function resetMarketState() {
    disconnectMarketSocket();
    cryptoQuotes.value = [];
    cryptoKlines.value = [];
    cryptoOrderBook.value = { bids: [], asks: [] };
    cryptoLoading.value = false;
    cryptoKlineLoading.value = false;
    orderBookLoading.value = false;
    cryptoKlineSource.value = "ccxt_binance";
    marketSocketState.value = "idle";
    marketStatusMessage.value = "实时行情未连接";
    lastMarketMessageAt.value = "";
  }

  function uniqueSymbols(symbols = []) {
    return uniqueCryptoSymbols(symbols);
  }

  function statusMessageForState(state) {
    if (state === "connecting") return "正在连接 Binance 实时行情";
    if (state === "connected") return "Binance 实时行情已连接";
    if (state === "snapshot_loading") return "正在加载 REST 行情快照";
    if (state === "reconnecting") return "实时行情断线重连中";
    if (state === "error") return "实时行情连接异常";
    return "实时行情未连接";
  }

  return {
    cryptoQuotes,
    cryptoKlines,
    cryptoOrderBook,
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
    fetchCryptoSymbols,
    fetchCryptoQuotes,
    fetchCryptoKlines,
    fetchCryptoOrderBook,
    connectMarketSocket,
    disconnectMarketSocket,
    subscribeMarketSocket,
    resetMarketState,
  };
});
