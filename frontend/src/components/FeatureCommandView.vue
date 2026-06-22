<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

import BacktestChart from "./BacktestChart.vue";
import CryptoKlineChart from "./CryptoKlineChart.vue";
import { apiClient } from "../lib/api";
import { formatCurrency, formatPercent, formatPrice, normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAutoTradingStore } from "../stores/autoTrading";
import { normalizeMarketSymbol, useMarketStore } from "../stores/market";
import { usePortfolioStore } from "../stores/portfolio";
import { useSystemStore } from "../stores/system";
import { useUiStore } from "../stores/ui";

const props = defineProps({
  feature: {
    type: String,
    required: true,
  },
});

const aiStore = useAiAdvisorStore();
const autoStore = useAutoTradingStore();
const marketStore = useMarketStore();
const portfolioStore = usePortfolioStore();
const systemStore = useSystemStore();
const uiStore = useUiStore();

const modelMode = ref("Flash");
const marketForm = reactive({
  symbol: marketStore.selectedCryptoSymbol || "DOGE/USDT",
  period: marketStore.selectedCryptoPeriod || "1h",
  limit: 200,
  search: "",
});
const orderForm = reactive({
  symbol: marketStore.selectedCryptoSymbol || "DOGE/USDT",
  action: "BUY",
  quantity: 100,
  price: 0,
  strategy: "manual_ai_review",
});
const autoSymbolsText = ref((autoStore.configDraft.symbols || ["BTC/USDT", "ETH/USDT", "SOL/USDT"]).join(", "));
const aiSupervisorAcknowledged = ref(false);
const strategyForm = reactive({
  symbolsText: "BTC/USDT,ETH/USDT,SOL/USDT",
  period: "1h",
  limit: 240,
  initialCash: 10000,
});
const strategyTemplates = ref([]);
const strategySignals = ref([]);
const strategyBacktests = ref([]);
const formMessage = ref("");
const strategyLoading = ref(false);
const selectedPortfolioGroup = ref("symbol");
let initialRefreshTimer = null;
let disposed = false;

const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];
const watchSymbols = ["BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT", "BNB/USDT"];
const quoteFilters = [
  { label: "全部", value: "ALL" },
  { label: "USDT", value: "USDT" },
  { label: "USDC", value: "USDC" },
  { label: "FDUSD", value: "FDUSD" },
  { label: "BTC", value: "BTC" },
  { label: "ETH", value: "ETH" },
  { label: "BNB", value: "BNB" },
];
const STRATEGY_RUN_TIMEOUT_MS = 45000;
const STRATEGY_BACKTEST_TIMEOUT_MS = 90000;

const FEATURE_META = {
  dashboard: {
    eyebrow: "AI 指挥台",
    title: "仪表盘",
    subtitle: "把行情、AI 建议、风控审批、模拟订单和账户状态放在一个总览里。",
    intent: "全局看板",
    primary: "刷新总览",
    prompt: "帮我总结当前模拟交易系统状态",
  },
  market: {
    eyebrow: "Market Intelligence",
    title: "Binance Spot 全市场行情",
    subtitle: "查看 Binance 活跃现货交易对，支持搜索、quote 筛选、排序、自选与单交易对 K 线/盘口联动。",
    intent: "全市场行情",
    primary: "刷新全市场",
    prompt: "分析当前选中交易对的趋势和波动风险",
  },
  trade: {
    eyebrow: "Paper Execution",
    title: "手动交易",
    subtitle: "手动生成模拟订单，保留价格、数量、撤单和订单流，真实交易始终关闭。",
    intent: "模拟执行",
    primary: "刷新账户",
    prompt: "检查这笔模拟订单是否适合提交",
  },
  auto: {
    eyebrow: "Strategy Automation",
    title: "自动交易",
    subtitle: "配置扫描周期、交易对、仓位限制和策略组合，只向模拟盘提交订单。",
    intent: "自动扫描",
    primary: "立即扫描",
    prompt: "解释最近一次自动交易为什么执行或阻断",
  },
  strategy: {
    eyebrow: "Strategy Lab",
    title: "策略中心",
    subtitle: "运行内置策略、查看信号汇总，并用回测结果决定是否进入模拟执行。",
    intent: "策略研发",
    primary: "运行策略",
    prompt: "帮我比较当前策略组合的风险和优势",
  },
  backtest: {
    eyebrow: "Backtest Center",
    title: "回测中心",
    subtitle: "用历史 K 线验证策略表现，重点查看收益曲线、最大回撤、胜率和盈亏比，不会触发任何真实下单。",
    intent: "历史回测",
    primary: "开始回测",
    prompt: "帮我判断这次回测结果是否稳定，最大回撤和胜率是否可以接受",
  },
  portfolio: {
    eyebrow: "Portfolio Intelligence",
    title: "投资组合",
    subtitle: "查看模拟账户收益、资金曲线、分组归因和历史交易表现。",
    intent: "组合复盘",
    primary: "刷新收益",
    prompt: "分析组合收益和最大回撤",
  },
  account: {
    eyebrow: "Paper Account",
    title: "账户状态",
    subtitle: "集中查看 USDT 现金、持仓、资金曲线和模拟实盘日志。",
    intent: "账户资产",
    primary: "刷新账户",
    prompt: "帮我检查账户资金和持仓风险",
  },
  risk: {
    eyebrow: "Risk Approval",
    title: "风控中心",
    subtitle: "展示金额上限、仓位上限、禁止做空、禁止杠杆和 Kill Switch 状态。",
    intent: "风险审批",
    primary: "刷新风控",
    prompt: "说明当前风控是否允许生成模拟订单",
  },
  audit: {
    eyebrow: "Audit Trail",
    title: "审计日志",
    subtitle: "追踪 AI 建议、风控审批、模拟订单、撤单和拒单记录。",
    intent: "可追溯日志",
    primary: "刷新审计",
    prompt: "总结最近的订单生命周期和异常记录",
  },
  diagnostics: {
    eyebrow: "Diagnostics",
    title: "诊断中心",
    subtitle: "检查策略、行情连接、自动交易循环、缓存和执行质量。",
    intent: "健康检查",
    primary: "刷新诊断",
    prompt: "找出当前系统最需要修复的风险点",
  },
  settings: {
    eyebrow: "Control Settings",
    title: "系统设置",
    subtitle: "管理模型模式、提醒音效、连接状态和真实交易安全边界。",
    intent: "安全设置",
    primary: "刷新设置",
    prompt: "检查当前 AI 和交易安全配置",
  },
};

