import { computed } from "vue";

import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAiChatStore } from "../stores/aiChat";
import { useAuthStore } from "../stores/auth";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useUiStore } from "../stores/ui";
import { useWorkspaceStore } from "../stores/workspace";

export function useSettingsData() {
  const aiAdvisor = useAiAdvisorStore();
  const aiChat = useAiChatStore();
  const authStore = useAuthStore();
  const autoStore = useAutoTradingStore();
  const marketStore = useMarketStore();
  const systemStore = useSystemStore();
  const uiStore = useUiStore();
  const workspaceStore = useWorkspaceStore();

  const safetySettings = computed(() => [
    { label: "真实交易", value: autoStore.configDraft.real_trading_enabled ? "异常：已开启" : "关闭", tone: "status-chip--idle" },
    { label: "账户模式", value: "Binance 模拟", tone: "status-chip--connected" },
    { label: "AI 下单权限", value: "仅建议，不下单", tone: "status-chip--idle" },
    { label: "自动交易模式", value: autoStore.configDraft.mode || "paper", tone: "status-chip--idle" },
  ]);

  const connectionSettings = computed(() => [
    { label: "行情 WebSocket", value: marketStore.marketSocketState || "idle" },
    { label: "系统 WebSocket", value: systemStore.systemSocketState || "idle" },
    { label: "当前交易对", value: marketStore.selectedCryptoSymbol || "-" },
    { label: "监听列表", value: (marketStore.cryptoWatchSymbols || []).join(", ") || "-" },
  ]);

  const aiSettings = computed(() => [
    { label: "AI 信号状态", value: aiAdvisor.errorMessage ? "需要配置或检查" : "待命" },
    { label: "AI 对话状态", value: aiChat.errorMessage ? "需要配置或检查" : "待命" },
    { label: "模型切换", value: "由 AI 对话抽屉选择" },
    { label: "API Key", value: "仅从环境变量读取" },
  ]);

  const preferenceSettings = computed(() => [
    { label: "偏好已加载", value: workspaceStore.preferencesHydrated ? "是" : "否" },
    { label: "提醒音效", value: uiStore.soundEnabled ? "开启" : "关闭" },
    { label: "当前用户", value: authStore.user?.username || "admin" },
    { label: "登录状态", value: authStore.isAuthenticated ? "已登录" : "未登录" },
  ]);

  async function refreshSettings() {
    await Promise.allSettled([authStore.refreshStatus(), autoStore.fetchStatus(), systemStore.refreshOverview()]);
  }

  return {
    safetySettings,
    connectionSettings,
    aiSettings,
    preferenceSettings,
    soundEnabled: computed({
      get: () => uiStore.soundEnabled,
      set: (value) => uiStore.setSoundEnabled(value),
    }),
    refreshSettings,
  };
}
