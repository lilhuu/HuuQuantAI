import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient, extractApiError } from "../lib/api";
import { getStoredToken } from "../lib/auth";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";

export const AI_CHAT_TIMEOUT_MS = 45000;

function buildChatPayload(payload, sessionId) {
  return {
    session_id: sessionId || null,
    message: String(payload.message || "").trim(),
    ...(payload.model ? { model: payload.model } : {}),
    ...(payload.current_route ? { current_route: payload.current_route } : {}),
    ...(payload.current_module ? { current_module: payload.current_module } : {}),
    ...(payload.current_view_title ? { current_view_title: payload.current_view_title } : {}),
    ...(payload.visible_context ? { visible_context: payload.visible_context } : {}),
    ...(typeof payload.guide_mode === "boolean" ? { guide_mode: payload.guide_mode } : {}),
    ...(payload.user_goal ? { user_goal: payload.user_goal } : {}),
    symbol: normalizeCryptoSymbol(payload.symbol || "BTC/USDT"),
    period: payload.period || "1h",
    limit: Number(payload.limit || 120),
    include_context: payload.include_context !== false,
  };
}

async function consumeEventStream(stream, onEvent) {
  if (!stream?.getReader) {
    throw new Error("浏览器未提供可读取的 AI 流式响应。");
  }
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consumeBlock = async (block) => {
    if (!block.trim()) return;
    let eventName = "message";
    const dataLines = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    const rawData = dataLines.join("\n");
    const data = rawData ? JSON.parse(rawData) : {};
    await onEvent(eventName, data);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) await consumeBlock(block);
    if (done) break;
  }
  if (buffer.trim()) await consumeBlock(buffer);
}

