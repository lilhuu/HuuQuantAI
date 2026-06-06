import { computed } from "vue";

import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useUiStore } from "../stores/ui";

const DEFAULT_PAIR_OPTIONS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"];

export function useWorkspaceActions() {
  const autoStore = useAutoTradingStore();
  const marketStore = useMarketStore();
  const systemStore = useSystemStore();
  const uiStore = useUiStore();

  const pairOptions = computed(() => {
    const base = [...DEFAULT_PAIR_OPTIONS, ...marketStore.cryptoWatchSymbols];
    return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
  });

  const selectedCryptoSymbol = computed({
    get: () => marketStore.selectedCryptoSymbol,
    set: (value) => {
      marketStore.selectedCryptoSymbol = value;
    },
  });

  const selectedQuote = computed(() => {
    const symbol = normalizeCryptoSymbol(marketStore.selectedCryptoSymbol);
    return marketStore.cryptoQuotes.find((item) => item.symbol === symbol) || null;
  });

  const priceText = computed(() => uiStore.formatPrice(selectedQuote.value?.price || 0));
  const changeText = computed(() => uiStore.formatPercent((selectedQuote.value?.change || 0) * 100));
  const changeClass = computed(() => (Number(selectedQuote.value?.change || 0) >= 0 ? "number-up" : "number-down"));

  async function changeSymbol() {
    const symbol = normalizeCryptoSymbol(marketStore.selectedCryptoSymbol);
    if (!symbol) {
      return;
    }

    marketStore.selectedCryptoSymbol = symbol;
    if (!marketStore.cryptoWatchSymbols.includes(symbol)) {
      marketStore.cryptoWatchSymbols = [...marketStore.cryptoWatchSymbols, symbol];
    }

    await Promise.allSettled([
      marketStore.fetchCryptoQuotes(marketStore.cryptoWatchSymbols),
      marketStore.fetchCryptoKlines({
        symbol,
        period: marketStore.selectedCryptoPeriod || "1h",
        limit: 200,
      }),
    ]);
    marketStore.subscribeMarketSocket(marketStore.cryptoWatchSymbols);
  }

  async function refreshWorkspace() {
    await Promise.allSettled([
      systemStore.refreshOverview(),
      autoStore.fetchStatus(),
      marketStore.fetchCryptoQuotes(marketStore.cryptoWatchSymbols),
      marketStore.fetchCryptoKlines({
        symbol: marketStore.selectedCryptoSymbol,
        period: marketStore.selectedCryptoPeriod || "1h",
        limit: 200,
      }),
    ]);
  }

  function clearWorkspaceError() {
    systemStore.clearError();
  }

  return {
    autoStateLabel: computed(() => autoStore.stateLabel),
    pairOptions,
    selectedCryptoSymbol,
    priceText,
    changeText,
    changeClass,
    errorInfo: computed(() => systemStore.errorInfo),
    changeSymbol,
    refreshWorkspace,
    clearWorkspaceError,
    primeAlertAudio: uiStore.primeAlertAudio,
  };
}
