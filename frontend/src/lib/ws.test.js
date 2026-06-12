// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";

import { createCryptoSocket } from "./ws";

describe("createCryptoSocket", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "WebSocket",
      vi.fn(function WebSocket(url) {
        this.url = url;
      }),
    );
  });

  it("uses Binance all-market mode without appending a large symbols query", () => {
    const socket = createCryptoSocket({
      allMarket: true,
      selectedSymbol: "BTC/USDT",
      period: "1h",
      depthLimit: 20,
      symbols: ["BTC/USDT", "ETH/BTC"],
      marketType: "um_futures",
    });

    expect(socket.url).toContain("all_market=1");
    expect(socket.url).toContain("market_type=um_futures");
    expect(socket.url).toContain("selected_symbol=BTC%2FUSDT");
    expect(socket.url).not.toContain("symbols=");
  });
});
