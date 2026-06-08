<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { formatCurrency, formatPercent, formatPrice } from "../lib/tradingUtils";

const props = defineProps({
  feature: {
    type: String,
    required: true,
  },
});

const router = useRouter();
const aiStore = useAiAdvisorStore();
const autoStore = useAutoTradingStore();
const marketStore = useMarketStore();
const systemStore = useSystemStore();
const matrixModelMode = ref("Flash");

const FEATURE_COPY = {
  dashboard: {
    eyebrow: "AI 总控矩阵",
    title: "仪表盘",
    subtitle: "把行情、AI 建议、风险审批、模拟成交和复盘放进同一个闭环。",
    focus: "全局指挥",
    primary: "刷新总控",
    secondary: "打开 AI 助手",
    questions: ["当前仓位是否过重？", "今天哪些信号被风控拦截？", "下一次模拟交易前要确认什么？"],
    workItems: ["账户快照", "AI 信号队列", "风险审批状态", "模拟成交追踪"],
  },
  market: {
    eyebrow: "市场感知",
    title: "市场行情",
    subtitle: "行情不再只是价格列表，而是进入 AI 判断和策略上下文的第一站。",
    focus: "行情上下文",
    primary: "刷新行情",
    secondary: "分析当前交易对",
    questions: ["这根 K 线突破可信吗？", "成交量有没有确认趋势？", "当前波动率适合开仓吗？"],
    workItems: ["多交易对行情", "K 线摘要", "量价异常", "AI 市场解读"],
  },
  trade: {
    eyebrow: "模拟执行",
    title: "手动交易",
    subtitle: "所有手动动作都先走本地审批，只生成模拟订单，真实交易保持关闭。",
    focus: "下单前审批",
    primary: "刷新账户",
    secondary: "进入模拟下单",
    questions: ["这笔模拟单是否超过限额？", "卖出会不会超出持仓？", "成交后资金曲线怎么变？"],
    workItems: ["订单草稿", "金额检查", "持仓检查", "模拟撮合"],
  },
  auto: {
    eyebrow: "自动扫描",
    title: "自动交易",
    subtitle: "自动化只负责扫描和生成候选，最终仍落在风控与模拟交易闭环里。",
    focus: "策略扫描",
    primary: "执行扫描",
    secondary: "查看 AI 审批",
    questions: ["最近一次扫描为什么没有下单？", "哪些策略贡献了信号？", "冷却期还剩多久？"],
    workItems: ["策略扫描", "宏观门控", "置信度门槛", "Paper 执行"],
  },
  strategy: {
    eyebrow: "策略建议",
    title: "策略中心",
    subtitle: "策略模板、参数建议和回测结果统一进入 AI 建议面板，审批后才进入模拟盘。",
    focus: "策略闭环",
    primary: "刷新策略",
    secondary: "请求 AI 建议",
    questions: ["RSI 参数是否需要调低？", "均值回归是否逆趋势？", "哪个策略近期回撤最大？"],
    workItems: ["策略模板", "参数优化", "信号归因", "回测验证"],
  },
  portfolio: {
    eyebrow: "复盘资产",
    title: "投资组合",
    subtitle: "把模拟账户、持仓敞口、权益曲线和 AI 建议效果放在同一张账本里。",
    focus: "组合复盘",
    primary: "刷新组合",
    secondary: "询问组合风险",
    questions: ["资金曲线是否进入回撤？", "单币种敞口是否过高？", "AI 建议的胜率如何？"],
    workItems: ["权益曲线", "持仓敞口", "成交归因", "建议复盘"],
  },
  account: {
    eyebrow: "账户状态",
    title: "账户状态",
    subtitle: "展示模拟账户资金、持仓、订单与连接状态，保持真实交易不可用。",
    focus: "模拟账户",
    primary: "刷新账户",
    secondary: "查看模拟日志",
    questions: ["当前可用 USDT 够不够？", "哪些订单仍未完成？", "真实交易状态是否关闭？"],
    workItems: ["USDT 现金", "模拟持仓", "订单状态", "连接状态"],
  },
  risk: {
    eyebrow: "风险审批",
    title: "风控中心",
    subtitle: "每条 AI 或策略信号都要经过金额、仓位、亏损和真实交易开关校验。",
    focus: "审批链路",
    primary: "刷新风控",
    secondary: "查看阻断原因",
    questions: ["这条信号被挡在哪一步？", "最大单笔金额是多少？", "连续亏损会不会触发暂停？"],
    workItems: ["金额上限", "仓位上限", "禁止杠杆", "Kill Switch"],
  },
  audit: {
    eyebrow: "审计日志",
    title: "审计日志",
    subtitle: "记录 AI 建议、人工确认、风控拒绝、模拟下单和撤单的完整证据链。",
    focus: "可追溯",
    primary: "刷新审计",
    secondary: "查看 AI 信号",
    questions: ["哪条建议转成了模拟单？", "拒单原因是什么？", "最近谁触发了扫描？"],
    workItems: ["AI 建议留痕", "审批记录", "订单生命周期", "异常事件"],
  },
  diagnostics: {
    eyebrow: "策略诊断",
    title: "诊断中心",
    subtitle: "围绕策略质量、信号阻断、执行质量和缓存新鲜度做实时诊断。",
    focus: "健康检查",
    primary: "刷新诊断",
    secondary: "询问诊断建议",
    questions: ["哪个模块数据过期？", "策略信号质量如何？", "执行滑点是否异常？"],
    workItems: ["策略状态", "阻断原因", "缓存新鲜度", "执行质量"],
  },
  settings: {
    eyebrow: "系统设置",
    title: "系统设置",
    subtitle: "集中展示模型、账户模式、真实交易状态、提醒和连接偏好。",
    focus: "安全默认",
    primary: "刷新设置",
    secondary: "打开模型助手",
    questions: ["现在用 Flash 还是 Pro？", "API Key 是否只在后端读取？", "真实交易是否永久关闭？"],
    workItems: ["DeepSeek 模型", "模拟账户模式", "提醒音效", "真实交易关闭"],
  },
};

