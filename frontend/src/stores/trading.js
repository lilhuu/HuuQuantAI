import { computed } from "vue";
import { defineStore, storeToRefs } from "pinia";

import { formatCryptoSymbol, toneFromSocketState } from "../lib/tradingUtils";
import { useMarketStore } from "./market";
import { useSystemStore } from "./system";
import { useUiStore } from "./ui";
import { useWorkspaceStore } from "./workspace";

export const useTradingStore = defineStore("trading", () => {
  const marketStore = useMarketStore();
  const systemStore = useSystemStore();
  const uiStore = useUiStore();
  const workspaceStore = useWorkspaceStore();

  const marketRefs = storeToRefs(marketStore);
  const systemRefs = storeToRefs(systemStore);
  const uiRefs = storeToRefs(uiStore);
  const workspaceRefs = storeToRefs(workspaceStore);

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
    ...workspaceRefs,
    systemBannerTone,
    ordersBannerTone,
    marketBannerTone,
    topMetrics,
    loadUserPreferences: workspaceStore.loadUserPreferences,
    saveUserPreferences: workspaceStore.saveUserPreferences,
    bootstrap: workspaceStore.bootstrap,
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
    connectRealtimeStreams: workspaceStore.connectRealtimeStreams,
    disconnectRealtimeStreams: workspaceStore.disconnectRealtimeStreams,
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
    resetState: workspaceStore.resetState,
    formatCurrency: uiStore.formatCurrency,
    formatPercent: uiStore.formatPercent,
    formatPrice: uiStore.formatPrice,
  };
});
