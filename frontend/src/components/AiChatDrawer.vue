<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAiChatStore } from "../stores/aiChat";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useTradingStore } from "../stores/trading";

const route = useRoute();
const router = useRouter();
const aiAdvisor = useAiAdvisorStore();
const aiChat = useAiChatStore();
const autoTrading = useAutoTradingStore();
const market = useMarketStore();
const system = useSystemStore();
const trading = useTradingStore();

const draft = ref("");
const symbol = ref(normalizeCryptoSymbol(trading.selectedCryptoSymbol || "BTC/USDT"));
const period = ref(trading.selectedCryptoPeriod || "1h");
const limit = ref(120);
const includeContext = ref(true);
const guideMode = ref(false);
const selectedGuideGoal = ref("");
const selectedModel = ref("deepseek-v4-flash");
const messageList = ref(null);
const CHAT_DRAFT_LIMIT = 500;

const periodOptions = ["1m", "5m", "15m", "1h", "4h", "1d"];
const modelOptions = [
  { label: "Flash", value: "deepseek-v4-flash" },
  { label: "Pro", value: "deepseek-v4-pro" },
];
const routeModuleMap = {
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
const routeQuestionMap = {
  dashboard: ["帮我总结当前系统状态", "当前最重要的风险是什么？", "下一步应该检查哪个模块？"],
  market: ["帮我解释当前 K 线走势", "成交量有没有确认趋势？", "当前行情适合观察哪些风险？"],
  manual_trade: ["这笔模拟单提交前要检查什么？", "卖出会不会超过持仓？", "这笔订单可能被哪些风控挡住？"],
  auto_trade: ["为什么自动交易没有下单？", "最近一次扫描卡在哪一步？", "自动交易配置应该先看哪里？"],
  ai_assistant: ["AI 为什么给这个建议？", "这个建议能不能生成模拟订单？", "AI 的风险提示该怎么看？"],
  strategy: ["当前策略结果怎么看？", "哪个策略信号更可靠？", "策略冲突时应该看哪些字段？"],
  portfolio: ["帮我分析当前组合风险", "组合收益主要来自哪里？", "仓位是否过于集中？"],
  account: ["帮我解释当前模拟账户状态", "当前可用资金够不够？", "哪些持仓需要重点关注？"],
  risk: ["这个风控阻断是什么意思？", "当前是否允许生成模拟订单？", "怎样理解最大单笔和持仓限制？"],
  audit: ["帮我复盘最近订单生命周期", "最近有哪些拒单或异常？", "哪条 AI 建议关联了模拟订单？"],
  diagnostics: ["当前系统哪里可能不健康？", "为什么数据没有刷新？", "策略或行情连接是否异常？"],
  settings: ["当前 AI 和交易安全配置是否正常？", "现在使用的是 Flash 还是 Pro？", "真实交易是否保持关闭？"],
};
const routeGuideMap = {
  dashboard: ["检查行情连接", "查看模拟账户", "打开风险概览"],
  market: ["解释当前 K 线", "检查盘口深度", "刷新实时行情"],
  manual_trade: ["检查下单风险", "核对可用资金", "查看最近订单"],
  auto_trade: ["查看扫描日志", "解释未下单原因", "检查自动交易开关"],
  ai_assistant: ["解释最新 AI 信号", "检查安全边界", "切换模型对比"],
  strategy: ["跑一次策略回测", "解释策略冲突", "检查参数过拟合"],
  portfolio: ["分析组合收益", "检查仓位集中度", "查看资金曲线"],
  account: ["解释账户权益", "检查持仓风险", "查看成交日志"],
  risk: ["解释风控阻断", "检查风险预算", "查看真实交易状态"],
  audit: ["复盘订单生命周期", "检查异常事件", "追踪 AI 建议来源"],
  diagnostics: ["检查行情健康", "检查策略健康", "定位数据刷新问题"],
  settings: ["检查 AI 配置", "检查交易安全开关", "确认真实交易关闭"],
};
const routeGuideOverrides = {
  dashboard: ["查看系统状态", "检查安全边界"],
  market: ["分析行情和 K 线", "检查数据源状态"],
  manual_trade: ["创建手动模拟订单", "提交前检查风险"],
  auto_trade: ["排查为什么没下单", "运行一次自动扫描"],
  ai_assistant: ["解释 AI 建议", "生成模拟订单前检查"],
  strategy: ["跑一次策略回测", "运行策略信号"],
  backtest: ["跑一次策略回测", "解释回测指标"],
  portfolio: ["查看组合风险", "复盘资金曲线"],
  account: ["检查模拟账户", "核对持仓和订单"],
  risk: ["查看风控阻断原因", "检查 Kill Switch"],
  audit: ["复盘订单审计日志", "查找拒单原因"],
  diagnostics: ["排查系统诊断问题", "检查 AI 是否可用"],
  settings: ["检查安全配置", "切换模型前确认"],
};
const fallbackQuestions = [
  "这个项目怎么用？",
  "自动交易为什么没有下单？",
  "风控中心这些指标是什么意思？",
  "帮我解释当前模拟账户风险",
];

const pairOptions = computed(() => {
  const base = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", ...trading.cryptoWatchSymbols];
  return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
});

const canSend = computed(() => draft.value.trim().length > 0 && !aiChat.loading);
const draftLength = computed(() => draft.value.length);
const currentRoutePath = computed(() => route.path || "/");
const currentModule = computed(() => routeModuleMap[currentRoutePath.value] || "");
const currentViewTitle = computed(() => route.meta?.title || route.name || "HuuQuantAI");
const suggestedQuestions = computed(() => {
  const routeQuestions = routeQuestionMap[currentModule.value] || fallbackQuestions;
  return ["这个项目怎么用？", ...routeQuestions].slice(0, 4);
});
const guideActions = computed(
  () => routeGuideOverrides[currentModule.value] || routeGuideMap[currentModule.value] || ["查看系统状态", "排查为什么没下单", "跑一次策略回测"],
);
const visibleActionCards = computed(() => aiChat.latestActionCards || []);
const visibleContext = computed(() => ({
  route: currentRoutePath.value,
  module: currentModule.value,
  selected_symbol: symbol.value,
  selected_period: period.value,
  kline_limit: Number(limit.value || 120),
  selected_model: selectedModel.value,
  include_project_and_market_context: includeContext.value,
  guide_mode: guideMode.value,
  selected_guide_goal: selectedGuideGoal.value,
  market: {
    quote_count: market.cryptoQuotes?.length || 0,
    kline_count: market.cryptoKlines?.length || 0,
    socket_state: market.marketSocketState || "",
  },
  account: {
    cash: system.liveCash,
    account_value: system.liveAccountValue,
    position_value: system.livePositionValue,
    positions_count: system.cryptoPositions?.length || 0,
    orders_count: system.cryptoOrders?.length || 0,
  },
  automation: {
    state: autoTrading.state,
    loop_running: autoTrading.loopRunning,
    decisions_count: autoTrading.decisions?.length || 0,
  },
  ai: {
    current_signal_action: aiAdvisor.currentSignal?.action || "",
    current_signal_status: aiAdvisor.currentSignal?.approval_status || "",
  },
}));

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}