const meta = computed(() => FEATURE_META[props.feature] || FEATURE_META.dashboard);
const selectedSymbol = computed(() => normalizeMarketSymbol(marketStore.selectedCryptoSymbol || marketForm.symbol || "DOGE/USDT", marketStore.marketType));
const selectedQuote = computed(
  () => marketStore.cryptoQuotes.find((item) => normalizeMarketSymbol(item.symbol, marketStore.marketType) === selectedSymbol.value) || marketStore.cryptoQuotes[0] || null,
);
const latestPrice = computed(() => Number(selectedQuote.value?.price || marketStore.cryptoKlines.at(-1)?.close || 0));
const latestSignal = computed(() => aiStore.currentSignal || aiStore.signals[0] || null);
const signalConfidence = computed(() => Number(latestSignal.value?.confidence ?? 0.56));
const orders = computed(() => systemStore.cryptoOrders || []);
const positions = computed(() => systemStore.cryptoPositions || []);
const logs = computed(() => systemStore.cryptoLogs || []);
const decisions = computed(() => autoStore.decisions || []);
const aiSupervisor = computed(() => autoStore.aiSupervisor || {});
const isAiSupervised = computed(() => autoStore.configDraft.decision_mode === "ai_supervised");
const canStartAuto = computed(() => !isAiSupervised.value || aiSupervisorAcknowledged.value);
const topQuotes = computed(() => [...(marketStore.cryptoQuotes || [])].slice(0, 8));
const fullMarketQuotes = computed(() => marketStore.paginatedQuotes || []);
const marketQuoteStart = computed(() => (marketStore.quotesTotal ? (marketStore.quotePage - 1) * marketStore.quotePageSize + 1 : 0));
const marketQuoteEnd = computed(() => Math.min(marketStore.quotePage * marketStore.quotePageSize, marketStore.quotesTotal || 0));
const orderBook = computed(() => marketStore.cryptoOrderBook || { bids: [], asks: [] });
const topBids = computed(() => [...(orderBook.value.bids || [])].slice(0, 8));
const topAsks = computed(() => [...(orderBook.value.asks || [])].slice(0, 8));
const latestEquity = computed(() => systemStore.cryptoEquityCurve.at(-1) || null);
const activeMarketLabel = computed(() => marketStore.activeMarketTab?.label || "现货");
const showDerivativeMetrics = computed(() => marketStore.marketType !== "spot" && marketStore.derivativeMetrics);

const dashboardMetrics = computed(() => [
  { label: "最新价", value: latestPrice.value ? formatPrice(latestPrice.value) : "--", hint: selectedSymbol.value, tone: "green" },
  { label: "账户权益", value: formatCurrency(systemStore.liveAccountValue), hint: `现金 ${formatCurrency(systemStore.liveCash)}` },
  { label: "AI 建议", value: latestSignal.value?.action || "HOLD", hint: `置信度 ${signalConfidence.value.toFixed(2)}`, tone: "yellow" },
  { label: "风控状态", value: riskState.value, hint: "真实交易关闭", tone: riskState.value === "通过" ? "green" : "red" },
]);

const riskState = computed(() => {
  if (autoStore.configDraft.real_trading_enabled) return "异常";
  if (autoStore.state === "blocked") return "阻断";
  return "通过";
});

const riskRules = computed(() => [
  { label: "真实交易", value: "已关闭", status: "通过", detail: "AI、自动交易、手动交易都不能直接真钱下单。" },
  { label: "禁止做空", value: "启用", status: "通过", detail: "SELL 数量不能超过当前模拟持仓。" },
  { label: "禁止杠杆", value: "启用", status: "通过", detail: "仅使用 USDT 现金账户，不做借贷或合约。" },
  { label: "单笔上限", value: formatCurrency(autoStore.configDraft.max_order_notional || 300), status: "通过", detail: "超过上限会被本地审批拦截。" },
  { label: "最大持仓数", value: String(autoStore.configDraft.max_positions || 3), status: autoStore.state === "blocked" ? "阻断" : "通过", detail: "达到限制后新信号进入观察队列。" },
]);

const equityForChart = computed(() =>
  (systemStore.cryptoEquityCurve || []).map((item, index) => ({
    timestamp: item.timestamp || item.time || index,
    equity: Number(item.equity || item.total_equity || 0),
  })),
);
const drawdownForChart = computed(() =>
  (systemStore.cryptoEquityCurve || []).map((item, index) => ({
    timestamp: item.timestamp || item.time || index,
    drawdown: Number(item.drawdown || item.drawdown_pct || 0) / 100,
  })),
);
const portfolioEquityForChart = computed(() =>
  (portfolioStore.equityCurve || []).map((item, index) => ({
    timestamp: item.label || item.timestamp || index,
    equity: Number(item.equity || 0),
  })),
);
const portfolioDrawdownForChart = computed(() =>
  (portfolioStore.equityCurve || []).map((item, index) => ({
    timestamp: item.label || item.timestamp || index,
    drawdown: Number(item.drawdown_pct || 0) / 100,
  })),
);
const portfolioGroups = computed(() =>
  selectedPortfolioGroup.value === "strategy" ? portfolioStore.byStrategy : portfolioStore.bySymbol,
);

const systemHealth = computed(() => [
  { label: "行情连接", value: marketStore.marketSocketState || "idle", score: marketStore.marketSocketState === "connected" ? 92 : 64 },
  { label: "自动循环", value: autoStore.loopRunning ? "running" : "stopped", score: autoStore.loopRunning ? 88 : 52 },
  { label: "策略数量", value: String((autoStore.configDraft.strategies || []).length), score: 76 },
  { label: "模拟订单", value: String(orders.value.length), score: orders.value.length ? 84 : 58 },
]);

