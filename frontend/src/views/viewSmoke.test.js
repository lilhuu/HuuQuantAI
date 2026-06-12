// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { shallowMount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import { apiClient } from "../lib/api";
import AiChatDrawer from "../components/AiChatDrawer.vue";
import FeatureCommandView from "../components/FeatureCommandView.vue";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useAiChatStore } from "../stores/aiChat";

const routeState = vi.hoisted(() => ({
  current: { path: "/", name: "dashboard", query: {}, meta: { title: "仪表盘" } },
  routerPush: vi.fn(),
}));

vi.mock("vue-router", async () => {
  const actual = await vi.importActual("vue-router");
  return {
    ...actual,
    useRoute: () => routeState.current,
    useRouter: () => ({ push: routeState.routerPush }),
  };
});

const viewModules = {
  AccountView: () => import("./AccountView.vue"),
  AiAdvisorView: () => import("./AiAdvisorView.vue"),
  AuditView: () => import("./AuditView.vue"),
  AutoTradingView: () => import("./AutoTradingView.vue"),
  AuthView: () => import("./AuthView.vue"),
  BacktestView: () => import("./BacktestView.vue"),
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
    routeState.routerPush.mockClear();
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

  it("renders BacktestView as an independent backtest center", async () => {
    const component = (await viewModules.BacktestView()).default;
    const wrapper = shallowMount(component, { global: { plugins: [createPinia()] } });

    expect(wrapper.findComponent(FeatureCommandView).props("feature")).toBe("backtest");
    expect(wrapper.findComponent({ name: "StrategyView" }).exists()).toBe(false);
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
    expect(text).toContain("这个项目怎么用？");
    expect(text).toContain("风控中心");
    expect(text).toContain("带项目和行情上下文");
    wrapper.unmount();
  });

  it("renders route-specific AI chat suggestions", () => {
    routeState.current = { path: "/risk", name: "risk", query: {}, meta: { title: "执行可靠性" } };
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

    expect(wrapper.text()).toContain("这个风控阻断是什么意思？");
    expect(wrapper.text()).not.toContain("为什么自动交易没有下单？");
    wrapper.unmount();
  });

  it("renders guide mode actions for the current route", () => {
    routeState.current = { path: "/strategy", name: "strategy", query: {}, meta: { title: "策略验证" } };
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

    expect(wrapper.text()).toContain("引导模式");
    expect(wrapper.text()).toContain("跑一次策略回测");
    wrapper.unmount();
  });

  it("renders safe AI action cards and navigates without trading calls", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const aiChat = useAiChatStore();
    aiChat.drawerOpen = true;
    aiChat.messages = [
      {
        message_id: "A1",
        role: "assistant",
        content: "可以先打开风控中心查看阻断原因。",
        context_summary: {
          action_cards: [
            {
              id: "risk-card",
              title: "查看风控阻断",
              description: "打开风控中心，只读检查阻断原因。",
              action_type: "navigate",
              target_route: "/risk",
              risk_level: "safe",
            },
            {
              id: "explain-card",
              title: "解释当前页面",
              description: "把问题填入输入框，不执行操作。",
              action_type: "explain",
              target_route: "",
              risk_level: "safe",
            },
          ],
        },
      },
    ];

    const wrapper = shallowMount(AiChatDrawer, {
      global: {
        plugins: [pinia],
        stubs: { Teleport: true },
      },
    });

    expect(wrapper.text()).toContain("查看风控阻断");
    await wrapper.find('[data-action-card-id="risk-card"]').trigger("click");
    expect(routeState.routerPush).toHaveBeenCalledWith("/risk");
    expect(apiClient.post).not.toHaveBeenCalledWith(expect.stringContaining("orders"), expect.anything());

    await wrapper.find('[data-action-card-id="explain-card"]').trigger("click");
    expect(wrapper.find("textarea").element.value).toContain("解释当前页面");
    wrapper.unmount();
  });

  it("marks feature pages with differentiated AI workspace regions", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const market = shallowMount(FeatureCommandView, {
      props: { feature: "market" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });
    expect(market.find('[data-feature-role="market-intelligence"]').exists()).toBe(true);
    expect(market.find(".cq-feature-copilot").exists()).toBe(true);
    market.unmount();

    const strategy = shallowMount(FeatureCommandView, {
      props: { feature: "strategy" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });
    expect(strategy.find('[data-feature-role="strategy-lab"]').exists()).toBe(true);
    expect(strategy.find('[data-feature-role="market-intelligence"]').exists()).toBe(false);
    strategy.unmount();

    const backtest = shallowMount(FeatureCommandView, {
      props: { feature: "backtest" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });
    expect(backtest.find('[data-feature-role="backtest-center"]').exists()).toBe(true);
    expect(backtest.find('[data-feature-role="strategy-lab"]').exists()).toBe(false);
    backtest.unmount();
  });

  it("renders a Binance Spot market table and loads details for the selected symbol only", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const marketStore = useMarketStore();
    marketStore.cryptoQuotes = [
      { symbol: "BTC/USDT", price: 65000, amount: 1000, volume: 2, change: 0.01, high: 66000, low: 64000 },
      { symbol: "ETH/BTC", price: 0.05, amount: 3000, volume: 50, change: -0.02, high: 0.052, low: 0.049 },
    ];
    marketStore.quoteFilter = "ALL";
    marketStore.quoteSortField = "amount";
    marketStore.quoteSortDir = "desc";

    const fetchQuotes = vi.spyOn(marketStore, "fetchCryptoQuotes").mockResolvedValue({});
    const fetchKlines = vi.spyOn(marketStore, "fetchCryptoKlines").mockResolvedValue({});
    const fetchOrderBook = vi.spyOn(marketStore, "fetchCryptoOrderBook").mockResolvedValue({});
    const connectMarketSocket = vi.spyOn(marketStore, "connectMarketSocket").mockImplementation(() => {});

    const wrapper = shallowMount(FeatureCommandView, {
      props: { feature: "market" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });

    expect(wrapper.find('[data-market-table="spot-quotes"]').text()).toContain("ETH/BTC");
    expect(wrapper.find('[data-quote-filter="spot-market"]').exists()).toBe(true);
    expect(wrapper.find('[data-market-search="spot-market"]').exists()).toBe(true);
    expect(wrapper.find('[data-market-type-tab="um_futures"]').exists()).toBe(true);

    await wrapper.find('[data-market-symbol="ETH/BTC"]').trigger("click");

    expect(fetchKlines).toHaveBeenCalledWith(expect.objectContaining({ symbol: "ETH/BTC" }));
    expect(fetchOrderBook).toHaveBeenCalledWith("ETH/BTC", 20, expect.objectContaining({ marketType: "spot" }));
    expect(fetchQuotes).not.toHaveBeenCalled();
    expect(connectMarketSocket).not.toHaveBeenCalled();

    await wrapper.find('[data-market-table-refresh="spot-market"]').trigger("click");
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchQuotes).toHaveBeenCalledWith(null, expect.objectContaining({ quote: "ALL" }));
    expect(connectMarketSocket).toHaveBeenCalledWith({ allMarket: true });

    await wrapper.find('[data-market-type-tab="um_futures"]').trigger("click");
    expect(marketStore.marketType).toBe("um_futures");
    expect(fetchQuotes).toHaveBeenCalledWith(null, expect.objectContaining({ marketType: "um_futures" }));

    wrapper.unmount();
  });

  it("does not run a backtest on mount and uses a longer timeout when requested", async () => {
    vi.useFakeTimers();
    const pinia = createPinia();
    setActivePinia(pinia);
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { items: [] } });

    const wrapper = shallowMount(FeatureCommandView, {
      props: { feature: "backtest" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });

    await vi.runOnlyPendingTimersAsync();
    expect(post).not.toHaveBeenCalledWith("/crypto/strategies/backtest", expect.anything(), expect.anything());

    await wrapper.find('[data-action="run-backtest"]').trigger("click");
    expect(post).toHaveBeenCalledWith(
      "/crypto/strategies/backtest",
      expect.objectContaining({ initial_cash: 10000 }),
      expect.objectContaining({ timeout: 90000 }),
    );

    wrapper.unmount();
    vi.useRealTimers();
  });

  it("uses a longer timeout for manual strategy runs", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { summary: [], strategy_results: [] } });

    const wrapper = shallowMount(FeatureCommandView, {
      props: { feature: "strategy" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });

    await wrapper.find('[data-action="run-strategy"]').trigger("click");
    expect(post).toHaveBeenCalledWith(
      "/crypto/strategies/run",
      expect.anything(),
      expect.objectContaining({ timeout: 45000 }),
    );

    wrapper.unmount();
  });

  it("defers feature data refresh until after the first render", async () => {
    vi.useFakeTimers();
    const pinia = createPinia();
    setActivePinia(pinia);
    const marketStore = useMarketStore();
    const systemStore = useSystemStore();
    const autoStore = useAutoTradingStore();
    const aiStore = useAiAdvisorStore();

    const fetchQuotes = vi.spyOn(marketStore, "fetchCryptoQuotes").mockResolvedValue({});
    const fetchKlines = vi.spyOn(marketStore, "fetchCryptoKlines").mockResolvedValue({});
    const fetchOrderBook = vi.spyOn(marketStore, "fetchCryptoOrderBook").mockResolvedValue({});
    const refreshOverview = vi.spyOn(systemStore, "refreshOverview").mockResolvedValue(undefined);
    const fetchStatus = vi.spyOn(autoStore, "fetchStatus").mockResolvedValue({});
    const fetchSignals = vi.spyOn(aiStore, "fetchSignals").mockResolvedValue({});

    const wrapper = shallowMount(FeatureCommandView, {
      props: { feature: "dashboard" },
      global: { plugins: [pinia], stubs: { CryptoKlineChart: true, BacktestChart: true } },
    });

    expect(wrapper.exists()).toBe(true);
    expect(fetchQuotes).not.toHaveBeenCalled();
    expect(fetchKlines).not.toHaveBeenCalled();
    expect(fetchOrderBook).not.toHaveBeenCalled();
    expect(refreshOverview).not.toHaveBeenCalled();
    expect(fetchStatus).not.toHaveBeenCalled();
    expect(fetchSignals).not.toHaveBeenCalled();

    await vi.runOnlyPendingTimersAsync();

    expect(fetchQuotes).toHaveBeenCalledTimes(1);
    expect(fetchKlines).toHaveBeenCalledTimes(1);
    expect(fetchOrderBook).toHaveBeenCalledTimes(1);
    expect(refreshOverview).toHaveBeenCalledTimes(1);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    expect(fetchSignals).toHaveBeenCalledTimes(1);

    wrapper.unmount();
    vi.useRealTimers();
  });
});