const config = computed(() => FEATURE_COPY[props.feature] || FEATURE_COPY.dashboard);
const selectedSymbol = computed(() => marketStore.selectedCryptoSymbol || "DOGE/USDT");
const quotes = computed(() => marketStore.cryptoQuotes || []);
const selectedQuote = computed(
  () => quotes.value.find((item) => item.symbol === selectedSymbol.value) || quotes.value[0] || null,
);
const lastKline = computed(() => (marketStore.cryptoKlines || []).slice(-1)[0] || null);
const latestPrice = computed(() => Number(selectedQuote.value?.price ?? lastKline.value?.close ?? 0));
const latestSignal = computed(() => aiStore.currentSignal || aiStore.signals[0] || null);
const signalAction = computed(() => latestSignal.value?.action || "HOLD");
const signalConfidence = computed(() => Number(latestSignal.value?.confidence ?? 0.56));
const signalNotional = computed(() => Number(latestSignal.value?.suggested_notional_usdt ?? 300));
const confidenceWidth = computed(() => `${Math.max(8, Math.min(100, signalConfidence.value * 100))}%`);
const riskState = computed(() => {
  if (autoStore.state === "blocked") return "阻断";
  if (autoStore.configDraft.real_trading_enabled) return "异常";
  return "通过";
});
const orders = computed(() => (systemStore.cryptoOrders || []).slice(0, 5));
const positions = computed(() => systemStore.cryptoPositions || []);
const logs = computed(() => {
  const autoLogs = autoStore.logs || [];
  const paperLogs = systemStore.cryptoLogs || [];
  return [...autoLogs, ...paperLogs].slice(-5).reverse();
});
const decisions = computed(() => (autoStore.decisions || []).slice(0, 5));

const metrics = computed(() => [
  {
    label: "最新价",
    value: latestPrice.value ? formatPrice(latestPrice.value) : "--",
    hint: selectedSymbol.value,
    tone: "green",
  },
  {
    label: "账户权益",
    value: formatCurrency(systemStore.liveAccountValue),
    hint: `现金 ${formatCurrency(systemStore.liveCash)}`,
  },
  {
    label: "风险状态",
    value: riskState.value,
    hint: "真实交易关闭",
    tone: riskState.value === "通过" ? "green" : "red",
  },
  {
    label: "模拟订单",
    value: String(systemStore.cryptoOrdersTotal || orders.value.length || 0),
    hint: `${positions.value.length} 个持仓`,
  },
]);

const pipelineSteps = computed(() => [
  { title: "行情快照", status: "通过", detail: `${selectedSymbol.value} / ${marketStore.selectedCryptoPeriod || "1h"}` },
  { title: "AI 建议", status: signalConfidence.value >= 0.65 ? "通过" : "观察", detail: `${signalAction.value} ${formatPercent(signalConfidence.value * 100)}` },
  { title: "策略门控", status: decisions.value.length ? "通过" : "待扫描", detail: config.value.focus },
  { title: "风险审批", status: riskState.value, detail: `上限 ${formatCurrency(autoStore.configDraft.max_order_notional || 300)}` },
  { title: "模拟执行", status: latestSignal.value?.linked_order_id ? "已生成" : "待确认", detail: "仅 PaperBroker" },
]);

