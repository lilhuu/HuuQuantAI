import { computed, ref } from "vue";

import { apiClient } from "../lib/api";
import { useAutoTradingStore } from "../stores/autoTrading";

export function useDiagnosticsData() {
  const autoStore = useAutoTradingStore();
  const templates = ref([]);
  const loading = ref(false);
  const errorMessage = ref("");

  const strategies = computed(() => autoStore.configDraft.strategies || []);
  const enabledStrategies = computed(() => strategies.value.filter((item) => item.enabled));
  const recentDecisions = computed(() => [...(autoStore.decisions || [])].slice(-30).reverse());
  const blockedDecisions = computed(() =>
    recentDecisions.value.filter((item) => String(item.status || "").toLowerCase() === "blocked"),
  );
  const signalStats = computed(() => {
    const stats = { BUY: 0, SELL: 0, HOLD: 0, blocked: blockedDecisions.value.length };
    for (const item of recentDecisions.value) {
      const signal = String(item.signal || item.action || "HOLD").toUpperCase();
      if (signal in stats) stats[signal] += 1;
    }
    return stats;
  });

  async function refreshDiagnostics() {
    loading.value = true;
    errorMessage.value = "";
    try {
      const [templateResult] = await Promise.allSettled([
        apiClient.get("/crypto/strategies/templates"),
        autoStore.fetchStatus(),
      ]);
      if (templateResult.status === "fulfilled") {
        templates.value = templateResult.value.data.items || [];
      }
    } catch (error) {
      errorMessage.value = error?.response?.data?.message || error?.message || "刷新策略诊断失败";
    } finally {
      loading.value = false;
    }
  }

  return {
    templates,
    loading,
    errorMessage,
    strategies,
    enabledStrategies,
    recentDecisions,
    blockedDecisions,
    signalStats,
    refreshDiagnostics,
  };
}
