import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";
import { AI_CHAT_TIMEOUT_MS, useAiChatStore } from "./aiChat";

describe("aiChat store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("sends a chat message and appends persisted messages", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        session: { session_id: "AICHAT_1", title: "BTC 风险", message_count: 2 },
        user_message: { message_id: "U1", role: "user", content: "分析 BTC" },
        assistant_message: { message_id: "A1", role: "assistant", content: "模拟研究建议" },
      },
    });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { items: [{ session_id: "AICHAT_1", title: "BTC 风险" }], total: 1 },
    });

    const store = useAiChatStore();
    const response = await store.sendMessage({ message: "分析 BTC", symbol: "btcusdt", period: "1h", limit: 120 });

    expect(response.session.session_id).toBe("AICHAT_1");
    expect(store.currentSession.session_id).toBe("AICHAT_1");
    expect(store.messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(apiClient.post).toHaveBeenCalledWith(
      "/crypto/ai/chat",
      {
        session_id: null,
        message: "分析 BTC",
        symbol: "BTC/USDT",
        period: "1h",
        limit: 120,
        include_context: true,
      },
      expect.objectContaining({ timeout: AI_CHAT_TIMEOUT_MS }),
    );
  });

  it("loads and deletes the current chat session", async () => {
    vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({
        data: {
          session: { session_id: "AICHAT_1", title: "历史" },
          messages: [{ message_id: "A1", role: "assistant", content: "历史回复" }],
        },
      })
      .mockResolvedValueOnce({ data: { items: [], total: 0 } });
    vi.spyOn(apiClient, "delete").mockResolvedValueOnce({ data: { success: true } });

    const store = useAiChatStore();
    await store.loadSession("AICHAT_1");
    expect(store.currentSession.title).toBe("历史");
    expect(store.messages).toHaveLength(1);

    await store.deleteSession("AICHAT_1");
    expect(store.currentSession).toBeNull();
    expect(store.messages).toEqual([]);
    expect(apiClient.delete).toHaveBeenCalledWith("/crypto/ai/chat/sessions/AICHAT_1");
  });

  it("sends the selected DeepSeek model when provided", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        session: { session_id: "AICHAT_2", title: "model", message_count: 2 },
        user_message: { message_id: "U2", role: "user", content: "Analyze BTC" },
        assistant_message: { message_id: "A2", role: "assistant", content: "Pro reply", model: "deepseek-v4-pro" },
      },
    });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: { items: [], total: 0 } });

    const store = useAiChatStore();
    await store.sendMessage({
      message: "Analyze BTC",
      symbol: "BTC/USDT",
      model: "deepseek-v4-pro",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/crypto/ai/chat",
      expect.objectContaining({ model: "deepseek-v4-pro" }),
      expect.objectContaining({ timeout: AI_CHAT_TIMEOUT_MS }),
    );
  });

  it("passes current page context when provided", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        session: { session_id: "AICHAT_3", title: "risk", message_count: 2 },
        user_message: { message_id: "U3", role: "user", content: "这个是什么意思？" },
        assistant_message: { message_id: "A3", role: "assistant", content: "这是风控阻断说明。" },
      },
    });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: { items: [], total: 0 } });

    const store = useAiChatStore();
    await store.sendMessage({
      message: "这个是什么意思？",
      symbol: "BTC/USDT",
      current_route: "/risk",
      current_module: "risk",
      current_view_title: "风控中心",
      visible_context: { risk_state: "blocked" },
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/crypto/ai/chat",
      expect.objectContaining({
        current_route: "/risk",
        current_module: "risk",
        current_view_title: "风控中心",
        visible_context: { risk_state: "blocked" },
      }),
      expect.objectContaining({ timeout: AI_CHAT_TIMEOUT_MS }),
    );
  });

  it("passes guide mode and user goal when provided", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        session: { session_id: "AICHAT_4", title: "guide", message_count: 2 },
        user_message: { message_id: "U4", role: "user", content: "run a strategy backtest" },
        assistant_message: { message_id: "A4", role: "assistant", content: "Follow the guide steps." },
      },
    });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: { items: [], total: 0 } });

    const store = useAiChatStore();
    await store.sendMessage({
      message: "run a strategy backtest",
      symbol: "BTC/USDT",
      guide_mode: true,
      user_goal: "strategy_backtest",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/crypto/ai/chat",
      expect.objectContaining({
        guide_mode: true,
        user_goal: "strategy_backtest",
      }),
      expect.objectContaining({ timeout: AI_CHAT_TIMEOUT_MS }),
    );
  });

  it("keeps the assistant reply when session refresh fails", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        session: { session_id: "AICHAT_REFRESH", title: "refresh", message_count: 2 },
        user_message: { message_id: "U_REFRESH", role: "user", content: "分析 SOL" },
        assistant_message: { message_id: "A_REFRESH", role: "assistant", content: "SOL 模拟分析" },
      },
    });
    vi.spyOn(apiClient, "get").mockRejectedValueOnce(new Error("session refresh failed"));

    const store = useAiChatStore();
    const response = await store.sendMessage({ message: "分析 SOL", symbol: "SOL/USDT" });

    expect(response.session.session_id).toBe("AICHAT_REFRESH");
    expect(store.messages.map((message) => message.message_id)).toEqual(["U_REFRESH", "A_REFRESH"]);
    expect(store.errorMessage).toBe("");
  });

  it("recovers loading state and shows an AI-specific timeout message", async () => {
    vi.spyOn(apiClient, "post").mockRejectedValueOnce({ code: "ECONNABORTED" });

    const store = useAiChatStore();
    await expect(store.sendMessage({ message: "分析 DOGE", symbol: "DOGE/USDT" })).rejects.toMatchObject({
      code: "ECONNABORTED",
    });

    expect(store.loading).toBe(false);
    expect(store.errorMessage).toContain("AI 助手响应超时");
  });

  it("keeps safe action cards from the latest assistant context", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: {
        session: { session_id: "AICHAT_5", title: "cards", message_count: 2 },
        user_message: { message_id: "U5", role: "user", content: "show me risk" },
        assistant_message: { message_id: "A5", role: "assistant", content: "Open risk center." },
        context_summary: {
          action_cards: [
            {
              id: "risk_block_explanation",
              title: "查看风控阻断",
              description: "打开风控中心查看阻断原因",
              action_type: "navigate",
              target_route: "/risk",
              risk_level: "safe",
            },
          ],
        },
      },
    });
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: { items: [], total: 0 } });

    const store = useAiChatStore();
    await store.sendMessage({ message: "show me risk", symbol: "BTC/USDT" });

    expect(store.latestActionCards).toHaveLength(1);
    expect(store.latestActionCards[0]).toMatchObject({
      action_type: "navigate",
      target_route: "/risk",
    });
    expect(store.messages.at(-1).context_summary.action_cards).toHaveLength(1);
  });
});
