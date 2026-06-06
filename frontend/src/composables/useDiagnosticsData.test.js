import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useDiagnosticsData } from "./useDiagnosticsData";

describe("useDiagnosticsData", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("builds strategy and signal diagnostics from auto status", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { items: [{ type: "rsi", name: "RSI" }] },
    });
    const autoStore = useAutoTradingStore();
    vi.spyOn(autoStore, "fetchStatus").mockImplementation(async () => {
      autoStore.status = {
        config: {
          strategies: [{ strategy_id: "auto_rsi", type: "rsi", enabled: true, symbols: ["BTC/USDT"], weight: 1 }],
        },
        last_decisions: [
          { symbol: "BTC/USDT", signal: "BUY", status: "executed" },
          { symbol: "ETH/USDT", signal: "SELL", status: "blocked" },
        ],
      };
      autoStore.configDraft.strategies = autoStore.status.config.strategies;
      return autoStore.status;
    });

    const diagnostics = useDiagnosticsData();
    await diagnostics.refreshDiagnostics();

    expect(diagnostics.templates.value).toHaveLength(1);
    expect(diagnostics.enabledStrategies.value).toHaveLength(1);
    expect(diagnostics.signalStats.value.BUY).toBe(1);
    expect(diagnostics.signalStats.value.SELL).toBe(1);
    expect(diagnostics.signalStats.value.blocked).toBe(1);
  });
});