function useSuggestedQuestion(question) {
  guideMode.value = false;
  selectedGuideGoal.value = "";
  draft.value = String(question || "").slice(0, CHAT_DRAFT_LIMIT);
}

function useGuideAction(action) {
  guideMode.value = true;
  selectedGuideGoal.value = String(action || "").trim();
  draft.value = selectedGuideGoal.value.slice(0, CHAT_DRAFT_LIMIT);
}

function handleActionCard(card) {
  const actionType = String(card?.action_type || "");
  if (actionType === "navigate" && card?.target_route) {
    router.push(String(card.target_route));
    return;
  }
  if (actionType === "inspect" && card?.target_route) {
    router.push(String(card.target_route));
    return;
  }
  if (actionType === "explain" || actionType === "inspect") {
    guideMode.value = true;
    selectedGuideGoal.value = String(card?.title || "解释当前页面");
    draft.value = `${selectedGuideGoal.value}：${String(card?.description || "请结合当前页面状态说明。")}`.slice(
      0,
      CHAT_DRAFT_LIMIT,
    );
  }
}

async function send() {
  if (!canSend.value) {
    return;
  }
  const message = draft.value.trim();
  draft.value = "";
  try {
    await aiChat.sendMessage({
      message,
      symbol: symbol.value,
      period: period.value,
      limit: limit.value,
      include_context: includeContext.value,
      model: selectedModel.value,
      current_route: currentRoutePath.value,
      current_module: currentModule.value,
      current_view_title: String(currentViewTitle.value || ""),
      visible_context: visibleContext.value,
      guide_mode: guideMode.value,
      user_goal: guideMode.value ? selectedGuideGoal.value || message : "",
    });
  } catch (error) {
    draft.value = message;
  } finally {
    scrollToBottom();
  }
}