const ledgerRows = computed(() => [
  { time: "现在", type: "AI 建议", content: `${signalAction.value} / ${selectedSymbol.value}`, status: "等待人工确认" },
  { time: "T+1", type: "风控审批", content: "金额、仓位、真实交易开关", status: riskState.value },
  { time: "T+2", type: "模拟订单", content: `${formatCurrency(signalNotional.value)} 上限内执行`, status: "Paper only" },
  { time: "T+3", type: "复盘归因", content: "记录后续收益、回撤和失效条件", status: "待统计" },
]);

const focusCards = computed(() =>
  config.value.workItems.map((item, index) => ({
    title: item,
    value: ["已接入", "AI 可读", "审批中", "可复盘"][index] || "监控中",
    hint: ["统一上下文", "结构化摘要", "本地规则", "模拟账本"][index] || "闭环",
  })),
);

function compactTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").slice(5, 16);
}

async function refreshMatrix() {
  const watchSymbols = marketStore.cryptoWatchSymbols?.length
    ? marketStore.cryptoWatchSymbols
    : ["BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT"];
  await Promise.allSettled([
    marketStore.fetchCryptoQuotes(watchSymbols),
    marketStore.fetchCryptoKlines({
      symbol: selectedSymbol.value,
      period: marketStore.selectedCryptoPeriod || "1h",
      limit: 200,
    }),
    systemStore.refreshOverview(),
    autoStore.fetchStatus(),
    aiStore.fetchSignals(),
  ]);
}

async function runPrimaryAction() {
  if (props.feature === "auto") {
    await autoStore.scan().catch(() => {});
  }
  await refreshMatrix();
}

function openAiAdvisor() {
  router.push({ name: "ai-advisor" });
}

function openTrade() {
  router.push({ name: "trade" });
}

function setMatrixModelMode(mode) {
  matrixModelMode.value = mode === "Pro" ? "Pro" : "Flash";
}

onMounted(() => {
  refreshMatrix().catch(() => {});
});
</script>

