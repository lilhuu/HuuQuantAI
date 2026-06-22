import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { normalizeConfig, useAutoTradingStore } from "./autoTrading";

describe("autoTrading store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("normalizes config into safe paper-only settings", () => {
    const config = normalizeConfig({
      mode: "live",
      symbols: ["btcusdt", "ETH-USDT", "bad/usdt", "btcusdt"],
      real_trading_enabled: true,
      max_positions: 8,
    });

    expect(config.mode).toBe("paper");
    expect(config.real_trading_enabled).toBe(false);
    expect(config.decision_mode).toBe("ai_supervised");
    expect(config.ai_model).toBe("deepseek-v4-pro");
    expect(config.ai_fallback_model).toBe("deepseek-v4-flash");
    expect(config.ai_confidence_threshold).toBe(0.65);
    expect(config.max_daily_loss).toBe(200);
    expect(config.symbols).toEqual(["BTC/USDT", "ETH/USDT", "BAD/USDT"]);
    expect(config.max_positions).toBe(8);
  });

  it("updates symbol drafts from comma-separated text", () => {
    const store = useAutoTradingStore();
    store.setSymbolsText("btcusdt, eth-usdt, sol");
    expect(store.configDraft.symbols).toEqual(["BTC/USDT", "ETH/USDT", "SOL/USDT"]);
    expect(store.symbolsText()).toBe("BTC/USDT, ETH/USDT, SOL/USDT");
  });

  it("exposes loop status fields from the backend payload", () => {
    const store = useAutoTradingStore();
    store.status = {
      state: "running",
      config: {},
      loop_running: true,
      next_run_at: "2026-06-02T10:00:00+00:00",
      last_error_type: "TimeoutError",
    };

    expect(store.stateLabel).toBe("运行中");
    expect(store.loopRunning).toBe(true);
    expect(store.nextRunAt).toBe("2026-06-02T10:00:00+00:00");
    expect(store.lastErrorType).toBe("TimeoutError");
  });
});
