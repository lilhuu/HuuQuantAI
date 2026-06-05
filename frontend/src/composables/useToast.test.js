import { beforeEach, describe, expect, it } from "vitest";

import { useToast } from "./useToast";

describe("useToast", () => {
  beforeEach(() => {
    useToast().clearError();
  });

  it("sets an error with the provided fallback message", () => {
    const { errorInfo, setError } = useToast();

    setError({}, "初始化失败");

    expect(errorInfo.value).toMatchObject({
      message: "初始化失败",
      type: "network",
    });
    expect(errorInfo.value.timestamp).toBeTruthy();
  });

  it("keeps explicit error messages and clears the current error", () => {
    const { errorInfo, setError, clearError } = useToast();

    setError(new Error("socket closed"), "界面异常");
    expect(errorInfo.value.message).toBe("socket closed");

    clearError();
    expect(errorInfo.value).toBeNull();
  });
});
