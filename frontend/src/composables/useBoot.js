import { ref } from "vue";

import { useAuthStore } from "../stores/auth";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useTradingStore } from "../stores/trading";
import { useToast } from "./useToast";

export function useBoot() {
  const authStore = useAuthStore();
  const autoStore = useAutoTradingStore();
  const tradingStore = useTradingStore();
  const { setError } = useToast();

  const isBooting = ref(false);
  const lastBootError = ref(null);
  let bootPromise = null;

  async function initializeWorkbench() {
    if (bootPromise) {
      return bootPromise;
    }

    isBooting.value = true;
    bootPromise = (async () => {
      try {
        await authStore.ensureInitialized();
        if (!authStore.isAuthenticated) {
          return false;
        }

        await tradingStore.loadUserPreferences();
        await Promise.allSettled([tradingStore.bootstrap(), autoStore.fetchStatus()]);
        tradingStore.connectRealtimeStreams();
        lastBootError.value = null;
        return true;
      } catch (error) {
        lastBootError.value = error;
        setError(error, "初始化 HuuQuantAI 工作台失败");
        return false;
      } finally {
        isBooting.value = false;
        bootPromise = null;
      }
    })();

    return bootPromise;
  }

  function teardownWorkbench({ reset = false } = {}) {
    tradingStore.disconnectRealtimeStreams();
    if (reset) {
      tradingStore.resetState();
    }
  }

  return {
    initializeWorkbench,
    teardownWorkbench,
    isBooting,
    lastBootError,
  };
}
