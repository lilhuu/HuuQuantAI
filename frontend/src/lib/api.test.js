import { describe, expect, it } from "vitest";

import { classifyApiError, extractApiError } from "./api";

describe("classifyApiError", () => {
  it("classifies auth, risk, and strategy business errors", () => {
    expect(classifyApiError({ response: { status: 401, data: { detail: "expired" } } })).toMatchObject({
      type: "auth",
      title: "登录已失效",
      message: "expired",
    });
    expect(classifyApiError({ response: { status: 400, data: { error_code: "risk.rejected", message: "blocked" } } })).toMatchObject({
      type: "risk",
      title: "风控拒绝",
      message: "blocked",
    });
    expect(classifyApiError({ response: { status: 400, data: { error_code: "strategy.config_invalid" } } })).toMatchObject({
      type: "strategy",
    });
  });

  it("classifies validation, server, timeout, and network errors", () => {
    expect(classifyApiError({ response: { status: 422, data: { error_code: "request.validation_failed" } } })).toMatchObject({
      type: "validation",
    });
    expect(classifyApiError({ response: { status: 503, data: { message: "down" } } })).toMatchObject({
      type: "server",
      message: "down",
    });
    expect(classifyApiError({ code: "ECONNABORTED" })).toMatchObject({ type: "network", title: "请求超时" });
    expect(extractApiError(new Error("offline"))).toBe("offline");
  });
});
