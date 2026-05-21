import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient } from "../lib/api";

export const usePortfolioStore = defineStore("portfolio", () => {
  const analytics = ref(null);
  const loading = ref(false);
  const mode = ref("live");
  const range = ref("30d");
  const error = ref("");

  const equityCurve = computed(() => analytics.value?.equity_curve || []);
  const summary = computed(() => analytics.value?.summary || {});
  const bySymbol = computed(() => analytics.value?.by_symbol || []);
  const byStrategy = computed(() => analytics.value?.by_strategy || []);
  const history = computed(() => analytics.value?.history || []);

  async function fetchAnalytics(payload = {}) {
    loading.value = true;
    error.value = "";
    try {
      const { data } = await apiClient.post("/crypto/portfolio/returns", {
        mode: mode.value,
        range: range.value,
        limit: 200,
        ...payload,
      });
      analytics.value = data;
      return data;
    } catch (requestError) {
      error.value = requestError?.response?.data?.message || requestError?.message || "组合收益加载失败";
      throw requestError;
    } finally {
      loading.value = false;
    }
  }

  return {
    analytics,
    loading,
    mode,
    range,
    error,
    equityCurve,
    summary,
    bySymbol,
    byStrategy,
    history,
    fetchAnalytics,
  };
});
