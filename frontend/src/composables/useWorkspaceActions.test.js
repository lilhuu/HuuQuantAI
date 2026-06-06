import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useWorkspaceActions } from "./useWorkspaceActions";

describe("useWorkspaceActions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("exposes normalized pair options and selected quote display data", () => {
    const marketStore = useMarketStore();
    marketStore.cryptoWatchSymbols = ["btcusdt", "ETH-USDT", "BTC/USDT"];
    marketStore.selectedCryptoSymbol = "BTC/USDT";
    marketStore.cryptoQuotes = [{ symbol: "BTC/USDT", price: 69420.25, change: -0.0123 }];

    const workspace = useWorkspaceActions();

    expect(workspace.pairOptions.value).toEqual(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]);
    expect(workspace.priceText.value).toBe("69,420.25");
    expect(workspace.changeText.value).toBe("-1.23%");
    expect(workspace.changeClass.value).toBe("number-down");
  });

  it("normalizes the selected symbol, refreshes market data, and updates socket subscriptions", async () => {
    const marketStore = useMarketStore();
    marketStore.selectedCryptoSymbol = "dogeusdt";

    const fetchQuotes = vi.spyOn(marketStore, "fetchCryptoQuotes").mockResolvedValue({});
    const fetchKlines = vi.spyOn(marketStore, "fetchCryptoKlines").mockResolvedValue({});
    const subscribe = vi.spyOn(marketStore, "subscribeMarketSocket").mockImplementation(() => {});

    const workspace = useWorkspaceActions();
    await workspace.changeSymbol();

    expect(marketStore.selectedCryptoSymbol).toBe("DOGE/USDT");
    expect(marketStore.cryptoWatchSymbols).toContain("DOGE/USDT");
    expect(fetchQuotes).toHaveBeenCalledWith(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]);
    expect(fetchKlines).toHaveBeenCalledWith({ symbol: "DOGE/USDT", period: "1h", limit: 200 });
    expect(subscribe).toHaveBeenCalledWith(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]);
  });

  it("refreshes account, automation status, quotes, and klines together", async () => {
    const autoStore = useAutoTradingStore();
    const marketStore = useMarketStore();
    const systemStore = useSystemStore();

    const refreshOverview = vi.spyOn(systemStore, "refreshOverview").mockResolvedValue(undefined);
    const fetchStatus = vi.spyOn(autoStore, "fetchStatus").mockResolvedValue({});
    const fetchQuotes = vi.spyOn(marketStore, "fetchCryptoQuotes").mockResolvedValue({});
    const fetchKlines = vi.spyOn(marketStore, "fetchCryptoKlines").mockResolvedValue({});

    const workspace = useWorkspaceActions();
    await workspace.refreshWorkspace();

    expect(refreshOverview).toHaveBeenCalledTimes(1);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    expect(fetchQuotes).toHaveBeenCalledWith(marketStore.cryptoWatchSymbols);
    expect(fetchKlines).toHaveBeenCalledWith({ symbol: "BTC/USDT", period: "1h", limit: 200 });
  });
});
