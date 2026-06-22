import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient, classifyApiError } from "../lib/api";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";

const DEFAULT_CONFIG = {
  enabled: false,
  mode: "paper",
  decision_mode: "ai_supervised",
  symbols: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
  period: "1h",
  timeframes: [],
  scan_interval_seconds: 30,
  max_positions: 3,
  per_trade_position_ratio: 0.1,
  max_order_notional: 300,
  min_order_notional: 10,
  confidence_threshold: 0.35,
  ai_model: "deepseek-v4-pro",
  ai_fallback_model: "deepseek-v4-flash",
  ai_on_new_candle_only: true,
  ai_confidence_threshold: 0.65,
  stop_loss_pct: 0.02,
  take_profit_pct: 0.04,
  max_daily_loss: 200,
  max_consecutive_losses: 3,
  cooldown_minutes: 60,
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

/**
 * @typedef {Object} AutoStrategyConfig
 * @property {string} strategy_id
 * @property {string} type
 * @property {string[]} symbols
 * @property {number} weight
 * @property {boolean} enabled
 * @property {Record<string, unknown>} parameters
 */

/**
 * @typedef {Object} AutoTradingConfig
 * @property {boolean} enabled
 * @property {"paper"} mode
 * @property {"strategy" | "ai_supervised"} decision_mode
 * @property {string[]} symbols
 * @property {string} period
 * @property {string[]} timeframes
 * @property {number} scan_interval_seconds
 * @property {number} max_positions
 * @property {number} per_trade_position_ratio
 * @property {number} max_order_notional
 * @property {number} min_order_notional
 * @property {number} confidence_threshold
 * @property {"deepseek-v4-flash" | "deepseek-v4-pro"} ai_model
 * @property {"deepseek-v4-flash" | "deepseek-v4-pro"} ai_fallback_model
 * @property {boolean} ai_on_new_candle_only
 * @property {number} ai_confidence_threshold
 * @property {number} stop_loss_pct
 * @property {number} take_profit_pct
 * @property {number} max_daily_loss
 * @property {number} max_consecutive_losses
 * @property {number} cooldown_minutes
 * @property {boolean} real_trading_enabled
 * @property {AutoStrategyConfig[]} strategies
 */

/**
 * Normalize server or draft auto-trading config into a paper-only safe shape.
 *
 * @param {Record<string, unknown>} [config]
 * @returns {AutoTradingConfig}
 */
export function normalizeConfig(config = {}) {
  const merged = /** @type {AutoTradingConfig} */ ({ ...DEFAULT_CONFIG, ...config });
  const symbols = Array.isArray(merged.symbols)
    ? merged.symbols.map((item) => normalizeCryptoSymbol(item)).filter(Boolean)
    : DEFAULT_CONFIG.symbols;
  return {
    ...merged,
    mode: "paper",
    decision_mode: merged.decision_mode === "strategy" ? "strategy" : "ai_supervised",
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
  const loopRunning = computed(() => Boolean(status.value?.loop_running));
  const nextRunAt = computed(() => status.value?.next_run_at || "");
  const lastErrorType = computed(() => status.value?.last_error_type || "");
  const aiSupervisor = computed(() => status.value?.ai_supervisor || {});
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
    loopRunning,
    nextRunAt,
    lastErrorType,
    aiSupervisor,
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
