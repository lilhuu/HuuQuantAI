import { computed } from "vue";
import { useRoute } from "vue-router";

import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useTradingStore } from "../stores/trading";

export const routeModuleMap = {
  "/": "dashboard",
  "/market": "market",
  "/trade": "manual_trade",
  "/auto": "auto_trade",
  "/ai": "ai_assistant",
  "/strategy": "strategy",
  "/backtest": "backtest",
  "/portfolio": "portfolio",
  "/account": "account",
  "/risk": "risk",
  "/audit": "audit",
  "/diagnostics": "diagnostics",
  "/settings": "settings",
};

export const moduleLabels = {
  dashboard: "仪表盘",
  market: "市场行情",
  manual_trade: "手动交易",
  auto_trade: "自动交易",
  ai_assistant: "AI 助手",
  strategy: "策略中心",
  backtest: "回测中心",
  portfolio: "投资组合",
  account: "账户状态",
  risk: "风控中心",
  audit: "审计日志",
  diagnostics: "诊断中心",
  settings: "系统设置",
};

const routeQuestionMap = {
  dashboard: ["帮我总结当前系统状态", "当前最重要的风险是什么？", "下一步应该检查哪个模块？"],
  market: ["帮我解释当前 K 线走势", "成交量有没有确认趋势？", "当前行情适合观察哪些风险？"],
  manual_trade: ["这笔模拟单提交前要检查什么？", "卖出会不会超过持仓？", "这笔订单可能被哪些风控挡住？"],
  auto_trade: ["为什么自动交易没有下单？", "最近一次扫描卡在哪一步？", "自动交易配置应该先看哪里？"],
  ai_assistant: ["AI 为什么给这个建议？", "这个建议能不能生成模拟订单？", "AI 的风险提示应该怎么看？"],
  strategy: ["当前策略结果怎么看？", "哪个策略信号更可靠？", "策略冲突时应该看哪些字段？"],
  backtest: ["这次回测结果是否稳定？", "最大回撤和胜率怎么看？", "参数是否有过拟合风险？"],
  portfolio: ["帮我分析当前组合风险", "组合收益主要来自哪里？", "仓位是否过于集中？"],
  account: ["帮我解释当前模拟账户状态", "当前可用资金够不够？", "哪些持仓需要重点关注？"],
  risk: ["这个风控阻断是什么意思？", "当前是否允许生成模拟订单？", "怎样理解最大单笔和持仓限制？"],
  audit: ["帮我复盘最近订单生命周期", "最近有哪些拒单或异常？", "哪条 AI 建议关联了模拟订单？"],
  diagnostics: ["当前系统哪里可能不健康？", "为什么数据没有刷新？", "策略或行情连接是否异常？"],
  settings: ["当前 AI 和交易安全配置是否正常？", "现在使用的是 Flash 还是 Pro？", "真实交易是否保持关闭？"],
};

const routeGuideMap = {
  dashboard: ["查看系统状态", "检查安全边界", "打开风控概览"],
  market: ["分析行情和 K 线", "检查数据源状态", "刷新实时行情"],
  manual_trade: ["创建手动模拟订单", "提交前检查风险", "查看最近订单"],
  auto_trade: ["排查为什么没下单", "运行一次自动扫描", "检查自动交易开关"],
  ai_assistant: ["解释 AI 建议", "生成模拟订单前检查", "切换模型对比"],
  strategy: ["运行策略信号", "跑一次策略回测", "解释策略冲突"],
  backtest: ["跑一次策略回测", "解释回测指标", "检查参数稳定性"],
  portfolio: ["查看组合风险", "复盘资金曲线", "检查仓位集中度"],
  account: ["检查模拟账户", "核对持仓和订单", "解释账户权益"],
  risk: ["查看风控阻断原因", "检查 Kill Switch", "检查风险预算"],
  audit: ["复盘订单审计日志", "查找拒单原因", "追踪 AI 建议来源"],
  diagnostics: ["排查系统诊断问题", "检查 AI 是否可用", "检查行情健康度"],
  settings: ["检查安全配置", "切换模型前确认", "确认真实交易关闭"],
};

const fallbackQuestions = [
  "这个项目怎么用？",
  "自动交易为什么没有下单？",
  "风控中心这些指标是什么意思？",
  "帮我解释当前模拟账户风险",
];

export function useCopilotContext(options = {}) {
  const route = useRoute();
  const aiAdvisor = useAiAdvisorStore();
  const autoTrading = useAutoTradingStore();
  const market = useMarketStore();
  const system = useSystemStore();
  const trading = useTradingStore();

  const currentRoutePath = computed(() => route.path || "/");
  const currentModule = computed(() => routeModuleMap[currentRoutePath.value] || "");
  const currentModuleLabel = computed(() => moduleLabels[currentModule.value] || "当前页面");
  const currentViewTitle = computed(() => route.meta?.title || route.name || currentModuleLabel.value);
  const selectedSymbol = computed(() =>
    normalizeCryptoSymbol(options.symbol?.value || trading.selectedCryptoSymbol || "BTC/USDT"),
  );
  const selectedPeriod = computed(() => options.period?.value || trading.selectedCryptoPeriod || "1h");
  const selectedLimit = computed(() => Number(options.limit?.value || 120));

  const suggestedQuestions = computed(() => {
    const routeQuestions = routeQuestionMap[currentModule.value] || fallbackQuestions;
    return ["这个项目怎么用？", ...routeQuestions].slice(0, 4);
  });

  const guideActions = computed(() => routeGuideMap[currentModule.value] || ["查看系统状态", "排查为什么没下单", "跑一次策略回测"]);

  const visibleContext = computed(() => ({
    route: currentRoutePath.value,
    module: currentModule.value,
    module_label: currentModuleLabel.value,
    view_title: String(currentViewTitle.value || ""),
    selected_symbol: selectedSymbol.value,
    selected_period: selectedPeriod.value,
    kline_limit: selectedLimit.value,
    selected_model: options.selectedModel?.value || "deepseek-v4-flash",
    include_project_and_market_context: options.includeContext?.value !== false,
    guide_mode: Boolean(options.guideMode?.value),
    selected_guide_goal: options.selectedGuideGoal?.value || "",
    market: {
      quote_count: market.cryptoQuotes?.length || 0,
      kline_count: market.cryptoKlines?.length || 0,
      socket_state: market.marketSocketState || "",
      selected_price: market.cryptoKlines?.at?.(-1)?.close || null,
    },
    account: {
      cash: system.liveCash,
      account_value: system.liveAccountValue,
      position_value: system.livePositionValue,
      positions_count: system.cryptoPositions?.length || 0,
      orders_count: system.cryptoOrders?.length || 0,
    },
    automation: {
      state: autoTrading.state || "idle",
      loop_running: Boolean(autoTrading.loopRunning),
      decisions_count: autoTrading.decisions?.length || 0,
    },
    ai: {
      current_signal_action: aiAdvisor.currentSignal?.action || "",
      current_signal_status: aiAdvisor.currentSignal?.approval_status || "",
    },
    safety: {
      trading_mode: "paper_trading",
      real_trading_enabled: false,
      ai_can_place_orders: false,
    },
  }));

  return {
    currentRoutePath,
    currentModule,
    currentModuleLabel,
    currentViewTitle,
    selectedSymbol,
    selectedPeriod,
    selectedLimit,
    suggestedQuestions,
    guideActions,
    visibleContext,
  };
}
