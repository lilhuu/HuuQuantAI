import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAuthStore } from "../stores/auth";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useTradingStore } from "../stores/trading";
import { useBoot } from "./useBoot";
import { useToast } from "./useToast";

describe("useBoot", () => {
  beforeEach(() => {
    const storage = new Map();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn((key) => storage.get(key) || null),
        setItem: vi.fn((key, value) => storage.set(key, String(value))),
        removeItem: vi.fn((key) => storage.delete(key)),
      },
    });
    setActivePinia(createPinia());
    useToast().clearError();
    vi.restoreAllMocks();
  });

  it("does not initialize workspace data when the user is not authenticated", async () => {
    const authStore = useAuthStore();
    const tradingStore = useTradingStore();
    const autoStore = useAutoTradingStore();

    vi.spyOn(authStore, "ensureInitialized").mockResolvedValue(undefined);
    const loadPreferences = vi.spyOn(tradingStore, "loadUserPreferences").mockResolvedValue(null);
    const bootstrap = vi.spyOn(tradingStore, "bootstrap").mockResolvedValue(undefined);
    const fetchStatus = vi.spyOn(autoStore, "fetchStatus").mockResolvedValue(null);

    const { initializeWorkbench } = useBoot();
    await expect(initializeWorkbench()).resolves.toBe(false);

    expect(authStore.ensureInitialized).toHaveBeenCalledTimes(1);
    expect(loadPreferences).not.toHaveBeenCalled();
    expect(bootstrap).not.toHaveBeenCalled();
    expect(fetchStatus).not.toHaveBeenCalled();
  });

  it("initializes preferences, workspace data, auto status, and realtime streams for authenticated users", async () => {
    const authStore = useAuthStore();
    const tradingStore = useTradingStore();
    const autoStore = useAutoTradingStore();
    const calls = [];

    authStore.token = "token";
    authStore.user = { username: "admin" };

    vi.spyOn(authStore, "ensureInitialized").mockImplementation(async () => {
      calls.push("auth");
    });
    vi.spyOn(tradingStore, "loadUserPreferences").mockImplementation(async () => {
      calls.push("preferences");
      return null;
    });
    vi.spyOn(tradingStore, "bootstrap").mockImplementation(async () => {
      calls.push("bootstrap");
    });
    vi.spyOn(autoStore, "fetchStatus").mockImplementation(async () => {
      calls.push("auto-status");
      return null;
    });
    vi.spyOn(tradingStore, "connectRealtimeStreams").mockImplementation(() => {
      calls.push("sockets");
    });

    const { initializeWorkbench, isBooting, lastBootError } = useBoot();
    await expect(initializeWorkbench()).resolves.toBe(true);

    expect(isBooting.value).toBe(false);
    expect(lastBootError.value).toBeNull();
    expect(calls[0]).toBe("auth");
    expect(calls[1]).toBe("preferences");
    expect(calls).toContain("bootstrap");
    expect(calls).toContain("auto-status");
    expect(calls.at(-1)).toBe("sockets");
  });

  it("disconnects realtime streams and resets state during teardown", () => {
    const tradingStore = useTradingStore();
    const disconnect = vi.spyOn(tradingStore, "disconnectRealtimeStreams").mockImplementation(() => {});
    const reset = vi.spyOn(tradingStore, "resetState").mockImplementation(() => {});

    const { teardownWorkbench } = useBoot();
    teardownWorkbench({ reset: true });

    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(reset).toHaveBeenCalledTimes(1);
  });
});
