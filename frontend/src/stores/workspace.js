import { ref, watch } from "vue";
import { defineStore, storeToRefs } from "pinia";

import { apiClient } from "../lib/api";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useMarketStore } from "./market";
import { useSystemStore } from "./system";
import { useUiStore } from "./ui";

const PREFERENCE_SAVE_DELAY_MS = 250;

export const useWorkspaceStore = defineStore("trading-workspace", () => {
  const marketStore = useMarketStore();
  const systemStore = useSystemStore();
  const uiStore = useUiStore();

  const marketRefs = storeToRefs(marketStore);
  const uiRefs = storeToRefs(uiStore);

  const preferencesHydrated = ref(false);
  let preferenceSaveTimer = null;

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

  return {
    preferencesHydrated,
    loadUserPreferences,
    saveUserPreferences,
    bootstrap,
    connectRealtimeStreams,
    disconnectRealtimeStreams,
    resetState,
  };
});
