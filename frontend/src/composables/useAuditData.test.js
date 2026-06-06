import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useAuditData } from "./useAuditData";

describe("useAuditData", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("aggregates safety, blocked decisions, order lifecycle, and rejected logs", () => {
    const autoStore = useAutoTradingStore();
    const marketStore = useMarketStore();
    const systemStore = useSystemStore();

    marketStore.marketSocketState = "connected";
    autoStore.status = {
      enabled: true,
      state: "running",
      config: {},
      last_decisions: [{ symbol: "BTC/USDT", strategy_id: "rsi", status: "blocked", reason: "macro gate" }],
    };
    systemStore.cryptoOrders = [{ order_id: "1", symbol: "BTC/USDT", action: "BUY", quantity: 0.01, status: "filled" }];
    systemStore.cryptoLogs = [{ event: "order_rejected", message: "risk reject", timestamp: "2026-06-01T00:00:00Z" }];

    const audit = useAuditData();

    expect(audit.safetyItems.value.find((item) => item.label === "自动交易")?.value).toBe("运行中");
    expect(audit.blockedDecisions.value).toHaveLength(1);
    expect(audit.orderLifecycle.value[0]).toMatchObject({ symbol: "BTC/USDT", tone: "badge-live" });
    expect(audit.rejectedLogs.value).toHaveLength(1);
  });
});
