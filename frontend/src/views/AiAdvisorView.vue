<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";

import CryptoKlineChart from "../components/CryptoKlineChart.vue";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAiChatStore } from "../stores/aiChat";
import { useMarketStore } from "../stores/market";
import { useTradingStore } from "../stores/trading";

const aiStore = useAiAdvisorStore();
const aiChat = useAiChatStore();
const marketStore = useMarketStore();
const trading = useTradingStore();

const form = reactive({
  symbol: trading.selectedCryptoSymbol || "BTC/USDT",
  period: trading.selectedCryptoPeriod || "1h",
  limit: 120,
});

const draft = ref("");
const selectedModel = ref("deepseek-v4-flash");
const messageList = ref(null);

const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];
const modelOptions = [
  { label: "Flash", value: "deepseek-v4-flash" },
  { label: "Pro", value: "deepseek-v4-pro" },
];

const pairOptions = computed(() => {
  const base = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", ...trading.cryptoWatchSymbols];
  return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
});
const signal = computed(() => aiStore.currentSignal);
const advice = computed(() => signal.value?.response || {});
const candles = computed(() => marketStore.cryptoKlines || []);
const canCreatePaperOrder = computed(() => signal.value?.approval_status === "approved");
const canSend = computed(() => draft.value.trim().length > 0 && !aiChat.loading);

const decisionSteps = computed(() => {
  const status = signal.value?.approval_status || "pending";
  const hasSignal = Boolean(signal.value);
  const approved = status === "approved" || status === "ordered";
  const blocked = ["blocked", "rejected", "failed"].includes(status);
  return [
    { label: "行情数据", detail: candles.value.length ? `${candles.value.length} 根 K 线已就绪` : "等待加载", state: candles.value.length ? "pass" : "idle" },
    { label: "策略信号", detail: hasSignal ? `${advice.value.action || signal.value.action} / ${Number(advice.value.confidence || 0).toFixed(2)}` : "等待 AI 分析", state: hasSignal ? "pass" : "idle" },
    { label: "宏观门控", detail: "禁止杠杆和做空", state: hasSignal ? "pass" : "idle" },
    { label: "风控审批", detail: signal.value?.approval_reason || "等待本地审批", state: approved ? "pass" : blocked ? "blocked" : "idle" },
    { label: "模拟订单", detail: signal.value?.linked_order_id || "手动确认后生成", state: signal.value?.linked_order_id ? "pass" : "idle" },
  ];
});

const diagnostics = computed(() => [
  { label: "RSI / 动量", value: advice.value.action === "HOLD" ? "中性" : "待复核", tone: "neutral" },
  { label: "趋势状态", value: advice.value.time_horizon || form.period, tone: "active" },
  { label: "最大亏损", value: `${Number(advice.value.max_loss_usdt || 0).toFixed(2)} USDT`, tone: "warn" },
  { label: "建议金额", value: `${Number(advice.value.suggested_notional_usdt || 0).toFixed(2)} USDT`, tone: "active" },
]);

async function loadKlines() {
  const symbol = normalizeCryptoSymbol(form.symbol);
  form.symbol = symbol || "BTC/USDT";
  await marketStore.fetchCryptoKlines({
    symbol: form.symbol,
    period: form.period,
    limit: Number(form.limit || 120),
  });
}

async function analyze() {
  await loadKlines();
  await aiStore.analyze(form);
}

async function createPaperOrder() {
  await aiStore.createPaperOrder();
}

async function sendChat() {
  if (!canSend.value) return;
  const message = draft.value;
  draft.value = "";
  await aiChat.sendMessage({
    message,
    symbol: form.symbol,
    period: form.period,
    limit: Number(form.limit || 120),
    include_context: true,
    model: selectedModel.value,
  });
  scrollChat();
}

function scrollChat() {
  nextTick(() => {
    if (messageList.value) {
      messageList.value.scrollTop = messageList.value.scrollHeight;
    }
  });
}

function handleChatKeydown(event) {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendChat();
  }
}

function badgeClass(status) {
  if (status === "approved" || status === "ordered") return "status-chip--connected";
  if (status === "blocked" || status === "rejected" || status === "failed") return "status-chip--error";
  return "status-chip--idle";
}

function stepClass(state) {
  return {
    "cq-decision-step--pass": state === "pass",
    "cq-decision-step--blocked": state === "blocked",
  };
}

watch(
  () => trading.selectedCryptoSymbol,
  (nextSymbol) => {
    const normalized = normalizeCryptoSymbol(nextSymbol);
    if (normalized) form.symbol = normalized;
  },
);