function handleKeydown(event) {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    send();
  }
}

function syncDraft(event) {
  draft.value = String(event?.target?.value || "").slice(0, CHAT_DRAFT_LIMIT);
}

watch(
  () => trading.selectedCryptoSymbol,
  (nextSymbol) => {
    const normalized = normalizeCryptoSymbol(nextSymbol);
    if (normalized) {
      symbol.value = normalized;
    }
  },
);

watch(
  () => aiChat.drawerOpen,
  (open) => {
    if (open) {
      aiChat.fetchSessions().catch(() => {});
      scrollToBottom();
    }
  },
);

watch(
  () => aiChat.messages.length,
  () => scrollToBottom(),
);
</script>

<template>
  <Teleport to="body">
    <div v-if="aiChat.drawerOpen" class="ai-chat-backdrop" @click.self="aiChat.closeDrawer()">
      <aside class="ai-chat-drawer" aria-label="AI 项目副驾驶">
        <header class="ai-chat-header">
          <div>
            <span>AI 对话助手</span>
            <strong>项目副驾驶</strong>
          </div>
          <button class="cq-icon-button" title="关闭 AI 对话" aria-label="关闭 AI 对话" @click="aiChat.closeDrawer()">×</button>
        </header>

        <section class="ai-chat-body">
          <aside class="ai-chat-sessions">
            <button class="cq-primary-button ai-chat-new" @click="aiChat.startNewSession()">新对话</button>
            <div class="ai-chat-session-list">
              <button
                v-for="sessionItem in aiChat.sessions"
                :key="sessionItem.session_id"
                class="ai-chat-session"
                :class="{ active: aiChat.currentSession?.session_id === sessionItem.session_id }"
                @click="aiChat.loadSession(sessionItem.session_id)"
              >
                <strong>{{ sessionItem.title || "AI 对话" }}</strong>
                <span>{{ sessionItem.last_message || "暂无消息" }}</span>
              </button>
              <p v-if="!aiChat.sessions.length && !aiChat.loadingSessions" class="ai-chat-empty">暂无历史会话</p>
            </div>
          </aside>

          <main class="ai-chat-main">
            <div class="ai-chat-context">
              <label>
                <span>交易对</span>
                <select v-model="symbol">
                  <option v-for="item in pairOptions" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label>
                <span>周期</span>
                <select v-model="period">
                  <option v-for="item in periodOptions" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label>
                <span>K 线</span>
                <input v-model.number="limit" type="number" min="30" max="500" step="10" />
              </label>
              <label class="ai-chat-toggle">
                <input v-model="includeContext" type="checkbox" />
                <span>带项目和行情上下文</span>
              </label>
              <label class="ai-chat-toggle">
                <input v-model="guideMode" type="checkbox" />
                <span>引导模式</span>
              </label>
            </div>

            <div ref="messageList" class="ai-chat-messages">
              <div v-if="!aiChat.hasMessages" class="ai-chat-welcome">
                <strong>真实交易关闭，AI 是项目副驾驶，不能直接下单。</strong>
                <p>
                  可以正常聊天，也可以问项目怎么用、每个模块做什么、策略和回测怎么理解、
                  风控中心为什么阻断、模拟账户和订单状态怎么看。
                </p>
                <span class="ai-chat-section-title">问项目问题</span>
                <div class="ai-chat-suggestions" aria-label="推荐问题">
                  <button
                    v-for="question in suggestedQuestions"
                    :key="question"
                    type="button"
                    @click="useSuggestedQuestion(question)"
                  >
                    {{ question }}
                  </button>
                </div>
                <div class="ai-chat-guide" aria-label="引导模式">
                  <span class="ai-chat-section-title">让我一步一步带你操作</span>
                  <button
                    v-for="action in guideActions"
                    :key="action"
                    type="button"
                    @click="useGuideAction(action)"
                  >
                    {{ action }}
                  </button>
                </div>
              </div>
              <article
                v-for="message in aiChat.messages"
                :key="message.message_id"
                class="ai-chat-message"
                :class="`ai-chat-message--${message.role}`"
              >
                <span>{{ message.role === "user" ? "你" : "AI" }}</span>
                <p>{{ message.content }}</p>
              </article>
              <article v-if="aiChat.loading" class="ai-chat-message ai-chat-message--assistant">
                <span>AI</span>
                <p>正在结合当前页面、项目模块、行情、账户和风控状态思考...</p>
              </article>
              <div v-if="visibleActionCards.length" class="ai-chat-action-cards" aria-label="AI 安全动作卡片">
                <button
                  v-for="card in visibleActionCards"
                  :key="card.id || card.title"
                  type="button"
                  class="ai-chat-action-card"
                  :data-action-card-id="card.id"
                  @click="handleActionCard(card)"
                >
                  <strong>{{ card.title }}</strong>
                  <span>{{ card.description }}</span>
                  <small>{{ card.action_type }} · {{ card.risk_level || "safe" }}</small>
                </button>
              </div>
            </div>

            <p v-if="aiChat.errorMessage" class="ai-chat-error">{{ aiChat.errorMessage }}</p>

            <footer class="ai-chat-composer">
              <textarea
                v-model="draft"
                data-ai-drawer-input="message"
                :maxlength="CHAT_DRAFT_LIMIT"
                rows="3"
                placeholder="例如：这个页面怎么用？为什么这里没有下单？这个风控阻断是什么意思？"
                @input="syncDraft"
                @compositionend="syncDraft"
                @keydown="handleKeydown"
              ></textarea>
              <div class="ai-chat-actions">
                <span class="ai-chat-draft-count" data-ai-drawer-count="message">{{ draftLength }}/{{ CHAT_DRAFT_LIMIT }}</span>
                <div class="ai-chat-model-switch" aria-label="模型选择">
                  <button
                    v-for="option in modelOptions"
                    :key="option.value"
                    type="button"
                    :class="{ active: selectedModel === option.value }"
                    :title="`使用 ${option.label} 模型回复`"
                    @click="selectedModel = option.value"
                  >
                    {{ option.label }}
                  </button>
                </div>
                <button
                  class="cq-outline-button"
                  :disabled="!aiChat.currentSession"
                  @click="aiChat.deleteSession()"
                >
                  删除会话
                </button>
                <button class="cq-primary-button" data-ai-drawer-send="message" :disabled="!canSend" @click="send">
                  {{ aiChat.loading ? "思考中" : "发送" }}
                </button>
              </div>
            </footer>
          </main>
        </section>
      </aside>
    </div>
  </Teleport>
</template>
