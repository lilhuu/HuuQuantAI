import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient, extractApiError } from "../lib/api";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";

export const useAiChatStore = defineStore("ai-chat", () => {
  const drawerOpen = ref(false);
  const loading = ref(false);
  const loadingSessions = ref(false);
  const errorMessage = ref("");
  const sessions = ref([]);
  const total = ref(0);
  const currentSession = ref(null);
  const messages = ref([]);

  const hasMessages = computed(() => messages.value.length > 0);

  function openDrawer() {
    drawerOpen.value = true;
    if (!sessions.value.length) {
      fetchSessions().catch(() => {});
    }
  }

  function closeDrawer() {
    drawerOpen.value = false;
  }

  function startNewSession() {
    currentSession.value = null;
    messages.value = [];
    errorMessage.value = "";
  }

  async function sendMessage(payload = {}) {
    const message = String(payload.message || "").trim();
    if (!message) {
      return null;
    }
    loading.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.post("/crypto/ai/chat", {
        session_id: currentSession.value?.session_id || null,
        message,
        ...(payload.model ? { model: payload.model } : {}),
        symbol: normalizeCryptoSymbol(payload.symbol || "BTC/USDT"),
        period: payload.period || "1h",
        limit: Number(payload.limit || 120),
        include_context: payload.include_context !== false,
      });
      currentSession.value = data.session;
      messages.value = [...messages.value, data.user_message, data.assistant_message].filter(Boolean);
      await fetchSessions();
      return data;
    } catch (error) {
      errorMessage.value = extractApiError(error) || "AI 对话请求失败";
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function fetchSessions(params = {}) {
    loadingSessions.value = true;
    try {
      const { data } = await apiClient.get("/crypto/ai/chat/sessions", {
        params: { limit: 50, ...params },
      });
      sessions.value = data.items || [];
      total.value = Number(data.total ?? data.count ?? sessions.value.length);
      return data;
    } finally {
      loadingSessions.value = false;
    }
  }

  async function loadSession(sessionId) {
    if (!sessionId) {
      return null;
    }
    loadingSessions.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.get(`/crypto/ai/chat/sessions/${sessionId}`);
      currentSession.value = data.session;
      messages.value = data.messages || [];
      return data;
    } catch (error) {
      errorMessage.value = extractApiError(error) || "加载 AI 对话失败";
      throw error;
    } finally {
      loadingSessions.value = false;
    }
  }

  async function deleteSession(sessionId = currentSession.value?.session_id) {
    if (!sessionId) {
      return null;
    }
    await apiClient.delete(`/crypto/ai/chat/sessions/${sessionId}`);
    if (currentSession.value?.session_id === sessionId) {
      startNewSession();
    }
    await fetchSessions();
    return true;
  }

  return {
    drawerOpen,
    loading,
    loadingSessions,
    errorMessage,
    sessions,
    total,
    currentSession,
    messages,
    hasMessages,
    openDrawer,
    closeDrawer,
    startNewSession,
    sendMessage,
    fetchSessions,
    loadSession,
    deleteSession,
  };
});
