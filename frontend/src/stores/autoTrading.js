import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient, classifyApiError } from "../lib/api";
import { normalizeCryptoSymbol } from "./tradingUtils";

const DEFAULT_CONFIG = {
  enabled: false,
  mode: "paper",
  symbols: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
  period: "1h",
  timeframes: [],
  scan_interval_seconds: 30,
  max_positions: 3,
  per_trade_position_ratio: 0.1,
  max_order_notional: 1000,
  min_order_notional: 10,
  confidence_threshold: 0.35,
  real_trading_enabled: false,
  strategies: [
    {
      strategy_id: "auto_rsi",
      type: "rsi",
      symbols: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
      weight: 1,
      enabled: true,
      parameters: { period: 14, oversold: 30, overbought: 70, position_ratio: 0.08 },
    },
    {
      strategy_id: "auto_macd",
      type: "macd",
      symbols: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
      weight: 0.8,
      enabled: true,
      parameters: { position_ratio: 0.06 },
    },
  ],
};

function normalizeConfig(config = {}) {
  const merged = { ...DEFAULT_CONFIG, ...config };
  const symbols = Array.isArray(merged.symbols)
    ? merged.symbols.map((item) => normalizeCryptoSymbol(item)).filter(Boolean)
    : DEFAULT_CONFIG.symbols;
  return {
    ...merged,
    mode: "paper",
    symbols: symbols.length ? [...new Set(symbols)] : DEFAULT_CONFIG.symbols,
    real_trading_enabled: false,
  };
}

export const useAutoTradingStore = defineStore("auto-trading", () => {
  const loading = ref(false);
  const errorInfo = ref(null);
  const status = ref(null);
  const configDraft = ref(normalizeConfig());

  const state = computed(() => status.value?.state || "stopped");
  const enabled = computed(() => Boolean(status.value?.enabled));
  const decisions = computed(() => status.value?.last_decisions || []);
  const logs = computed(() => status.value?.logs || []);
  const stateLabel = computed(() => {
    const labels = {
      running: "运行中",
      paused: "已暂停",
      stopped: "已停止",
      blocked: "已阻断",
    };
    return labels[state.value] || state.value;
  });

  function applyStatus(payload) {
    status.value = payload;
    configDraft.value = normalizeConfig(payload?.config || configDraft.value);
    return payload;
  }

  async function fetchStatus() {
    loading.value = true;
    try {
      const { data } = await apiClient.get("/crypto/auto/status");
      return applyStatus(data);
    } catch (error) {
      setError(error, "加载自动交易状态失败");
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function saveConfig() {
    loading.value = true;
    try {
      const payload = normalizeConfig(configDraft.value);
      const { data } = await apiClient.put("/crypto/auto/config", payload);
      return applyStatus(data);
    } catch (error) {
      setError(error, "保存自动交易配置失败");
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function start() {
    loading.value = true;
    try {
      await saveConfig();
      const { data } = await apiClient.post("/crypto/auto/start");
      return applyStatus(data);
    } catch (error) {
      setError(error, "启动自动交易失败");
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function pause() {
    return postAction("/crypto/auto/pause", "暂停自动交易失败");
  }

  async function stop() {
    return postAction("/crypto/auto/stop", "停止自动交易失败");
  }

  async function scan() {
    return postAction("/crypto/auto/scan", "执行自动扫描失败");
  }

  async function postAction(url, fallbackMessage) {
    loading.value = true;
    try {
      const { data } = await apiClient.post(url);
      return applyStatus(data);
    } catch (error) {
      setError(error, fallbackMessage);
      throw error;
    } finally {
      loading.value = false;
    }
  }

  function setSymbolsText(text) {
    configDraft.value.symbols = String(text || "")
      .split(",")
      .map((item) => normalizeCryptoSymbol(item))
      .filter(Boolean);
  }

  function symbolsText() {
    return (configDraft.value.symbols || []).join(", ");
  }

  function setError(error, fallbackMessage = "请求失败") {
    const info = classifyApiError(error);
    errorInfo.value = { ...info, message: info.message || fallbackMessage };
  }

  function clearError() {
    errorInfo.value = null;
  }

  return {
    loading,
    errorInfo,
    status,
    configDraft,
    state,
    enabled,
    decisions,
    logs,
    stateLabel,
    fetchStatus,
    saveConfig,
    start,
    pause,
    stop,
    scan,
    setSymbolsText,
    symbolsText,
    clearError,
  };
});
