import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";
import { cryptoMarketStatusMessage, uniqueCryptoSymbols, useMarketStore } from "./market";

describe("market store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("deduplicates and normalizes watch symbols", () => {
    expect(uniqueCryptoSymbols(["btcusdt", "BTC/USDT", "eth-usdt", "", null])).toEqual(["BTC/USDT", "ETH/USDT"]);
  });

  it("returns readable socket status messages", () => {
    expect(cryptoMarketStatusMessage("connecting")).toBe("正在连接 Binance 实时行情");
    expect(cryptoMarketStatusMessage("connected")).toBe("Binance 实时行情已连接");
    expect(cryptoMarketStatusMessage("snapshot_loading")).toBe("正在加载 REST 行情快照");
    expect(cryptoMarketStatusMessage("error")).toBe("实时行情连接异常");
    expect(cryptoMarketStatusMessage("idle")).toBe("实时行情未连接");
  });

  it("treats ALL as no quote filter and sorts full-market quotes by amount", () => {
    const store = useMarketStore();
    store.cryptoQuotes = [
      { symbol: "BTC/USDT", price: 50000, amount: 1000, change: 0.01 },
      { symbol: "ETH/BTC", price: 0.05, amount: 3000, change: -0.02 },
      { symbol: "SOL/USDT", price: 150, amount: 2000, change: 0.03 },
    ];
    store.quoteFilter = "ALL";
    store.quoteSortField = "amount";
    store.quoteSortDir = "desc";

    expect(store.filteredSortedQuotes.map((item) => item.symbol)).toEqual(["ETH/BTC", "SOL/USDT", "BTC/USDT"]);

    store.quoteFilter = "USDT";
    expect(store.filteredSortedQuotes.map((item) => item.symbol)).toEqual(["SOL/USDT", "BTC/USDT"]);
  });

  it("sorts quotes and updates watch symbols after REST refresh", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: {
        source: "binance",
        items: [
          { symbol: "ETH/USDT", price: 3000 },
          { symbol: "BTC/USDT", price: 50000 },
        ],
      },
    });
    const store = useMarketStore();
    const response = await store.fetchCryptoQuotes(["ethusdt", "btcusdt"]);

    expect(response.source).toBe("binance");
    expect(store.cryptoWatchSymbols).toEqual(["ETH/USDT", "BTC/USDT"]);
    expect(store.cryptoQuotes.map((item) => item.symbol)).toEqual(["BTC/USDT", "ETH/USDT"]);
  });

  it("passes market_type for futures quotes and derivative metrics", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({
        data: {
          source: "binance_um_futures",
          items: [{ symbol: "BTC/USDT", market_type: "um_futures", quote: "USDT", amount: 1000 }],
        },
      })
      .mockResolvedValueOnce({
        data: {
          market_type: "um_futures",
          symbol: "BTC/USDT",
          mark_price: 65010,
          funding_rate: 0.0001,
          open_interest: 12345,
        },
      });
    const store = useMarketStore();
    store.setMarketType("um_futures");

    await store.fetchCryptoQuotes(null, { quote: "USDT" });
    await store.fetchDerivativeMetrics("BTC/USDT");

    expect(get.mock.calls[0][1].params.market_type).toBe("um_futures");
    expect(get.mock.calls[1][0]).toBe("/crypto/derivatives/metrics");
    expect(get.mock.calls[1][1].params.market_type).toBe("um_futures");
    expect(store.derivativeMetrics.mark_price).toBe(65010);
  });

  it("reuses a fresh quote response for duplicate refreshes", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: {
        source: "binance",
        items: [
          { symbol: "ETH/USDT", price: 3000 },
          { symbol: "BTC/USDT", price: 50000 },
        ],
      },
    });
    const store = useMarketStore();

    const first = await store.fetchCryptoQuotes(["BTC/USDT", "ETH/USDT"]);
    const second = await store.fetchCryptoQuotes(["btcusdt", "ethusdt"]);

    expect(get).toHaveBeenCalledTimes(1);
    expect(second).toBe(first);
    expect(store.cryptoQuotes.map((item) => item.symbol)).toEqual(["BTC/USDT", "ETH/USDT"]);
  });
});
