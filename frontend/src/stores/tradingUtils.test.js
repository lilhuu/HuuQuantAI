import { describe, expect, it } from "vitest";

import {
  badgeClassForOrder,
  eventToneFromType,
  formatPrice,
  formatUsdt,
  normalizeCryptoSymbol,
  sortOrders,
  toneFromSocketState,
} from "./tradingUtils";

describe("tradingUtils", () => {
  it("normalizes crypto symbols into BASE/QUOTE form", () => {
    expect(normalizeCryptoSymbol("btcusdt")).toBe("BTC/USDT");
    expect(normalizeCryptoSymbol("eth-usdt")).toBe("ETH/USDT");
    expect(normalizeCryptoSymbol("sol_usdt")).toBe("SOL/USDT");
    expect(normalizeCryptoSymbol("doge", "USDT")).toBe("DOGE/USDT");
    expect(normalizeCryptoSymbol("")).toBe("");
  });

  it("formats prices, USDT values, and percent values deterministically", () => {
    expect(formatPrice("1234.56789")).toBe("1,234.56789");
    expect(formatUsdt(1234.5)).toContain("1,234.50");
  });

  it("sorts orders by created or filled time descending", () => {
    const orders = [
      { order_id: "old", created_time: "2026-05-20T00:00:00Z" },
      { order_id: "new", filled_time: "2026-05-22T00:00:00Z" },
    ];
    expect(sortOrders(orders).map((item) => item.order_id)).toEqual(["new", "old"]);
  });

  it("maps socket and order states to UI tones", () => {
    expect(toneFromSocketState("connected")).toBe("connected");
    expect(toneFromSocketState("reconnecting")).toBe("connecting");
    expect(toneFromSocketState("error")).toBe("error");
    expect(badgeClassForOrder("filled")).toBe("badge-live");
    expect(badgeClassForOrder("rejected")).toBe("badge-danger");
    expect(eventToneFromType("order_rejected")).toBe("error");
  });
});
