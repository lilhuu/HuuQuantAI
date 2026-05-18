import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient, classifyApiError } from "../lib/api";

export const useSystemStore = defineStore("trading-system", () => {
  const loading = ref(false);
  const errorMessage = ref("");
  const errorInfo = ref(null);
  const cryptoAccount = ref(null);
  const cryptoPositions = ref([]);
  const cryptoOrders = ref([]);
  const cryptoOrdersTotal = ref(0);
  const cryptoEquityCurve = ref([]);
  const cryptoLogs = ref([]);
  const cryptoLoading = ref(false);
  const systemSocketState = ref("idle");
  const lastSystemMessageAt = ref("");

  const liveAccountValue = computed(() => Number(cryptoAccount.value?.equity ?? 0));
  const liveCash = computed(() => Number(cryptoAccount.value?.cash ?? 0));
  const livePositionValue = computed(() => Number(cryptoAccount.value?.market_value ?? 0));

  async function refreshOverview() {
    loading.value = true;
    errorMessage.value = "";
    try {
      await Promise.all([
        fetchCryptoPaperAccount(),
        fetchCryptoPaperPositions(),
        fetchCryptoPaperOrders(),
        fetchCryptoPaperEquityCurve(),
        fetchCryptoPaperLogs(),
      ]);
    } catch (error) {
      setError(error, "刷新加密货币账户失败");
    } finally {
      loading.value = false;
    }
  }

  async function fetchCryptoPaperAccount() {
    const { data } = await apiClient.get("/crypto/paper/account");
    cryptoAccount.value = data;
    return data;
  }

  async function fetchCryptoPaperPositions() {
    const { data } = await apiClient.get("/crypto/paper/positions");
    cryptoPositions.value = data.items || [];
    return data;
  }

  async function fetchCryptoPaperOrders(params = {}) {
    const { data } = await apiClient.get("/crypto/paper/orders", {
      params: { limit: 50, ...params },
    });
    cryptoOrders.value = data.items || [];
    cryptoOrdersTotal.value = Number(data.total ?? data.count ?? cryptoOrders.value.length);
    return data;
  }

  async function placeCryptoPaperOrder(payload) {
    cryptoLoading.value = true;
    try {
      const { data } = await apiClient.post("/crypto/paper/orders", payload);
      await Promise.all([
        fetchCryptoPaperAccount(),
        fetchCryptoPaperPositions(),
        fetchCryptoPaperOrders(),
        fetchCryptoPaperEquityCurve(),
        fetchCryptoPaperLogs(),
      ]);
      return data;
    } finally {
      cryptoLoading.value = false;
    }
  }

  async function cancelCryptoPaperOrder(orderId) {
    const { data } = await apiClient.delete(`/crypto/paper/orders/${orderId}`);
    await Promise.all([fetchCryptoPaperOrders(), fetchCryptoPaperEquityCurve(), fetchCryptoPaperLogs()]);
    return data;
  }

  async function fetchCryptoPaperEquityCurve() {
    const { data } = await apiClient.get("/crypto/paper/equity-curve", { params: { limit: 200 } });
    cryptoEquityCurve.value = data.items || [];
    return data;
  }

  async function fetchCryptoPaperLogs() {
    const { data } = await apiClient.get("/crypto/paper/logs", { params: { limit: 80 } });
    cryptoLogs.value = data.items || [];
    return data;
  }

  function connectSystemSocket() {
    systemSocketState.value = "idle";
  }

  function disconnectSystemSocket() {
    systemSocketState.value = "idle";
  }

  function schedulePortfolioRefresh(delayMs = 180) {
    setTimeout(() => {
      refreshOverview();
    }, delayMs);
  }

  function setError(error, fallbackMessage = "请求失败") {
    const nextError = classifyApiError(error);
    errorInfo.value = {
      ...nextError,
      message: nextError.message || fallbackMessage,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    };
    errorMessage.value = errorInfo.value.message;
  }

  function clearError() {
    errorInfo.value = null;
    errorMessage.value = "";
  }

  function resetSystemState() {
    cryptoAccount.value = null;
    cryptoPositions.value = [];
    cryptoOrders.value = [];
    cryptoOrdersTotal.value = 0;
    cryptoEquityCurve.value = [];
    cryptoLogs.value = [];
    cryptoLoading.value = false;
    loading.value = false;
    systemSocketState.value = "idle";
    lastSystemMessageAt.value = "";
    clearError();
  }

  return {
    loading,
    errorMessage,
    errorInfo,
    cryptoAccount,
    cryptoPositions,
    cryptoOrders,
    cryptoOrdersTotal,
    cryptoEquityCurve,
    cryptoLogs,
    cryptoLoading,
    systemSocketState,
    lastSystemMessageAt,
    liveAccountValue,
    liveCash,
    livePositionValue,
    refreshOverview,
    fetchCryptoPaperAccount,
    fetchCryptoPaperPositions,
    fetchCryptoPaperOrders,
    placeCryptoPaperOrder,
    cancelCryptoPaperOrder,
    fetchCryptoPaperEquityCurve,
    fetchCryptoPaperLogs,
    setError,
    clearError,
    connectSystemSocket,
    disconnectSystemSocket,
    schedulePortfolioRefresh,
    resetSystemState,
  };
});
