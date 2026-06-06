import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient } from "../lib/api";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useSystemStore } from "./system";

export const useAiAdvisorStore = defineStore("ai-advisor", () => {
  const loading = ref(false);
  const ordering = ref(false);
  const errorMessage = ref("");
  const currentSignal = ref(null);
  const signals = ref([]);
  const total = ref(0);

  const approved = computed(() => currentSignal.value?.approval_status === "approved");

  async function analyze(payload) {
    loading.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.post("/crypto/ai/analyze", {
        symbol: normalizeCryptoSymbol(payload.symbol),
        period: payload.period || "1h",
        limit: Number(payload.limit || 120),
      });
      currentSignal.value = data.signal;
      await fetchSignals();
      return data;
    } catch (error) {
      errorMessage.value = error?.response?.data?.message || error?.message || "AI 分析失败";
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function fetchSignals(params = {}) {
    const { data } = await apiClient.get("/crypto/ai/signals", {
      params: { limit: 50, ...params },
    });
    signals.value = data.items || [];
    total.value = Number(data.total ?? data.count ?? signals.value.length);
    if (!currentSignal.value && signals.value.length) {
      currentSignal.value = signals.value[0];
    }
    return data;
  }

  async function fetchSignal(signalId) {
    const { data } = await apiClient.get(`/crypto/ai/signals/${signalId}`);
    currentSignal.value = data;
    return data;
  }

  async function createPaperOrder(signalId = currentSignal.value?.signal_id) {
    if (!signalId) {
      return null;
    }
    ordering.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.post(`/crypto/ai/signals/${signalId}/paper-order`);
      currentSignal.value = data.signal;
      await Promise.all([fetchSignals(), useSystemStore().refreshOverview()]);
      return data;
    } catch (error) {
      errorMessage.value = error?.response?.data?.message || error?.message || "生成模拟订单失败";
      throw error;
    } finally {
      ordering.value = false;
    }
  }

  function selectSignal(signal) {
    currentSignal.value = signal;
  }

  return {
    loading,
    ordering,
    errorMessage,
    currentSignal,
    signals,
    total,
    approved,
    analyze,
    fetchSignals,
    fetchSignal,
    createPaperOrder,
    selectSignal,
  };
});
