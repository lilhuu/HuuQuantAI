// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { shallowMount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";
import AiChatDrawer from "../components/AiChatDrawer.vue";
import FeatureCommandView from "../components/FeatureCommandView.vue";
import { useAiChatStore } from "../stores/aiChat";

const routeState = vi.hoisted(() => ({
  current: { path: "/", name: "dashboard", query: {}, meta: { title: "仪表盘" } },
}));

vi.mock("vue-router", async () => {
  const actual = await vi.importActual("vue-router");
  return {
    ...actual,
    useRoute: () => routeState.current,
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
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    mockApiClient();
    routeState.current = { path: "/", name: "dashboard", query: {}, meta: { title: "仪表盘" } };
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

    expect(wrapper.findComponent(FeatureCommandView).props("feature")).toBe("audit");
    expect(wrapper.findComponent({ name: "RiskView" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders DiagnosticsView as an independent diagnostics page", async () => {
    const component = (await viewModules.DiagnosticsView()).default;
    const wrapper = shallowMount(component, { global: { plugins: [createPinia()] } });

    expect(wrapper.findComponent(FeatureCommandView).props("feature")).toBe("diagnostics");
    expect(wrapper.findComponent({ name: "StrategyView" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders SettingsView as an independent settings page", async () => {
    const component = (await viewModules.SettingsView()).default;
    const wrapper = shallowMount(component, { global: { plugins: [createPinia()] } });

    expect(wrapper.findComponent(FeatureCommandView).props("feature")).toBe("settings");
    expect(wrapper.findComponent({ name: "AccountView" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders AI chat drawer as a project copilot", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const aiChat = useAiChatStore();
    aiChat.drawerOpen = true;

    const wrapper = shallowMount(AiChatDrawer, {
      global: {
        plugins: [pinia],
        stubs: { Teleport: true },
      },
    });

    const text = wrapper.text();
    expect(text).toContain("项目副驾驶");
    expect(text).toContain("这个项目怎么用");
    expect(text).toContain("风控中心");
    expect(text).toContain("带项目和行情上下文");
    wrapper.unmount();
  });

  it("renders route-specific AI chat suggestions", () => {
    routeState.current = { path: "/risk", name: "risk", query: {}, meta: { title: "风控中心" } };
    const pinia = createPinia();
    setActivePinia(pinia);
    const aiChat = useAiChatStore();
    aiChat.drawerOpen = true;

    const wrapper = shallowMount(AiChatDrawer, {
      global: {
        plugins: [pinia],
        stubs: { Teleport: true },
      },
    });

    expect(wrapper.text()).toContain("这个风控阻断是什么意思");
    expect(wrapper.text()).not.toContain("为什么自动交易没有下单");
    wrapper.unmount();
  });
});
