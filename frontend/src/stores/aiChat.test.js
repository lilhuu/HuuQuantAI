import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";
import { useAiChatStore } from "./aiChat";

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
    expect(apiClient.post).toHaveBeenCalledWith("/crypto/ai/chat", {
      session_id: null,
      message: "分析 BTC",
      symbol: "BTC/USDT",
      period: "1h",
      limit: 120,
      include_context: true,
    });
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
    );
  });
});