watch(
  () => aiChat.messages.length,
  () => scrollChat(),
);

onMounted(() => {
  aiStore.fetchSignals().catch(() => {});
  aiChat.fetchSessions().catch(() => {});
  loadKlines().catch(() => {});
});
</script>

<template>
  <section class="cq-ai-workbench">
    <header class="cq-ai-hero">
      <div>
        <span class="eyebrow">AI Copilot Workbench</span>
        <h1>量化副驾驶</h1>
        <p>DeepSeek 只提供结构化建议，本地风控负责审批，所有订单都必须手动确认并进入模拟交易。</p>
      </div>
      <div class="cq-ai-hero__controls">
        <label>
          <span>交易对</span>
          <select v-model="form.symbol" @change="loadKlines">
            <option v-for="symbol in pairOptions" :key="symbol" :value="symbol">{{ symbol }}</option>
          </select>
        </label>
        <label>
          <span>周期</span>
          <select v-model="form.period" @change="loadKlines">
            <option v-for="period in periods" :key="period" :value="period">{{ period }}</option>
          </select>
        </label>
        <label>
          <span>K 线</span>
          <input v-model.number="form.limit" type="number" min="30" max="500" step="10" @change="loadKlines" />
        </label>
        <span class="cq-safety-lock">真实交易关闭</span>
      </div>
    </header>

    <div class="cq-ai-cockpit-grid">
      <main class="cq-ai-cockpit-main">
        <article class="cq-panel cq-chart-command">
          <div class="cq-panel__heading">
            <div>
              <h2>{{ form.symbol }} 智能行情上下文</h2>
              <p>AI 分析前会先刷新 K 线，让建议基于当前市场状态。</p>
            </div>
            <div class="button-row">
              <button class="ghost-button" @click="loadKlines">刷新 K 线</button>
              <button class="primary-button" :disabled="aiStore.loading" @click="analyze">
                {{ aiStore.loading ? "分析中..." : "AI 分析建议" }}
              </button>
            </div>
          </div>
          <div class="cq-copilot-chart">
            <CryptoKlineChart v-if="candles.length" :candles="candles" :height="360" />
            <div v-else class="cq-chart-empty-state">
              <strong>等待 K 线数据</strong>
              <p>点击“刷新 K 线”从 Binance 公共行情加载，网络不可用时仍可先使用 AI 对话和历史复盘。</p>
            </div>
          </div>
          <p v-if="aiStore.errorMessage" class="helper-text text-rise">{{ aiStore.errorMessage }}</p>
        </article>

        <section class="cq-ai-split">
          <article class="cq-panel">
            <div class="cq-panel__heading">
              <div>
                <h2>AI 信号分析</h2>
                <p>建议动作、金额和失效条件会被保存，用于复盘模型表现。</p>
              </div>
              <span v-if="signal" class="status-chip" :class="badgeClass(signal.approval_status)">
                {{ signal.approval_status }}
              </span>
            </div>

            <div v-if="signal" class="cq-ai-signal cq-ai-signal--compact">
              <div class="cq-ai-action">
                <span>{{ signal.symbol }}</span>
                <strong>{{ advice.action || signal.action }}</strong>
                <small>confidence {{ Number(advice.confidence || 0).toFixed(2) }}</small>
              </div>
              <div class="cq-health-grid">
                <div>
                  <span>建议金额</span>
                  <strong>{{ Number(advice.suggested_notional_usdt || 0).toFixed(2) }} USDT</strong>
                </div>
                <div>
                  <span>审批金额</span>
                  <strong>{{ Number(signal.approved_notional_usdt || 0).toFixed(2) }} USDT</strong>
                </div>
                <div>
                  <span>时间窗口</span>
                  <strong>{{ advice.time_horizon || "-" }}</strong>
                </div>
              </div>
              <div class="cq-ai-notes">
                <h3>核心理由</h3>
                <p>{{ advice.reason || signal.approval_reason }}</p>
                <h3>风险点</h3>
                <ul>
                  <li v-for="item in advice.risk_notes || []" :key="item">{{ item }}</li>
                </ul>
                <h3>失效条件</h3>
                <ul>
                  <li v-for="item in advice.invalid_if || []" :key="item">{{ item }}</li>
                </ul>
              </div>
            </div>
            <p v-else class="cq-empty-copy">暂无 AI 建议。点击“AI 分析建议”生成结构化信号。</p>
          </article>

          <article class="cq-panel">
            <div class="cq-panel__heading">
              <div>
                <h2>本地风控审批流</h2>
                <p>AI 不能直接下单，必须逐级通过本地规则。</p>
              </div>
              <button class="ghost-button" :disabled="!canCreatePaperOrder || aiStore.ordering" @click="createPaperOrder">
                {{ aiStore.ordering ? "生成中..." : "手动生成模拟订单" }}
              </button>
            </div>

            <div class="cq-decision-flow">
              <article
                v-for="(step, index) in decisionSteps"
                :key="step.label"
                class="cq-decision-step"
                :class="stepClass(step.state)"
              >
                <span>{{ index + 1 }}</span>
                <strong>{{ step.label }}</strong>
                <p>{{ step.detail }}</p>
              </article>
            </div>

            <div class="cq-diagnostics-strip">
              <div v-for="item in diagnostics" :key="item.label" class="cq-diagnostic-card" :data-tone="item.tone">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
          </article>
        </section>

        <article class="cq-panel cq-ai-history">
          <div class="cq-panel__heading">
            <div>
              <h2>AI 建议历史</h2>
              <p>用于观察 Flash / Pro 建议质量、审批通过率和模拟订单后续表现。</p>
            </div>
            <button class="cq-outline-button" @click="aiStore.fetchSignals()">刷新历史</button>
          </div>

          <table class="cq-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>交易对</th>
                <th>动作</th>
                <th>置信度</th>
                <th>审批</th>
                <th>模拟订单</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in aiStore.signals" :key="item.signal_id" @click="aiStore.selectSignal(item)">
                <td>{{ item.created_at }}</td>
                <td>{{ item.symbol }}</td>
                <td>{{ item.action }}</td>
                <td>{{ Number(item.confidence || 0).toFixed(2) }}</td>
                <td><span class="status-chip" :class="badgeClass(item.approval_status)">{{ item.approval_status }}</span></td>
                <td>{{ item.linked_order_id || "-" }}</td>
              </tr>
              <tr v-if="!aiStore.signals.length">
                <td colspan="6">暂无历史建议。</td>
              </tr>
            </tbody>
          </table>
        </article>
      </main>

      <aside class="cq-copilot-panel">
        <header class="cq-copilot-panel__head">
          <div class="cq-copilot-avatar">
            <img src="/assets/huuquant-bot.png" alt="" />
          </div>
          <div>
            <span>AI 对话助手</span>
            <strong>量化副驾驶</strong>
            <p>AI 只能建议，不能直接下单。</p>
          </div>
        </header>

        <div ref="messageList" class="cq-copilot-messages">
          <div v-if="!aiChat.hasMessages" class="cq-copilot-welcome">
            <strong>可以问我什么？</strong>
            <p>结合当前 {{ form.symbol }} {{ form.period }} K 线，询问账户、持仓、风控、策略复盘或模拟交易风险。</p>
          </div>
          <article
            v-for="message in aiChat.messages"
            :key="message.message_id"
            class="cq-copilot-message"
            :class="`cq-copilot-message--${message.role}`"
          >
            <span>{{ message.role === "user" ? "你" : "AI" }}</span>
            <p>{{ message.content }}</p>
          </article>
          <article v-if="aiChat.loading" class="cq-copilot-message cq-copilot-message--assistant">
            <span>AI</span>
            <p>正在结合行情、K 线、账户和风控状态分析...</p>
          </article>
        </div>

        <p v-if="aiChat.errorMessage" class="ai-chat-error">{{ aiChat.errorMessage }}</p>

        <footer class="cq-copilot-composer">
          <textarea
            v-model="draft"
            rows="4"
            placeholder="询问 K 线、账户、持仓、风控、回测等问题..."
            @keydown="handleChatKeydown"
          ></textarea>
          <div class="cq-copilot-actions">
            <div class="ai-chat-model-switch" aria-label="模型选择">
              <button
                v-for="option in modelOptions"
                :key="option.value"
                type="button"
                :class="{ active: selectedModel === option.value }"
                @click="selectedModel = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <button class="cq-primary-button" :disabled="!canSend" @click="sendChat">
              {{ aiChat.loading ? "分析中" : "发送" }}
            </button>
          </div>
          <button class="cq-muted-button" :disabled="!canCreatePaperOrder" @click="createPaperOrder">
            手动确认生成模拟订单
          </button>
        </footer>
      </aside>
    </div>
  </section>
</template>