<template>
  <section class="cq-feature-matrix">
    <div class="cq-feature-grid">
      <main class="cq-feature-main">
        <header class="cq-feature-hero">
          <div>
            <span class="cq-feature-kicker">{{ config.eyebrow }}</span>
            <h1>{{ config.title }}</h1>
            <p>{{ config.subtitle }}</p>
          </div>
          <div class="cq-feature-hero__actions">
            <button class="cq-command-button cq-command-button--primary" type="button" @click="runPrimaryAction">
              {{ config.primary }}
            </button>
            <button class="cq-command-button" type="button" @click="openAiAdvisor">
              {{ config.secondary }}
            </button>
          </div>
        </header>

        <div class="cq-feature-metrics">
          <article
            v-for="metric in metrics"
            :key="metric.label"
            class="cq-feature-metric"
            :class="metric.tone ? `cq-feature-metric--${metric.tone}` : ''"
          >
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
            <small>{{ metric.hint }}</small>
          </article>
        </div>

        <div class="cq-feature-columns">
          <article class="cq-feature-panel cq-feature-panel--signal">
            <div class="cq-panel-headline">
              <div>
                <span>AI 策略建议</span>
                <h2>{{ selectedSymbol }} 信号卡</h2>
              </div>
              <b>DeepSeek V4 {{ matrixModelMode }}</b>
            </div>
            <div class="cq-signal-card">
              <div>
                <span>建议动作</span>
                <strong>{{ signalAction }}</strong>
              </div>
              <div>
                <span>建议金额</span>
                <strong>{{ formatCurrency(signalNotional) }}</strong>
              </div>
              <div>
                <span>置信度</span>
                <strong>{{ signalConfidence.toFixed(2) }}</strong>
              </div>
            </div>
            <div class="cq-confidence-track">
              <i :style="{ width: confidenceWidth }"></i>
            </div>
            <p class="cq-feature-copy">
              {{
                latestSignal?.reason ||
                "当前页面统一使用 AI 总控矩阵：先整理行情和账户上下文，再输出建议，最后交给本地风控审批。"
              }}
            </p>
            <div class="cq-tag-row">
              <span>趋势确认</span>
              <span>风险审批</span>
              <span>模拟闭环</span>
            </div>
          </article>

          <article class="cq-feature-panel">
            <div class="cq-panel-headline">
              <div>
                <span>本地风控审批流程</span>
                <h2>信号到模拟单</h2>
              </div>
              <b>真实交易关闭</b>
            </div>
            <div class="cq-feature-flow">
              <div v-for="(step, index) in pipelineSteps" :key="step.title" class="cq-feature-step">
                <span>{{ index + 1 }}</span>
                <strong>{{ step.title }}</strong>
                <em>{{ step.status }}</em>
                <small>{{ step.detail }}</small>
              </div>
            </div>
          </article>
        </div>

        <section class="cq-feature-panel">
          <div class="cq-panel-headline">
            <div>
              <span>{{ config.focus }}</span>
              <h2>模拟交易闭环账本</h2>
            </div>
            <button class="cq-table-eye" type="button" @click="openTrade">查看交易</button>
          </div>
          <div class="cq-feature-ledger">
            <div v-for="row in ledgerRows" :key="row.type" class="cq-feature-ledger-row">
              <time>{{ row.time }}</time>
              <strong>{{ row.type }}</strong>
              <span>{{ row.content }}</span>
              <em>{{ row.status }}</em>
            </div>
          </div>
        </section>

        <div class="cq-feature-columns cq-feature-columns--bottom">
          <article class="cq-feature-panel">
            <div class="cq-panel-headline">
              <div>
                <span>模块能力</span>
                <h2>{{ config.title }} 工作台</h2>
              </div>
            </div>
            <div class="cq-focus-grid">
              <div v-for="card in focusCards" :key="card.title" class="cq-focus-card">
                <span>{{ card.title }}</span>
                <strong>{{ card.value }}</strong>
                <small>{{ card.hint }}</small>
              </div>
            </div>
          </article>

          <article class="cq-feature-panel">
            <div class="cq-panel-headline">
              <div>
                <span>最近事件</span>
                <h2>订单 / 决策 / 日志</h2>
              </div>
            </div>
            <div class="cq-feature-feed">
              <div v-for="order in orders" :key="order.order_id || order.created_time" class="cq-feature-feed-row">
                <strong>{{ order.symbol || selectedSymbol }}</strong>
                <span>{{ order.side || order.status || "paper" }}</span>
                <small>{{ compactTime(order.created_time || order.filled_time) }}</small>
              </div>
              <div v-for="decision in decisions" :key="decision.symbol + decision.created_at" class="cq-feature-feed-row">
                <strong>{{ decision.symbol || selectedSymbol }}</strong>
                <span>{{ decision.action || decision.status || "decision" }}</span>
                <small>{{ compactTime(decision.created_at || decision.timestamp) }}</small>
              </div>
              <div v-for="log in logs" :key="log.created_at || log.message" class="cq-feature-feed-row">
                <strong>{{ log.event_type || log.type || "log" }}</strong>
                <span>{{ log.message || log.status || "模拟事件" }}</span>
                <small>{{ compactTime(log.created_at || log.timestamp) }}</small>
              </div>
              <p v-if="!orders.length && !decisions.length && !logs.length" class="cq-empty-note">
                暂无事件，刷新后会显示 AI 建议、审批记录和模拟订单。
              </p>
            </div>
          </article>
        </div>
      </main>

      <aside class="cq-feature-copilot">
        <div class="cq-feature-copilot__head">
          <img src="/assets/huuquant-bot.png" alt="HuuQuantAI" />
          <div>
            <span>量化副驾驶</span>
            <strong>AI 只做建议，不能直接下单</strong>
          </div>
        </div>
        <div class="cq-feature-copilot__message">
          <b>{{ config.title }}已接入 AI 总控矩阵。</b>
          <p>
            当前 {{ selectedSymbol }} 最新价 {{ latestPrice ? formatPrice(latestPrice) : "--" }}，账户可用现金
            {{ formatCurrency(systemStore.liveCash) }}。所有建议必须通过本地风控和手动确认，才会进入模拟交易。
          </p>
        </div>
        <div class="cq-feature-question-list">
          <button v-for="question in config.questions" :key="question" type="button" @click="openAiAdvisor">
            {{ question }}
          </button>
        </div>
        <div class="cq-feature-model-switch">
          <span>AI 模型</span>
          <strong>DeepSeek V4</strong>
          <div>
            <button type="button" :class="{ active: matrixModelMode === 'Flash' }" @click="setMatrixModelMode('Flash')">
              Flash
            </button>
            <button type="button" :class="{ active: matrixModelMode === 'Pro' }" @click="setMatrixModelMode('Pro')">
              Pro
            </button>
          </div>
          <small>模型切换在 AI 助手中生效，真实交易始终关闭。</small>
        </div>
        <button class="cq-command-button cq-command-button--primary cq-feature-full-button" type="button" @click="openAiAdvisor">
          打开 AI 对话助手
        </button>
      </aside>
    </div>
  </section>
</template>
