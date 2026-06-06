// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { shallowMount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";

vi.mock("vue-router", async () => {
  const actual = await vi.importActual("vue-router");
  return {
    ...actual,
    useRoute: () => ({ path: "/", query: {}, meta: {} }),
    useRouter: () => ({ push: vi.fn() }),
  };
});

const viewModules = {
  AccountView: () => import("./AccountView.vue"),
  AiAdvisorView: () => import("./AiAdvisorView.vue"),
  AuditView: () => import("./AuditView.vue"),
  AutoTradingView: () => import("./AutoTradingView.vue"),
  AuthView: () => import("./AuthView.vue"),
  DashboardView: () => import("./DashboardView.vue"),
  DiagnosticsView: () => import("./DiagnosticsView.vue"),
  MarketView: () => import("./MarketView.vue"),
  PortfolioView: () => import("./PortfolioView.vue"),
  ReliabilityView: () => import("./ReliabilityView.vue"),
  RiskView: () => import("./RiskView.vue"),
  SettingsView: () => import("./SettingsView.vue"),
  StrategyView: () => import("./StrategyView.vue"),
  TradeView: () => import("./TradeView.vue"),
};

function createStorageStub() {
  const storage = new Map();
  return {
    getItem: vi.fn((key) => storage.get(key) || null),
    setItem: vi.fn((key, value) => storage.set(key, String(value))),
    removeItem: vi.fn((key) => storage.delete(key)),
  };
}

function mockApiClient() {
  vi.spyOn(apiClient, "get").mockResolvedValue({ data: { items: [], total: 0 } });
  vi.spyOn(apiClient, "post").mockResolvedValue({ data: { success: true, items: [] } });
  vi.spyOn(apiClient, "put").mockResolvedValue({ data: { success: true } });
  vi.spyOn(apiClient, "delete").mockResolvedValue({ data: { success: true } });
}

describe("view smoke tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("localStorage", createStorageStub());
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.stubGlobal("IntersectionObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    mockApiClient();
    setActivePinia(createPinia());
  });

  for (const [name, loadView] of Object.entries(viewModules)) {
    it(`mounts ${name}`, async () => {
      const pinia = createPinia();
      setActivePinia(pinia);
      const component = (await loadView()).default;

      const wrapper = shallowMount(component, {
        global: {
          plugins: [pinia],
          stubs: {
            RouterLink: true,
            RouterView: true,
            BacktestChart: true,
            CryptoKlineChart: true,
          },
        },
      });

      expect(wrapper.exists()).toBe(true);
      wrapper.unmount();
    });
  }

  it("renders AuditView as an independent audit page", async () => {
    const component = (await viewModules.AuditView()).default;
    const wrapper = shallowMount(component, { global: { plugins: [createPinia()] } });

    expect(wrapper.text()).toContain("监控审计");
    expect(wrapper.findComponent({ name: "RiskView" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders DiagnosticsView as an independent diagnostics page", async () => {
    const component = (await viewModules.DiagnosticsView()).default;
    const wrapper = shallowMount(component, { global: { plugins: [createPinia()] } });

    expect(wrapper.text()).toContain("策略诊断");
    expect(wrapper.findComponent({ name: "StrategyView" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders SettingsView as an independent settings page", async () => {
    const component = (await viewModules.SettingsView()).default;
    const wrapper = shallowMount(component, { global: { plugins: [createPinia()] } });

    expect(wrapper.text()).toContain("系统设置");
    expect(wrapper.findComponent({ name: "AccountView" }).exists()).toBe(false);
    wrapper.unmount();
  });
});
