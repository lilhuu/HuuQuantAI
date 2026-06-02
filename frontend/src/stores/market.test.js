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
    expect(cryptoMarketStatusMessage("connected")).toBe("Binance 实时行情已连接");
    expect(cryptoMarketStatusMessage("error")).toBe("实时行情连接异常");
    expect(cryptoMarketStatusMessage("idle")).toBe("实时行情未连接");
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
});