function parseSymbols(text) {
  return [...new Set(String(text || "").split(",").map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
}

function compactTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").slice(5, 16);
}

function pct(value) {
  return formatPercent(Number(value || 0) * 100);
}

function setModelMode(mode) {
  modelMode.value = mode === "Pro" ? "Pro" : "Flash";
}

function useQuotePrice() {
  if (latestPrice.value) {
    orderForm.price = latestPrice.value;
  }
}

function activeQuoteFilter() {
  const quote = String(marketStore.quoteFilter || (marketStore.marketType === "spot" ? "USDT" : "ALL")).toUpperCase();
  return quote === "ALL" ? "ALL" : quote;
}

function switchMarketType(marketType) {
  marketStore.setMarketType(marketType);
  marketForm.symbol = marketStore.selectedCryptoSymbol || "BTC/USDT";
  loadMarket();
}

function resetMarketPage() {
  marketStore.quotePage = 1;
}

function setMarketSort(field) {
  if (marketStore.quoteSortField === field) {
    marketStore.quoteSortDir = marketStore.quoteSortDir === "asc" ? "desc" : "asc";
  } else {
    marketStore.quoteSortField = field;
    marketStore.quoteSortDir = field === "symbol" ? "asc" : "desc";
  }
  resetMarketPage();
}

async function refreshAll() {
  const symbols = marketStore.cryptoWatchSymbols?.length ? marketStore.cryptoWatchSymbols : watchSymbols;
  await Promise.allSettled([
    marketStore.fetchCryptoQuotes(symbols),
    marketStore.fetchCryptoKlines({ symbol: selectedSymbol.value, period: marketStore.selectedCryptoPeriod || "1h", limit: 200 }),
    marketStore.fetchCryptoOrderBook(selectedSymbol.value, 20),
    systemStore.refreshOverview(),
    autoStore.fetchStatus(),
    aiStore.fetchSignals(),
  ]);
}

async function loadMarket() {
  const symbol = normalizeMarketSymbol(marketForm.symbol || selectedSymbol.value, marketStore.marketType);
  marketForm.symbol = symbol;
  marketStore.selectedCryptoSymbol = symbol;
  await Promise.allSettled([
    marketStore.fetchCryptoSymbols({
      marketType: marketStore.marketType,
      search: marketStore.quoteSearch || undefined,
      quote: activeQuoteFilter(),
      limit: 500,
      offset: 0,
    }),
    marketStore.fetchCryptoQuotes(null, {
      marketType: marketStore.marketType,
      search: marketStore.quoteSearch || undefined,
      quote: activeQuoteFilter(),
      limit: 0,
      offset: 0,
    }),
    marketStore.fetchCryptoKlines({
      marketType: marketStore.marketType,
      symbol,
      period: marketForm.period,
      limit: Number(marketForm.limit || 200),
    }),
    marketStore.fetchCryptoOrderBook(symbol, 20, { marketType: marketStore.marketType }),
    marketStore.fetchDerivativeMetrics(symbol, { marketType: marketStore.marketType }),
  ]);
  marketStore.connectMarketSocket({ allMarket: true });
}

async function selectMarketQuote(quote) {
  const symbol = normalizeMarketSymbol(quote?.symbol, marketStore.marketType);
  if (!symbol) {
    return;
  }
  marketForm.symbol = symbol;
  orderForm.symbol = symbol;
  marketStore.selectedCryptoSymbol = symbol;
  await Promise.allSettled([
    marketStore.fetchCryptoKlines({
      marketType: marketStore.marketType,
      symbol,
      period: marketForm.period,
      limit: Number(marketForm.limit || 200),
    }),
    marketStore.fetchCryptoOrderBook(symbol, 20, { marketType: marketStore.marketType }),
    marketStore.fetchDerivativeMetrics(symbol, { marketType: marketStore.marketType }),
  ]);
}

async function submitOrder() {
  formMessage.value = "";
  const symbol = normalizeCryptoSymbol(orderForm.symbol);
  if (!symbol) {
    formMessage.value = "请输入交易对。";
    return;
  }
  if (Number(orderForm.quantity) <= 0 || Number(orderForm.price) <= 0) {
    formMessage.value = "数量和价格必须大于 0。";
    return;
  }
  try {
    const result = await systemStore.placeCryptoPaperOrder({
      symbol,
      action: orderForm.action,
      quantity: Number(orderForm.quantity),
      price: Number(orderForm.price),
      order_type: "LIMIT",
      strategy: orderForm.strategy || "manual_ai_review",
    });
    formMessage.value = result?.message || "模拟订单已提交。";
  } catch (error) {
    systemStore.setError(error, "提交模拟订单失败");
  }
}

async function saveAutoConfig() {
  autoStore.setSymbolsText(autoSymbolsText.value);
  await autoStore.saveConfig();
  autoSymbolsText.value = autoStore.symbolsText();
}

async function startAuto() {
  if (!canStartAuto.value) {
    formMessage.value = "请先确认 AI 只操作 PaperBroker 模拟账户。";
    return;
  }
  autoStore.setSymbolsText(autoSymbolsText.value);
  await autoStore.start();
}

function setDecisionMode(mode) {
  autoStore.configDraft.decision_mode = mode === "strategy" ? "strategy" : "ai_supervised";
  aiSupervisorAcknowledged.value = false;
}

async function runAutoScan() {
  autoStore.setSymbolsText(autoSymbolsText.value);
  await autoStore.scan();
}

function strategyPayload() {
  const symbols = parseSymbols(strategyForm.symbolsText);
  return {
    symbols: symbols.length ? symbols : ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    period: strategyForm.period,
    limit: Number(strategyForm.limit || 240),
    conflict_threshold: 0.15,
    strategies: (autoStore.configDraft.strategies || []).map((item) => ({
      strategy_id: item.strategy_id,
      type: item.type,
      enabled: item.enabled,
      weight: Number(item.weight || 1),
      symbols: item.symbols || symbols,
      parameters: item.parameters || {},
    })),
  };
}

async function loadStrategyTemplates() {
  const { data } = await apiClient.get("/crypto/strategies/templates");
  strategyTemplates.value = data.items || [];
}

async function runStrategies() {
  strategyLoading.value = true;
  try {
    const { data } = await apiClient.post("/crypto/strategies/run", strategyPayload(), {
      timeout: STRATEGY_RUN_TIMEOUT_MS,
    });
    strategySignals.value = data.summary || data.strategy_results || [];
  } catch (error) {
    systemStore.setError(error, "运行策略失败");
  } finally {
    strategyLoading.value = false;
  }
}

async function backtestStrategies() {
  strategyLoading.value = true;
  try {
    const { data } = await apiClient.post(
      "/crypto/strategies/backtest",
      {
        ...strategyPayload(),
        initial_cash: Number(strategyForm.initialCash || 10000),
        fee_rate: 0.001,
        slippage_rate: 0.0005,
        min_quantity: 0.000001,
        position_sizing: "strategy_position_ratio",
      },
      {
        timeout: STRATEGY_BACKTEST_TIMEOUT_MS,
      },
    );
    strategyBacktests.value = data.items || [];
  } catch (error) {
    systemStore.setError(error, "策略回测失败");
  } finally {
    strategyLoading.value = false;
  }
}

async function refreshFeature() {
  if (props.feature === "market") return loadMarket();
  if (props.feature === "trade" || props.feature === "account") return systemStore.refreshOverview();
  if (props.feature === "auto") return runAutoScan();
  if (props.feature === "strategy") return runStrategies();
  if (props.feature === "backtest") return backtestStrategies();
  if (props.feature === "portfolio") return portfolioStore.fetchAnalytics();
  if (props.feature === "settings") return Promise.allSettled([autoStore.fetchStatus(), systemStore.refreshOverview()]);
  return refreshAll();
}

async function hydrateFeature() {
  if (props.feature === "market") {
    await loadMarket();
  } else if (props.feature === "trade" || props.feature === "account" || props.feature === "risk" || props.feature === "audit") {
    await Promise.allSettled([systemStore.refreshOverview(), autoStore.fetchStatus()]);
  } else if (props.feature === "auto") {
    await Promise.allSettled([
      autoStore.fetchStatus(),
      systemStore.refreshOverview(),
      marketStore.fetchCryptoQuotes(marketStore.cryptoWatchSymbols?.length ? marketStore.cryptoWatchSymbols : watchSymbols),
    ]);
  } else if (props.feature === "strategy") {
    await Promise.allSettled([
      loadStrategyTemplates(),
      autoStore.fetchStatus(),
      marketStore.fetchCryptoQuotes(marketStore.cryptoWatchSymbols?.length ? marketStore.cryptoWatchSymbols : watchSymbols),
    ]);
  } else if (props.feature === "backtest") {
    await Promise.allSettled([
      loadStrategyTemplates(),
      autoStore.fetchStatus(),
      marketStore.fetchCryptoQuotes(marketStore.cryptoWatchSymbols?.length ? marketStore.cryptoWatchSymbols : watchSymbols),
    ]);
  } else if (props.feature === "portfolio") {
    await Promise.allSettled([portfolioStore.fetchAnalytics(), systemStore.refreshOverview()]);
  } else if (props.feature === "settings" || props.feature === "diagnostics") {
    await Promise.allSettled([autoStore.fetchStatus(), systemStore.refreshOverview()]);
  } else {
    await refreshAll();
  }

  if (!orderForm.price && latestPrice.value) {
    orderForm.price = latestPrice.value;
  }
}

onMounted(() => {
  disposed = false;
  initialRefreshTimer = window.setTimeout(() => {
    initialRefreshTimer = null;
    if (disposed) {
      return;
    }
    hydrateFeature().catch((error) => {
      if (!disposed) {
        systemStore.setError(error, "刷新工作台数据失败");
      }
    });
  }, 180);
});

onBeforeUnmount(() => {
  disposed = true;
  if (initialRefreshTimer) {
    window.clearTimeout(initialRefreshTimer);
    initialRefreshTimer = null;
  }
});
</script>

<template>
  <section class="cq-feature-matrix cq-feature-matrix--distinct">
    <header class="cq-feature-hero">
      <div>
        <span class="cq-feature-kicker">{{ meta.eyebrow }}</span>
        <h1>{{ meta.title }}</h1>
        <p>{{ meta.subtitle }}</p>
      </div>
      <div class="cq-feature-hero__actions">
        <button class="cq-command-button cq-command-button--primary" type="button" @click="refreshFeature">
          {{ meta.primary }}
        </button>
      </div>
    </header>

    <div class="cq-feature-metrics">
      <article
        v-for="metric in dashboardMetrics"
        :key="metric.label"
        class="cq-feature-metric"
        :class="metric.tone ? `cq-feature-metric--${metric.tone}` : ''"
      >
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.hint }}</small>
      </article>
    </div>

    <div v-if="feature === 'dashboard'" class="cq-distinct-grid cq-distinct-grid--dashboard" data-feature-role="ai-command-dashboard">
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline">
          <div>
            <span>AI 总览</span>
            <h2>当前模拟交易闭环</h2>
          </div>
          <b>DeepSeek V4 {{ modelMode }}</b>
        </div>
        <div class="cq-command-steps">
          <div v-for="rule in riskRules" :key="rule.label">
            <strong>{{ rule.label }}</strong>
            <span>{{ rule.value }}</span>
            <small>{{ rule.detail }}</small>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline">
          <div>
            <span>市场雷达</span>
            <h2>关注交易对</h2>
          </div>
        </div>
        <div class="cq-mini-table">
          <div v-for="quote in topQuotes" :key="quote.symbol">
            <strong>{{ quote.symbol }}</strong>
            <span>{{ formatPrice(quote.price) }}</span>
            <em :class="Number(quote.change || 0) >= 0 ? 'number-up' : 'number-down'">{{ pct(quote.change) }}</em>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline">
          <div>
            <span>AI 建议</span>
            <h2>{{ latestSignal?.action || "HOLD" }} / {{ selectedSymbol }}</h2>
          </div>
        </div>
        <p class="cq-feature-copy">{{ latestSignal?.reason || "暂无新的结构化 AI 信号，系统保持观察模式。" }}</p>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline">
          <div>
            <span>最近事件</span>
            <h2>订单 / 决策 / 日志</h2>
          </div>
        </div>
        <div class="cq-feature-feed">
          <div v-for="order in orders.slice(0, 6)" :key="order.order_id || order.created_time" class="cq-feature-feed-row">
            <strong>{{ order.symbol || selectedSymbol }}</strong>
            <span>{{ order.action || order.status }}</span>
            <small>{{ compactTime(order.created_time || order.filled_time) }}</small>
          </div>
          <p v-if="!orders.length" class="cq-empty-note">暂无模拟订单。</p>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'market'" class="cq-distinct-grid cq-distinct-grid--market" data-feature-role="market-intelligence">
      <article class="cq-feature-panel cq-span-3" data-market-tabs="binance-public-market">
        <div class="cq-panel-headline">
          <div>
            <span>Binance 公共行情</span>
            <h2>{{ activeMarketLabel }}全市场</h2>
          </div>
          <b>{{ marketStore.marketType }}</b>
        </div>
        <div class="cq-button-row">
          <button
            v-for="tab in marketStore.marketTabs"
            :key="tab.value"
            class="cq-command-button"
            :class="{ 'cq-command-button--primary': marketStore.marketType === tab.value }"
            type="button"
            :data-market-type-tab="tab.value"
            @click="switchMarketType(tab.value)"
          >
            {{ tab.label }}
          </button>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline">
          <div>
            <span>Binance 行情</span>
            <h2>{{ marketForm.symbol }} K 线</h2>
          </div>
          <b>{{ marketStore.marketSocketState || "idle" }}</b>
        </div>
        <div class="cq-form-strip">
          <input v-model="marketForm.symbol" placeholder="DOGE/USDT" />
          <select v-model="marketForm.period">
            <option v-for="period in periods" :key="period" :value="period">{{ period }}</option>
          </select>
          <input v-model.number="marketForm.limit" type="number" min="50" max="1000" />
          <button class="cq-command-button cq-command-button--primary" type="button" @click="loadMarket">加载</button>
        </div>
        <p class="cq-empty-note">
          {{ marketStore.marketStatusMessage }} · 数据源 {{ marketStore.cryptoKlineSource || "binance" }} ·
          {{ marketStore.lastMarketMessageAt || "等待刷新" }}
        </p>
        <CryptoKlineChart :candles="marketStore.cryptoKlines" :height="360" />
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline">
          <div>
            <span>盘口深度</span>
            <h2>买卖队列</h2>
          </div>
        </div>
        <div class="cq-orderbook-grid">
          <div>
            <strong>买盘</strong>
            <p v-for="(bid, index) in topBids" :key="`bid-${index}`">
              <span>{{ formatPrice(bid.price || bid[0]) }}</span><em>{{ bid.quantity || bid.amount || bid[1] }}</em>
            </p>
          </div>
          <div>
            <strong>卖盘</strong>
            <p v-for="(ask, index) in topAsks" :key="`ask-${index}`">
              <span>{{ formatPrice(ask.price || ask[0]) }}</span><em>{{ ask.quantity || ask.amount || ask[1] }}</em>
            </p>
          </div>
        </div>
      </article>
      <article v-if="showDerivativeMetrics" class="cq-feature-panel" data-market-derivatives="metrics">
        <div class="cq-panel-headline">
          <div>
            <span>衍生指标</span>
            <h2>{{ marketStore.derivativeMetrics?.symbol }}</h2>
          </div>
          <b>{{ marketStore.derivativeMetrics?.source || "binance" }}</b>
        </div>
        <div class="cq-command-steps">
          <div>
            <strong>标记价格</strong>
            <span>{{ formatPrice(marketStore.derivativeMetrics?.mark_price || 0) }}</span>
          </div>
          <div>
            <strong>指数价格</strong>
            <span>{{ formatPrice(marketStore.derivativeMetrics?.index_price || 0) }}</span>
          </div>
          <div>
            <strong>资金费率</strong>
            <span>{{ pct(marketStore.derivativeMetrics?.funding_rate || 0) }}</span>
          </div>
          <div>
            <strong>持仓量</strong>
            <span>{{ formatPrice(marketStore.derivativeMetrics?.open_interest || 0) }}</span>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline">
          <div>
            <span>Binance {{ activeMarketLabel }}</span>
            <h2>全市场行情</h2>
          </div>
          <b>{{ marketStore.quotesTotal }} 个交易对</b>
        </div>
        <div class="cq-form-strip">
          <select
            v-model="marketStore.quoteFilter"
            data-quote-filter="spot-market"
            @change="resetMarketPage(); loadMarket()"
          >
            <option v-for="item in marketStore.quoteFilterOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
          <input
            v-model="marketStore.quoteSearch"
            class="cq-compact-input"
            data-market-search="spot-market"
            placeholder="搜索 BTC / DOGE"
            @input="resetMarketPage"
          />
          <select v-model="marketStore.quoteSortField" @change="resetMarketPage">
            <option value="amount">成交额</option>
            <option value="change">涨跌幅</option>
            <option value="price">最新价</option>
            <option value="volume">成交量</option>
            <option value="symbol">交易对</option>
          </select>
          <button
            class="cq-command-button cq-command-button--primary"
            type="button"
            data-market-table-refresh="spot-market"
            @click="loadMarket"
          >
            刷新行情
          </button>
        </div>
        <div class="cq-table-shell">
          <table data-market-table="spot-quotes">
            <thead>
              <tr>
                <th><button class="cq-table-eye" type="button" @click="setMarketSort('symbol')">交易对</button></th>
                <th><button class="cq-table-eye" type="button" @click="setMarketSort('price')">最新价</button></th>
                <th><button class="cq-table-eye" type="button" @click="setMarketSort('change')">24h 涨跌</button></th>
                <th><button class="cq-table-eye" type="button" @click="setMarketSort('volume')">成交量</button></th>
                <th><button class="cq-table-eye" type="button" @click="setMarketSort('amount')">成交额</button></th>
                <th>最高价</th>
                <th>最低价</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="quote in fullMarketQuotes"
                :key="quote.symbol"
                :data-market-symbol="quote.symbol"
                class="cq-clickable-row"
                @click="selectMarketQuote(quote)"
              >
                <td>{{ quote.symbol }}</td>
                <td>{{ formatPrice(quote.price) }}</td>
                <td :class="Number(quote.change || 0) >= 0 ? 'number-up' : 'number-down'">{{ pct(quote.change) }}</td>
                <td>{{ formatPrice(quote.volume || 0) }}</td>
                <td>{{ formatPrice(quote.amount || 0) }}</td>
                <td>{{ formatPrice(quote.high || 0) }}</td>
                <td>{{ formatPrice(quote.low || 0) }}</td>
                <td>{{ compactTime(quote.timestamp) }}</td>
              </tr>
              <tr v-if="!fullMarketQuotes.length"><td colspan="8">暂无行情，点击刷新行情。</td></tr>
            </tbody>
          </table>
        </div>
        <div class="cq-button-row">
          <button
            class="cq-command-button"
            type="button"
            :disabled="marketStore.quotePage <= 1"
            @click="marketStore.quotePage = Math.max(1, marketStore.quotePage - 1)"
          >
            上一页
          </button>
          <span class="cq-empty-note">
            {{ marketQuoteStart }}-{{ marketQuoteEnd }} / {{ marketStore.quotesTotal }} · 第 {{ marketStore.quotePage }} / {{ marketStore.totalPages }} 页
          </span>
          <button
            class="cq-command-button"
            type="button"
            :disabled="marketStore.quotePage >= marketStore.totalPages"
            @click="marketStore.quotePage = Math.min(marketStore.totalPages, marketStore.quotePage + 1)"
          >
            下一页
          </button>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'trade'" class="cq-distinct-grid cq-distinct-grid--trade" data-feature-role="paper-execution">
      <article class="cq-feature-panel">
        <div class="cq-panel-headline">
          <div>
            <span>手动确认</span>
            <h2>模拟下单</h2>
          </div>
          <b>真实交易关闭</b>
        </div>
        <div class="cq-form-stack">
          <label><span>交易对</span><input v-model="orderForm.symbol" /></label>
          <label><span>方向</span><select v-model="orderForm.action"><option>BUY</option><option>SELL</option></select></label>
          <label><span>数量</span><input v-model.number="orderForm.quantity" type="number" min="0.000001" step="0.000001" /></label>
          <label><span>限价 USDT</span><input v-model.number="orderForm.price" type="number" min="0.000001" step="0.01" /></label>
          <label><span>策略标签</span><input v-model="orderForm.strategy" /></label>
        </div>
        <div class="cq-button-row">
          <button class="cq-command-button" type="button" @click="useQuotePrice">使用最新价</button>
          <button class="cq-command-button cq-command-button--primary" type="button" @click="submitOrder">提交模拟订单</button>
        </div>
        <p v-if="formMessage" class="cq-feature-copy">{{ formMessage }}</p>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline">
          <div>
            <span>订单流</span>
            <h2>模拟订单</h2>
          </div>
          <button class="cq-table-eye" type="button" @click="systemStore.fetchCryptoPaperOrders()">刷新</button>
        </div>
        <div class="cq-table-shell">
          <table>
            <thead><tr><th>订单号</th><th>交易对</th><th>方向</th><th>数量</th><th>价格</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="order in orders" :key="order.order_id">
                <td>{{ order.order_id }}</td><td>{{ order.symbol }}</td><td>{{ order.action }}</td><td>{{ order.quantity }}</td>
                <td>{{ formatPrice(order.price) }}</td><td>{{ order.status }}</td>
                <td><button class="cq-table-eye" type="button" @click="systemStore.cancelCryptoPaperOrder(order.order_id)">撤单</button></td>
              </tr>
              <tr v-if="!orders.length"><td colspan="7">暂无模拟订单。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>账户资金</span><h2>USDT 模拟盘</h2></div></div>
        <div class="cq-focus-grid">
          <div class="cq-focus-card"><span>现金</span><strong>{{ formatCurrency(systemStore.cryptoAccount?.cash || 0) }}</strong><small>可下单余额</small></div>
          <div class="cq-focus-card"><span>权益</span><strong>{{ formatCurrency(systemStore.cryptoAccount?.equity || 0) }}</strong><small>含持仓市值</small></div>
          <div class="cq-focus-card"><span>手续费</span><strong>{{ formatCurrency(systemStore.cryptoAccount?.total_fee || 0) }}</strong><small>累计成本</small></div>
          <div class="cq-focus-card"><span>持仓数</span><strong>{{ positions.length }}</strong><small>禁止做空</small></div>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'auto'" class="cq-distinct-grid cq-distinct-grid--auto" data-feature-role="auto-decision-pipeline">
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>自动交易配置</span><h2>扫描控制台</h2></div><b>{{ autoStore.stateLabel }}</b></div>
        <div class="cq-auto-mode-switch" aria-label="自动交易决策模式">
          <button
            type="button"
            data-auto-decision-mode="strategy"
            :class="{ active: !isAiSupervised }"
            @click="setDecisionMode('strategy')"
          >规则自动</button>
          <button
            type="button"
            data-auto-decision-mode="ai_supervised"
            :class="{ active: isAiSupervised }"
            @click="setDecisionMode('ai_supervised')"
          >AI 模拟托管</button>
        </div>
        <div class="cq-form-stack">
          <label><span>交易对</span><input v-model="autoSymbolsText" /></label>
          <label><span>周期</span><select v-model="autoStore.configDraft.period"><option v-for="period in periods" :key="period">{{ period }}</option></select></label>
          <label><span>扫描间隔</span><input v-model.number="autoStore.configDraft.scan_interval_seconds" type="number" /></label>
          <label><span>最大持仓数</span><input v-model.number="autoStore.configDraft.max_positions" type="number" /></label>
          <label><span>单笔上限 USDT</span><input v-model.number="autoStore.configDraft.max_order_notional" type="number" /></label>
          <label><span>置信度阈值</span><input v-model.number="autoStore.configDraft.confidence_threshold" type="number" step="0.05" /></label>
          <label v-if="isAiSupervised"><span>AI 置信度</span><input v-model.number="autoStore.configDraft.ai_confidence_threshold" type="number" step="0.05" /></label>
          <label v-if="isAiSupervised"><span>日亏损上限</span><input v-model.number="autoStore.configDraft.max_daily_loss" type="number" /></label>
        </div>
        <label v-if="isAiSupervised" class="cq-auto-acknowledgement">
          <input v-model="aiSupervisorAcknowledged" data-ai-supervisor-ack type="checkbox" />
          <span>我确认 AI 仅操作 PaperBroker 模拟账户，真实交易保持关闭。</span>
        </label>
        <div class="cq-button-row">
          <button class="cq-command-button" type="button" @click="saveAutoConfig">保存</button>
          <button class="cq-command-button" type="button" :disabled="!canStartAuto" @click="startAuto">启动</button>
          <button class="cq-command-button" type="button" @click="autoStore.pause()">暂停</button>
          <button class="cq-command-button cq-command-button--primary" type="button" @click="runAutoScan">扫描</button>
        </div>
        <p v-if="formMessage" class="cq-feature-copy">{{ formMessage }}</p>
      </article>
      <article class="cq-feature-panel cq-span-2" data-ai-supervisor-status>
        <div class="cq-panel-headline">
          <div><span>AI 托管状态</span><h2>{{ isAiSupervised ? "DeepSeek 最终裁决" : "规则策略执行" }}</h2></div>
          <b>{{ aiSupervisor.last_action || "HOLD" }}</b>
        </div>
        <div class="cq-auto-supervisor-grid">
          <div><span>主模型</span><strong>{{ autoStore.configDraft.ai_model || "deepseek-v4-pro" }}</strong></div>
          <div><span>备用模型</span><strong>{{ autoStore.configDraft.ai_fallback_model || "deepseek-v4-flash" }}</strong></div>
          <div><span>最近 K 线</span><strong>{{ compactTime(aiSupervisor.last_candle_at) }}</strong></div>
          <div><span>Provider 失败</span><strong>{{ aiSupervisor.provider_failure_count || 0 }} / 3</strong></div>
          <div><span>保护退出</span><strong>止损 2% / 止盈 4%</strong></div>
          <div><span>重启行为</span><strong>需要手动重新开启</strong></div>
        </div>
        <div class="cq-panel-headline cq-auto-strategy-heading"><div><span>候选来源</span><h2>已配置策略</h2></div></div>
        <div class="cq-strategy-stack">
          <div v-for="strategy in autoStore.configDraft.strategies" :key="strategy.strategy_id">
            <strong>{{ strategy.strategy_id }}</strong>
            <span>{{ strategy.type }} / weight {{ strategy.weight }}</span>
            <em>{{ strategy.enabled ? "启用" : "停用" }}</em>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>最近自动决策</span><h2>Decision Pipeline</h2></div></div>
        <div class="cq-table-shell">
          <table>
            <thead><tr><th>时间</th><th>交易对</th><th>策略</th><th>动作</th><th>置信度</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in decisions.slice(0, 12)" :key="index">
                <td>{{ compactTime(item.timestamp || item.created_at) }}</td><td>{{ item.symbol || "-" }}</td><td>{{ item.strategy_id || "-" }}</td>
                <td>{{ item.action || item.signal || "HOLD" }}</td><td>{{ Number(item.confidence || 0).toFixed(2) }}</td><td>{{ item.status || "-" }}</td>
              </tr>
              <tr v-if="!decisions.length"><td colspan="6">暂无自动决策，点击扫描生成。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'strategy'" class="cq-distinct-grid cq-distinct-grid--strategy" data-feature-role="strategy-lab">
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>策略实验室</span><h2>运行参数</h2></div></div>
        <div class="cq-form-stack">
          <label><span>交易对</span><input v-model="strategyForm.symbolsText" /></label>
          <label><span>周期</span><select v-model="strategyForm.period"><option v-for="period in periods" :key="period">{{ period }}</option></select></label>
          <label><span>K 线数量</span><input v-model.number="strategyForm.limit" type="number" /></label>
          <label><span>初始资金</span><input v-model.number="strategyForm.initialCash" type="number" /></label>
        </div>
        <div class="cq-button-row">
          <button class="cq-command-button" type="button" @click="loadStrategyTemplates">模板</button>
          <button class="cq-command-button cq-command-button--primary" type="button" data-action="run-strategy" @click="runStrategies">运行策略</button>
          <button class="cq-command-button" type="button" @click="backtestStrategies">回测</button>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline"><div><span>模板库</span><h2>内置策略</h2></div><b>{{ strategyTemplates.length || autoStore.configDraft.strategies.length }}</b></div>
        <div class="cq-strategy-stack">
          <div v-for="template in (strategyTemplates.length ? strategyTemplates : autoStore.configDraft.strategies)" :key="template.strategy_id || template.type">
            <strong>{{ template.name || template.strategy_id || template.type }}</strong>
            <span>{{ template.description || template.type || "策略模板" }}</span>
            <em>AI 可解释</em>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>信号与回测</span><h2>策略验证结果</h2></div><b>{{ strategyLoading ? "运行中" : "就绪" }}</b></div>
        <div class="cq-table-shell">
          <table>
            <thead><tr><th>策略/交易对</th><th>动作</th><th>置信度</th><th>原因/收益</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in strategySignals.slice(0, 8)" :key="`signal-${index}`">
                <td>{{ item.strategy_id || item.symbol || "-" }}</td><td>{{ item.action || item.signal || "HOLD" }}</td>
                <td>{{ Number(item.confidence || 0).toFixed(2) }}</td><td>{{ item.reason || item.message || "-" }}</td><td>信号</td>
              </tr>
              <tr v-for="(item, index) in strategyBacktests.slice(0, 8)" :key="`backtest-${index}`">
                <td>{{ item.strategy_name || item.strategy_id || "-" }}</td><td>BACKTEST</td>
                <td>{{ Number(item.win_rate || 0).toFixed(2) }}</td><td>{{ formatCurrency(item.total_pnl || 0) }}</td><td>回测</td>
              </tr>
              <tr v-if="!strategySignals.length && !strategyBacktests.length"><td colspan="5">暂无策略结果。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'backtest'" class="cq-distinct-grid cq-distinct-grid--backtest" data-feature-role="backtest-center">
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>回测参数</span><h2>历史表现验证</h2></div><b>{{ strategyLoading ? "运行中" : "就绪" }}</b></div>
        <div class="cq-form-stack">
          <label><span>交易对</span><input v-model="strategyForm.symbolsText" /></label>
          <label><span>周期</span><select v-model="strategyForm.period"><option v-for="period in periods" :key="period">{{ period }}</option></select></label>
          <label><span>K 线数量</span><input v-model.number="strategyForm.limit" type="number" /></label>
          <label><span>初始资金 USDT</span><input v-model.number="strategyForm.initialCash" type="number" /></label>
        </div>
        <div class="cq-button-row">
          <button class="cq-command-button" type="button" @click="loadStrategyTemplates">模板</button>
          <button class="cq-command-button cq-command-button--primary" type="button" data-action="run-backtest" @click="backtestStrategies">开始回测</button>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline"><div><span>回测曲线</span><h2>权益与回撤</h2></div><b>{{ strategyBacktests.length }} 组结果</b></div>
        <BacktestChart
          :equity-curve="strategyBacktests[0]?.equity_curve || []"
          :drawdown-curve="strategyBacktests[0]?.drawdown_curve || []"
          :height="300"
        />
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>回测结果</span><h2>收益 / 回撤 / 胜率</h2></div></div>
        <div class="cq-table-shell">
          <table>
            <thead><tr><th>策略</th><th>收益</th><th>最大回撤</th><th>胜率</th><th>盈亏比</th><th>交易数</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in strategyBacktests.slice(0, 12)" :key="`backtest-center-${index}`">
                <td>{{ item.strategy_name || item.strategy_id || "-" }}</td>
                <td>{{ formatPercent(item.total_return_percent || 0) }}</td>
                <td>{{ formatPercent(item.max_drawdown_percent || 0) }}</td>
                <td>{{ formatPercent(item.win_rate || 0) }}</td>
                <td>{{ Number(item.profit_factor || 0).toFixed(2) }}</td>
                <td>{{ item.trade_count || 0 }}</td>
              </tr>
              <tr v-if="!strategyBacktests.length"><td colspan="6">暂无回测结果，点击“开始回测”后生成。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>模板库</span><h2>可回测策略</h2></div><b>{{ strategyTemplates.length || autoStore.configDraft.strategies.length }}</b></div>
        <div class="cq-strategy-stack">
          <div v-for="template in (strategyTemplates.length ? strategyTemplates : autoStore.configDraft.strategies)" :key="template.strategy_id || template.type">
            <strong>{{ template.name || template.strategy_id || template.type }}</strong>
            <span>{{ template.description || template.type || "策略模板" }}</span>
            <em>仅模拟</em>
          </div>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'portfolio'" class="cq-distinct-grid cq-distinct-grid--portfolio" data-feature-role="portfolio-intelligence">
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline">
          <div><span>资金曲线</span><h2>组合收益</h2></div>
          <div class="cq-button-row">
            <select v-model="portfolioStore.mode"><option value="demo">模拟盘</option><option value="shadow">影子交易</option><option value="live">本地记录</option></select>
            <select v-model="portfolioStore.range"><option value="7d">7 天</option><option value="30d">30 天</option><option value="90d">90 天</option><option value="all">全部</option></select>
          </div>
        </div>
        <BacktestChart :equity-curve="portfolioEquityForChart" :drawdown-curve="portfolioDrawdownForChart" :height="320" />
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>收益概览</span><h2>绩效指标</h2></div></div>
        <div class="cq-focus-grid cq-focus-grid--two">
          <div class="cq-focus-card"><span>总盈亏</span><strong>{{ formatCurrency(portfolioStore.summary.total_pnl || 0) }}</strong><small>模拟归因</small></div>
          <div class="cq-focus-card"><span>胜率</span><strong>{{ formatPercent(portfolioStore.summary.win_rate || 0) }}</strong><small>交易质量</small></div>
          <div class="cq-focus-card"><span>盈亏比</span><strong>{{ Number(portfolioStore.summary.profit_factor || 0).toFixed(2) }}</strong><small>收益风险</small></div>
          <div class="cq-focus-card"><span>最大回撤</span><strong>{{ formatPercent(portfolioStore.summary.max_drawdown_pct || 0) }}</strong><small>风险底线</small></div>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline"><div><span>分组归因</span><h2>{{ selectedPortfolioGroup === "symbol" ? "按标的" : "按策略" }}</h2></div><button class="cq-table-eye" @click="selectedPortfolioGroup = selectedPortfolioGroup === 'symbol' ? 'strategy' : 'symbol'">切换</button></div>
        <div class="cq-mini-table">
          <div v-for="item in portfolioGroups.slice(0, 8)" :key="item.key">
            <strong>{{ item.key }}</strong><span>{{ item.trades }} 笔</span><em>{{ formatCurrency(item.pnl || 0) }}</em>
          </div>
          <p v-if="!portfolioGroups.length" class="cq-empty-note">暂无分组收益。</p>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'account'" class="cq-distinct-grid cq-distinct-grid--account" data-feature-role="paper-account">
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>模拟账户</span><h2>资金曲线</h2></div><b>{{ latestEquity?.timestamp || "暂无" }}</b></div>
        <BacktestChart :equity-curve="equityForChart" :drawdown-curve="drawdownForChart" :height="300" />
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>持仓</span><h2>当前资产</h2></div></div>
        <div class="cq-mini-table">
          <div v-for="item in positions" :key="item.symbol">
            <strong>{{ item.symbol }}</strong><span>{{ item.quantity }}</span><em>{{ formatCurrency(item.market_value || 0) }}</em>
          </div>
          <p v-if="!positions.length" class="cq-empty-note">暂无持仓。</p>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline"><div><span>模拟实盘日志</span><h2>PaperBroker 事件</h2></div></div>
        <div class="cq-feature-feed">
          <div v-for="log in logs.slice(0, 8)" :key="log.timestamp + log.message" class="cq-feature-feed-row">
            <strong>{{ log.event || log.event_type || "log" }}</strong><span>{{ log.message || "-" }}</span><small>{{ compactTime(log.timestamp || log.created_at) }}</small>
          </div>
          <p v-if="!logs.length" class="cq-empty-note">暂无日志。</p>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'risk'" class="cq-distinct-grid cq-distinct-grid--risk" data-feature-role="risk-approval">
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>审批规则</span><h2>本地风控闸门</h2></div><b>{{ riskState }}</b></div>
        <div class="cq-command-steps">
          <div v-for="rule in riskRules" :key="rule.label">
            <strong>{{ rule.label }}</strong><span>{{ rule.value }}</span><small>{{ rule.detail }}</small>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>阻断记录</span><h2>最近自动决策</h2></div></div>
        <div class="cq-table-shell">
          <table>
            <thead><tr><th>时间</th><th>交易对</th><th>策略</th><th>动作</th><th>状态</th><th>原因</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in decisions.slice(0, 12)" :key="index">
                <td>{{ compactTime(item.timestamp || item.created_at) }}</td><td>{{ item.symbol || "-" }}</td><td>{{ item.strategy_id || "-" }}</td><td>{{ item.action || item.signal || "HOLD" }}</td><td>{{ item.status || "-" }}</td><td>{{ item.reason || "-" }}</td>
              </tr>
              <tr v-if="!decisions.length"><td colspan="6">暂无决策记录。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'audit'" class="cq-distinct-grid cq-distinct-grid--audit" data-feature-role="audit-trail">
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>订单生命周期</span><h2>审计账本</h2></div><b>{{ orders.length }} 条</b></div>
        <div class="cq-table-shell">
          <table>
            <thead><tr><th>时间</th><th>订单号</th><th>交易对</th><th>方向</th><th>数量</th><th>状态</th><th>来源</th></tr></thead>
            <tbody>
              <tr v-for="order in orders.slice(0, 20)" :key="order.order_id">
                <td>{{ compactTime(order.created_time || order.filled_time) }}</td><td>{{ order.order_id }}</td><td>{{ order.symbol }}</td><td>{{ order.action }}</td><td>{{ order.quantity }}</td><td>{{ order.status }}</td><td>{{ order.strategy || "manual" }}</td>
              </tr>
              <tr v-if="!orders.length"><td colspan="7">暂无订单审计记录。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>事件流</span><h2>模拟日志</h2></div></div>
        <div class="cq-feature-feed">
          <div v-for="log in logs.slice(0, 16)" :key="log.timestamp + log.message" class="cq-feature-feed-row">
            <strong>{{ log.event || log.event_type || "paper" }}</strong><span>{{ log.message || "-" }}</span><small>{{ compactTime(log.timestamp || log.created_at) }}</small>
          </div>
          <p v-if="!logs.length" class="cq-empty-note">暂无审计日志。</p>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'diagnostics'" class="cq-distinct-grid cq-distinct-grid--diagnostics" data-feature-role="diagnostics-radar">
      <article class="cq-feature-panel cq-span-3">
        <div class="cq-panel-headline"><div><span>健康雷达</span><h2>系统诊断</h2></div></div>
        <div class="cq-health-grid">
          <div v-for="item in systemHealth" :key="item.label">
            <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
            <i><b :style="{ width: `${item.score}%` }"></b></i><small>{{ item.score }}/100</small>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>策略状态</span><h2>启用策略</h2></div></div>
        <div class="cq-strategy-stack">
          <div v-for="strategy in autoStore.configDraft.strategies" :key="strategy.strategy_id">
            <strong>{{ strategy.strategy_id }}</strong><span>{{ strategy.type }}</span><em>{{ strategy.enabled ? "启用" : "停用" }}</em>
          </div>
        </div>
      </article>
      <article class="cq-feature-panel cq-span-2">
        <div class="cq-panel-headline"><div><span>异常线索</span><h2>最近错误 / 阻断</h2></div></div>
        <div class="cq-feature-feed">
          <div v-for="(item, index) in decisions.slice(0, 8)" :key="index" class="cq-feature-feed-row">
            <strong>{{ item.symbol || "decision" }}</strong><span>{{ item.reason || item.status || "无异常" }}</span><small>{{ compactTime(item.timestamp || item.created_at) }}</small>
          </div>
          <p v-if="!decisions.length" class="cq-empty-note">暂无诊断异常。</p>
        </div>
      </article>
    </div>

    <div v-else-if="feature === 'settings'" class="cq-distinct-grid cq-distinct-grid--settings" data-feature-role="safety-settings">
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>AI 模型</span><h2>DeepSeek V4</h2></div></div>
        <div class="cq-feature-model-switch cq-feature-model-switch--inline">
          <span>模式</span><strong>{{ modelMode }}</strong>
          <div>
            <button :class="{ active: modelMode === 'Flash' }" @click="setModelMode('Flash')">Flash</button>
            <button :class="{ active: modelMode === 'Pro' }" @click="setModelMode('Pro')">Pro</button>
          </div>
          <small>AI Key 只由后端环境变量读取，不写入前端。</small>
        </div>
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>安全边界</span><h2>交易权限</h2></div><b>真实交易关闭</b></div>
        <div class="cq-command-steps cq-command-steps--compact">
          <div><strong>AI 权限</strong><span>仅建议</span><small>不能直接下单</small></div>
          <div><strong>账户模式</strong><span>Binance 模拟</span><small>PaperBroker</small></div>
          <div><strong>杠杆</strong><span>禁止</span><small>现货模拟</small></div>
        </div>
      </article>
      <article class="cq-feature-panel">
        <div class="cq-panel-headline"><div><span>偏好</span><h2>工作台设置</h2></div></div>
        <label class="cq-toggle-row"><span>提醒音效</span><input v-model="uiStore.soundEnabled" type="checkbox" /></label>
        <label class="cq-toggle-row"><span>行情 WebSocket</span><strong>{{ marketStore.marketSocketState }}</strong></label>
        <label class="cq-toggle-row"><span>系统 WebSocket</span><strong>{{ systemStore.systemSocketState }}</strong></label>
      </article>
    </div>

  </section>
</template>