export const useAiChatStore = defineStore("ai-chat", () => {
  const drawerOpen = ref(false);
  const selectedModel = ref("deepseek-v4-flash");
  const loading = ref(false);
  const streaming = ref(false);
  const firstTokenReceived = ref(false);
  const unreadCount = ref(0);
  const streamError = ref("");
  const loadingSessions = ref(false);
  const errorMessage = ref("");
  const sessions = ref([]);
  const total = ref(0);
  const currentSession = ref(null);
  const messages = ref([]);
  let activeController = null;

  const hasMessages = computed(() => messages.value.length > 0);
  const petState = computed(() => {
    if (streamError.value || errorMessage.value) return "error";
    if (streaming.value && firstTokenReceived.value) return "speaking";
    if (streaming.value || loading.value) return "thinking";
    if (unreadCount.value > 0) return "attention";
    return "idle";
  });
  const latestActionCards = computed(() => {
    for (const message of [...messages.value].reverse()) {
      const cards = message?.context_summary?.action_cards;
      if (Array.isArray(cards) && cards.length) return cards;
    }
    return [];
  });

  function openDrawer() {
    drawerOpen.value = true;
    unreadCount.value = 0;
    if (!sessions.value.length) fetchSessions().catch(() => {});
  }

  function closeDrawer() {
    drawerOpen.value = false;
  }

  function setSelectedModel(model) {
    selectedModel.value = model === "deepseek-v4-pro" ? "deepseek-v4-pro" : "deepseek-v4-flash";
  }

  function stopGeneration() {
    if (activeController) activeController.abort();
  }

  function startNewSession() {
    if (streaming.value) stopGeneration();
    currentSession.value = null;
    messages.value = [];
    errorMessage.value = "";
    streamError.value = "";
    unreadCount.value = 0;
  }

  async function sendMessage(payload = {}) {
    const requestPayload = buildChatPayload(payload, currentSession.value?.session_id);
    if (!requestPayload.message) return null;
    loading.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.post("/crypto/ai/chat", requestPayload, { timeout: AI_CHAT_TIMEOUT_MS });
      currentSession.value = data.session;
      const assistantMessage = data.assistant_message
        ? {
            ...data.assistant_message,
            context_summary: data.assistant_message.context_summary || data.context_summary || {},
          }
        : null;
      messages.value = [...messages.value, data.user_message, assistantMessage].filter(Boolean);
      fetchSessions().catch(() => {});
      return data;
    } catch (error) {
      errorMessage.value =
        error?.code === "ECONNABORTED"
          ? "AI 助手响应超时，请稍后重试，或切换 Flash 模型后再发送。"
          : extractApiError(error) || "AI 对话请求失败";
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function sendMessageStream(payload = {}) {
    const requestPayload = buildChatPayload(payload, currentSession.value?.session_id);
    if (!requestPayload.message || streaming.value) return null;

    const stamp = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const tempUserId = `TEMP_USER_${stamp}`;
    const tempAssistantId = `TEMP_ASSISTANT_${stamp}`;
    messages.value = [
      ...messages.value,
      { message_id: tempUserId, role: "user", content: requestPayload.message, stream_status: "sending" },
      { message_id: tempAssistantId, role: "assistant", content: "", stream_status: "thinking" },
    ];
    loading.value = true;
    streaming.value = true;
    firstTokenReceived.value = false;
    errorMessage.value = "";
    streamError.value = "";
    activeController = new AbortController();

    const removeTemporaryMessages = () => {
      messages.value = messages.value.filter(
        (message) => message.message_id !== tempUserId && message.message_id !== tempAssistantId,
      );
    };

    try {
      const headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
      const token = typeof window !== "undefined" ? getStoredToken() : "";
      if (token) headers.Authorization = `Bearer ${token}`;
      const baseURL = String(apiClient.defaults.baseURL || "/api/v1").replace(/\/$/, "");
      const response = await fetch(`${baseURL}/crypto/ai/chat/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify(requestPayload),
        signal: activeController.signal,
      });
      if (!response.ok) throw new Error(`AI 流式请求失败（${response.status}）`);

      /** @type {Record<string, any> | null} */
      let completedResponse = null;
      await consumeEventStream(response.body, async (eventName, data) => {
        if (eventName === "delta") {
          const content = String(data.content || "");
          if (!content) return;
          firstTokenReceived.value = true;
          messages.value = messages.value.map((message) =>
            message.message_id === tempAssistantId
              ? { ...message, content: `${message.content || ""}${content}`, stream_status: "streaming" }
              : message,
          );
        } else if (eventName === "done") {
          completedResponse = data;
        } else if (eventName === "error") {
          const error = new Error(String(data.message || "AI 流式回复失败"));
          throw error;
        }
      });

      if (!completedResponse?.assistant_message) throw new Error("AI 流式回复没有完成事件。");
      const finalResponse = /** @type {Record<string, any>} */ (completedResponse);
      removeTemporaryMessages();
      currentSession.value = finalResponse.session;
      const assistantMessage = {
        ...finalResponse.assistant_message,
        context_summary:
          finalResponse.assistant_message.context_summary || finalResponse.context_summary || {},
      };
      messages.value = [...messages.value, finalResponse.user_message, assistantMessage].filter(Boolean);
      if (!drawerOpen.value) unreadCount.value += 1;
      fetchSessions().catch(() => {});
      return finalResponse;
    } catch (error) {
      if (error?.name === "AbortError") {
        removeTemporaryMessages();
        streamError.value = "已停止生成，本次临时回复未保存。";
        return null;
      }
      const temporaryAssistant = messages.value.find((message) => message.message_id === tempAssistantId);
      if (!temporaryAssistant?.content) {
        removeTemporaryMessages();
      } else {
        messages.value = messages.value.map((message) =>
          message.message_id === tempAssistantId ? { ...message, stream_status: "interrupted" } : message,
        );
      }
      streamError.value = error?.message || "AI 流式回复失败，请重试。";
      errorMessage.value = streamError.value;
      throw error;
    } finally {
      loading.value = false;
      streaming.value = false;
      activeController = null;
    }
  }

  async function fetchSessions(params = {}) {
    loadingSessions.value = true;
    try {
      const { data } = await apiClient.get("/crypto/ai/chat/sessions", { params: { limit: 50, ...params } });
      sessions.value = data.items || [];
      total.value = Number(data.total ?? data.count ?? sessions.value.length);
      return data;
    } finally {
      loadingSessions.value = false;
    }
  }

  async function loadSession(sessionId) {
    if (!sessionId) return null;
    if (streaming.value) stopGeneration();
    loadingSessions.value = true;
    errorMessage.value = "";
    streamError.value = "";
    try {
      const { data } = await apiClient.get(`/crypto/ai/chat/sessions/${sessionId}`);
      currentSession.value = data.session;
      messages.value = data.messages || [];
      unreadCount.value = 0;
      return data;
    } catch (error) {
      errorMessage.value = extractApiError(error) || "加载 AI 对话失败";
      throw error;
    } finally {
      loadingSessions.value = false;
    }
  }

  async function deleteSession(sessionId = currentSession.value?.session_id) {
    if (!sessionId) return null;
    await apiClient.delete(`/crypto/ai/chat/sessions/${sessionId}`);
    if (currentSession.value?.session_id === sessionId) startNewSession();
    await fetchSessions();
    return true;
  }

  return {
    drawerOpen,
    selectedModel,
    loading,
    streaming,
    firstTokenReceived,
    unreadCount,
    streamError,
    loadingSessions,
    errorMessage,
    sessions,
    total,
    currentSession,
    messages,
    hasMessages,
    petState,
    latestActionCards,
    openDrawer,
    closeDrawer,
    setSelectedModel,
    stopGeneration,
    startNewSession,
    sendMessage,
    sendMessageStream,
    fetchSessions,
    loadSession,
    deleteSession,
  };
});
