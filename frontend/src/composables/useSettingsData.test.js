import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAuthStore } from "../stores/auth";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useUiStore } from "../stores/ui";
import { useSettingsData } from "./useSettingsData";

describe("useSettingsData", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    const storage = new Map();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn((key) => storage.get(key) || null),
        setItem: vi.fn((key, value) => storage.set(key, String(value))),
        removeItem: vi.fn((key) => storage.delete(key)),
      },
    });
    setActivePinia(createPinia());
  });

  it("maps safety, connection, AI, and preference settings", () => {
    const authStore = useAuthStore();
    const autoStore = useAutoTradingStore();
    const marketStore = useMarketStore();
    const uiStore = useUiStore();

    authStore.token = "token";
    authStore.user = { username: "admin" };
    autoStore.configDraft.real_trading_enabled = true;
    marketStore.selectedCryptoSymbol = "ETH/USDT";

    const settings = useSettingsData();

    expect(settings.safetySettings.value[0].value).toContain("异常");
    expect(settings.connectionSettings.value.find((item) => item.label === "当前交易对")?.value).toBe("ETH/USDT");
    expect(settings.preferenceSettings.value.find((item) => item.label === "当前用户")?.value).toBe("admin");

    settings.soundEnabled.value = false;
    expect(uiStore.soundEnabled).toBe(false);
  });
});
