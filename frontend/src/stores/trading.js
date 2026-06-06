import { computed, ref, watch } from "vue";
import { defineStore, storeToRefs } from "pinia";

import { apiClient } from "../lib/api";
import { useMarketStore } from "./market";
import { useSystemStore } from "./system";
import { useUiStore } from "./ui";
import { formatCryptoSymbol, normalizeCryptoSymbol, toneFromSocketState } from "../lib/tradingUtils";

const PREFERENCE_SAVE_DELAY_MS = 250;

export const useTradingStore = defineStore("trading", () => {
  const marketStore = useMarketStore();
  const systemStore = useSystemStore();
  const uiStore = useUiStore();

  const marketRefs = storeToRefs(marketStore);
  const systemRefs = storeToRefs(systemStore);
  const uiRefs = storeToRefs(uiStore);

  const preferencesHydrated = ref(false);
  let preferenceSaveTimer = null;

  const systemBannerTone = computed(() => toneFromSocketState(systemStore.systemSocketState));
  const ordersBannerTone = computed(() => "idle");
  const marketBannerTone = computed(() => toneFromSocketState(marketStore.marketSocketState));

  const topMetrics = computed(() => [
    {
      label: "总权益",
      value: uiStore.formatCurrency(systemStore.liveAccountValue),
    },
    {
      label: "USDT 现金",
      value: uiStore.formatCurrency(systemStore.liveCash),
    },
    {
      label: "持仓市值",
      value: uiStore.formatCurrency(systemStore.livePositionValue),
    },
    {
      label: "交易对",
      value: `${marketStore.cryptoQuotes.length} 个`,
    },
  ]);

  watch(
    [marketRefs.cryptoWatchSymbols, marketRefs.selectedCryptoSymbol, uiRefs.soundEnabled],
    () => {
      if (!preferencesHydrated.value) {
        return;
      }
      scheduleUserPreferenceSave();
    },
    { deep: true },
  );

  async function loadUserPreferences() {
    try {
      const { data } = await apiClient.get("/auth/preferences");
      const workspace = data?.preferences?.workspace || {};
      const alerts = data?.preferences?.alerts || {};
      const nextWatchSymbols = Array.isArray(workspace.cryptoWatchSymbols)
        ? workspace.cryptoWatchSymbols.map((item) => normalizeCryptoSymbol(item)).filter(Boolean)
        : [];

      if (nextWatchSymbols.length) {
        marketStore.cryptoWatchSymbols = [...new Set(nextWatchSymbols)];
      }

      if (workspace.selectedCryptoSymbol) {
        marketStore.selectedCryptoSymbol = normalizeCryptoSymbol(workspace.selectedCryptoSymbol);
      }

      if (typeof alerts.soundEnabled === "boolean") {
        uiStore.soundEnabled = alerts.soundEnabled;
      }

      preferencesHydrated.value = true;
      return data;
    } catch (error) {
      preferencesHydrated.value = true;
      if (error?.response?.status !== 401) {
        systemStore.setError(error, "加载用户偏好失败");
      }
      return null;
    }
  }

  async function saveUserPreferences() {
    const payload = {
      preferences: {
        workspace: {
          cryptoWatchSymbols: marketStore.cryptoWatchSymbols,
          selectedCryptoSymbol: marketStore.selectedCryptoSymbol,
        },
        alerts: {
          soundEnabled: uiStore.soundEnabled,
        },
      },
    };
    return apiClient.put("/auth/preferences", payload);
  }

  function scheduleUserPreferenceSave() {
    if (preferenceSaveTimer) {
      clearTimeout(preferenceSaveTimer);
    }
    preferenceSaveTimer = setTimeout(async () => {
      try {
        await saveUserPreferences();
      } catch (error) {
        if (error?.response?.status !== 401) {
          systemStore.setError(error, "保存用户偏好失败");
        }
      }
    }, PREFERENCE_SAVE_DELAY_MS);
  }

  async function bootstrap() {
    await Promise.all([
      systemStore.refreshOverview(),
      marketStore.fetchCryptoQuotes(marketStore.cryptoWatchSymbols),
      marketStore.fetchCryptoKlines({
        symbol: marketStore.selectedCryptoSymbol,
        period: marketStore.selectedCryptoPeriod,
        limit: 200,
      }),
    ]);
  }

  function connectRealtimeStreams() {
    marketStore.connectMarketSocket();
    systemStore.connectSystemSocket();
  }

  function disconnectRealtimeStreams() {
    marketStore.disconnectMarketSocket();
    systemStore.disconnectSystemSocket();
  }

  function resetState() {
    if (preferenceSaveTimer) {
      clearTimeout(preferenceSaveTimer);
      preferenceSaveTimer = null;
    }
    marketStore.resetMarketState();
    systemStore.resetSystemState();
    uiStore.resetUiState();
    preferencesHydrated.value = false;
  }

  function displaySymbol(symbol) {
    return formatCryptoSymbol(symbol);
  }

  function displaySymbolList(symbols = []) {
    return symbols.map((symbol) => displaySymbol(symbol)).join(", ");
  }

  return {
    ...systemRefs,
    ...marketRefs,
    ...uiRefs,
    preferencesHydrated,
    systemBannerTone,
    ordersBannerTone,
    marketBannerTone,
    topMetrics,
    loadUserPreferences,
    saveUserPreferences,
    bootstrap,
    refreshOverview: systemStore.refreshOverview,
    fetchCryptoPaperAccount: systemStore.fetchCryptoPaperAccount,
    fetchCryptoPaperPositions: systemStore.fetchCryptoPaperPositions,
    fetchCryptoPaperOrders: systemStore.fetchCryptoPaperOrders,
    placeCryptoPaperOrder: systemStore.placeCryptoPaperOrder,
    cancelCryptoPaperOrder: systemStore.cancelCryptoPaperOrder,
    fetchCryptoPaperEquityCurve: systemStore.fetchCryptoPaperEquityCurve,
    fetchCryptoPaperLogs: systemStore.fetchCryptoPaperLogs,
    fetchCryptoQuotes: marketStore.fetchCryptoQuotes,
    fetchCryptoKlines: marketStore.fetchCryptoKlines,
    fetchCryptoOrderBook: marketStore.fetchCryptoOrderBook,
    setError: systemStore.setError,
    clearError: systemStore.clearError,
    connectMarketSocket: marketStore.connectMarketSocket,
    disconnectMarketSocket: marketStore.disconnectMarketSocket,
    connectSystemSocket: systemStore.connectSystemSocket,
    disconnectSystemSocket: systemStore.disconnectSystemSocket,
    connectRealtimeStreams,
    disconnectRealtimeStreams,
    subscribeMarketSocket: marketStore.subscribeMarketSocket,
    displaySymbol,
    displaySymbolList,
    primeAlertAudio: uiStore.primeAlertAudio,
    setSoundEnabled: uiStore.setSoundEnabled,
    toggleSound: uiStore.toggleSound,
    badgeClassForOrder: uiStore.badgeClassForOrder,
    badgeClassForEvent: uiStore.badgeClassForEvent,
    eventToneFromType: uiStore.eventToneFromType,
    getOrderRowClass: uiStore.getOrderRowClass,
    getOrderPulseClass: uiStore.getOrderPulseClass,
    eventCardClass: uiStore.eventCardClass,
    resetState,
    formatCurrency: uiStore.formatCurrency,
    formatPercent: uiStore.formatPercent,
    formatPrice: uiStore.formatPrice,
  };
});
