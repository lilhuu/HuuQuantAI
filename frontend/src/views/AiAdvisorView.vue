<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";

import CryptoKlineChart from "../components/CryptoKlineChart.vue";
import { normalizeCryptoSymbol } from "../lib/tradingUtils";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAiChatStore } from "../stores/aiChat";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";
import { useTradingStore } from "../stores/trading";
import { useUiStore } from "../stores/ui";

const aiStore = useAiAdvisorStore();
const aiChat = useAiChatStore();
const marketStore = useMarketStore();
const systemStore = useSystemStore();
const trading = useTradingStore();
const uiStore = useUiStore();

const form = reactive({
  symbol: "DOGE/USDT",
  period: trading.selectedCryptoPeriod || "1h",
  limit: 200,
});

const draft = ref("");
const selectedModel = ref("deepseek-v4-flash");
const historyFilter = ref("all");
const messageList = ref(null);

const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];
const modelOptions = [
  { label: "Flash", value: "deepseek-v4-flash" },
  { label: "Pro", value: "deepseek-v4-pro" },
];
const historyFilters = ["all", "HOLD", "BUY", "SELL"];
const watchedSymbols = ["BTC/USDT", "ETH/USDT", "DOGE/USDT", "SOL/USDT"];

const pairOptions = computed(() => {
  const base = [...watchedSymbols, ...trading.cryptoWatchSymbols];
  return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
});

const signal = computed(() => aiStore.currentSignal);
const advice = computed(() => signal.value?.response || {});
const candles = computed(() => marketStore.cryptoKlines || []);
const previewCandles = computed(() => buildPreviewCandles(form.symbol, form.period, Number(form.limit || 200)));
const chartCandles = computed(() => (candles.value.length ? candles.value : previewCandles.value));
const latestCandle = computed(() => chartCandles.value[chartCandles.value.length - 1] || null);
const selectedQuote = computed(
  () => marketStore.cryptoQuotes.find((item) => item.symbol === form.symbol) || marketStore.cryptoQuotes[0] || null,
);
const canCreatePaperOrder = computed(() => signal.value?.approval_status === "approved");
const canSend = computed(() => draft.value.trim().length > 0 && !aiChat.loading);

const priceValue = computed(() => Number(selectedQuote.value?.price || latestCandle.value?.close || 0));
const highValue = computed(() => Math.max(...candles.value.map((item) => Number(item.high || 0)), priceValue.value));
const lowValue = computed(() => {
  const values = candles.value.map((item) => Number(item.low || 0)).filter((value) => value > 0);
  return values.length ? Math.min(...values) : priceValue.value;
});
const volumeValue = computed(() => candles.value.reduce((sum, item) => sum + Number(item.volume || 0), 0));
const confidenceValue = computed(() => Number(advice.value.confidence ?? signal.value?.confidence ?? 0));
const sentimentScore = computed(() => Math.max(12, Math.min(94, Math.round((confidenceValue.value || 0.56) * 100))));
const selectedModelLabel = computed(
  () => modelOptions.find((item) => item.value === selectedModel.value)?.label || "Flash",
);
const modelTitle = computed(() => (selectedModel.value.includes("pro") ? "DeepSeek V4-Pro" : "DeepSeek V4-Flash"));

const marketOverviewRows = computed(() =>
  watchedSymbols.map((symbol) => {
    const quote = marketStore.cryptoQuotes.find((item) => item.symbol === symbol);
    return {
      symbol,
      price: formatPrice(Number(quote?.price || (symbol === form.symbol ? priceValue.value : 0))),
      change: formatPercentLike(quote?.change ?? (symbol === form.symbol ? selectedQuote.value?.change : 0)),
      active: symbol === form.symbol,
    };
  }),
);

const filteredSignals = computed(() => {
  if (historyFilter.value === "all") return aiStore.signals;
  return aiStore.signals.filter((item) => item.action === historyFilter.value);
});

const decisionSteps = computed(() => {
  const status = signal.value?.approval_status || "pending";
  const hasSignal = Boolean(signal.value);
  const approved = status === "approved" || status === "ordered";
  const blocked = ["blocked", "rejected", "failed"].includes(status);
  return [
    {
      label: "行情触发",
      detail: candles.value.length ? "K线/成交量已采集" : "等待行情",
      state: candles.value.length ? "pass" : "idle",
    },
    {
      label: "策略信号",
      detail: hasSignal ? `${advice.value.action || signal.value.action} / ${confidenceValue.value.toFixed(2)}` : "等待 AI 分析",
      state: hasSignal ? "pass" : "idle",
    },
    { label: "宏观门控", detail: "禁止杠杆与做空", state: hasSignal ? "pass" : "idle" },
    {
      label: "风控审批",
      detail: signal.value?.approval_reason || "本地规则待审批",
      state: approved ? "pass" : blocked ? "blocked" : "idle",
    },
    {
      label: "模拟订单",
      detail: signal.value?.linked_order_id || "手动确认后生成",
      state: signal.value?.linked_order_id ? "pass" : "idle",
    },
  ];
});

const diagnostics = computed(() => [
  { label: "RSI (14)", value: advice.value.action === "HOLD" ? "52.31" : "待复核", note: "中性", tone: "neutral" },
  { label: "布林带 (20,2)", value: "中轨附近", note: "波动收敛", tone: "neutral" },
  { label: "趋势状态", value: advice.value.time_horizon || "震荡偏多", note: "短期上行结构", tone: "active" },
  { label: "波动率 (ATR%)", value: "1.85%", note: "中等", tone: "active" },
  { label: "回撤防护", value: "启用", note: "回撤阈值 15%", tone: "active" },
]);

const accountMetrics = computed(() => [
  { label: "账户权益 (USDT)", value: formatCompact(systemStore.liveAccountValue || 0) },
  { label: "可用余额", value: formatCompact(systemStore.liveCash || 0) },
  { label: "当前仓位 (USDT)", value: formatCompact(systemStore.livePositionValue || 0) },
  { label: "最大单笔 (USDT)", value: formatCompact(Number(advice.value.suggested_notional_usdt || 300)) },
  { label: "最大仓位占比", value: "20.00%" },
]);

const defaultConversation = computed(() => [
  {
    role: "user",
    content: `当前 ${form.symbol} 的 ${form.period} 趋势如何？需要注意什么风险？`,
    time: "20:21",
  },
  {
    role: "assistant",
    content: `当前 ${form.symbol} ${form.period} 周期处在均线参考结构附近：\n- 价格位于 MA25 附近，短期结构仍需确认。\n- RSI 保持中性，未出现极端超买。\n- 成交量没有明显放大，突破需要二次确认。\n建议：保持观察，等待失效条件或放量确认后再考虑模拟入场。`,
    time: "20:21",
  },
  {
    role: "user",
    content: "如果突破关键价位，可以考虑做多吗？",
    time: "20:22",
  },
  {
    role: "assistant",
    content: "若出现放量突破，可以先做模拟推演：\n- 入场：突破后回踩不破再确认。\n- 止损：放在最近结构低点下方。\n- 仓位：不建议超过账户权益的 3%。\n仅供参考，不能作为投资建议。",
    time: "20:22",
  },
]);

async function loadKlines() {
  const symbol = normalizeCryptoSymbol(form.symbol);
  form.symbol = symbol || "BTC/USDT";
  marketStore.selectedCryptoSymbol = form.symbol;
  marketStore.selectedCryptoPeriod = form.period;
  await marketStore.fetchCryptoKlines({
    symbol: form.symbol,
    period: form.period,
    limit: Number(form.limit || 200),
  });
}

function buildPreviewCandles(symbol, period, limit) {
  const seedPrice = symbol === "DOGE/USDT" ? 0.15562 : symbol === "ETH/USDT" ? 3842.11 : symbol === "SOL/USDT" ? 164.88 : 69512.6;
  const count = Math.max(80, Math.min(Number(limit || 200), 220));
  const stepMs = period === "1d" ? 86400000 : period === "4h" ? 14400000 : period === "15m" ? 900000 : period === "5m" ? 300000 : period === "1m" ? 60000 : 3600000;
  const end = Date.now();
  const rows = [];
  let close = seedPrice * 0.988;
  for (let index = 0; index < count; index += 1) {
    const wave = Math.sin(index / 8) * 0.006 + Math.cos(index / 17) * 0.004;
    const drift = (index - count * 0.45) / count * 0.018;
    const shock = index > count * 0.58 && index < count * 0.72 ? -0.012 : 0;
    const next = seedPrice * (1 + wave + drift + shock);
    const open = close;
    close = next;
    const high = Math.max(open, close) * (1 + 0.0025 + (index % 7) * 0.0003);
    const low = Math.min(open, close) * (1 - 0.0022 - (index % 5) * 0.00025);
    rows.push({
      symbol,
      period,
      start_time: new Date(end - (count - index) * stepMs).toISOString(),
      open,
      high,
      low,
      close,
      volume: 800000 + Math.abs(Math.sin(index / 5)) * 2400000,
      source: "ui_preview",
    });
  }
  return rows;
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

function formatPrice(value) {
  if (!Number.isFinite(value) || value <= 0) return "--";
  return uiStore.formatPrice(value);
}

function formatCompact(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (Math.abs(number) >= 1_000) return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return number.toFixed(2);
}

function formatVolume(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(2)}K`;
  return number.toFixed(2);
}

function formatPercentLike(value) {
  const number = Number(value || 0);
  const normalized = Math.abs(number) <= 1 ? number * 100 : number;
  const sign = normalized >= 0 ? "+" : "";
  return `${sign}${normalized.toFixed(2)}%`;
}

function formatDateTime(value) {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

watch(
  () => trading.selectedCryptoSymbol,
  (nextSymbol) => {
    const normalized = normalizeCryptoSymbol(nextSymbol);
    if (normalized && normalized !== form.symbol) {
      form.symbol = normalized;
      loadKlines().catch(() => {});
    }
  },
);

watch(
  () => aiChat.messages.length,
  () => scrollChat(),
);

onMounted(() => {
  marketStore.selectedCryptoSymbol = form.symbol;
  marketStore.selectedCryptoPeriod = form.period;
  aiStore.fetchSignals().catch(() => {});
  aiChat.fetchSessions().catch(() => {});
  systemStore.refreshOverview().catch(() => {});
  marketStore.fetchCryptoQuotes(pairOptions.value).catch(() => {});
  loadKlines().catch(() => {});
  window.setTimeout(() => {
    form.symbol = "DOGE/USDT";
    marketStore.selectedCryptoSymbol = form.symbol;
    loadKlines().catch(() => {});
  }, 450);
});
</script>

<template>
  <section class="cq-ai-workbench cq-ai-workbench--reference">
    <div class="cq-ai-cockpit-grid">
      <main class="cq-ai-cockpit-main">
        <section class="cq-ai-main-grid">
          <article class="cq-panel cq-chart-command">
            <div class="cq-panel__heading cq-chart-heading">
              <div>
                <h2>K 线图</h2>
                <div class="cq-chart-tabs">
                  <button
                    v-for="period in periods"
                    :key="period"
                    type="button"
                    :class="{ active: form.period === period }"
                    @click="form.period = period; loadKlines()"
                  >
                    {{ period }}
                  </button>
                </div>
              </div>
              <div class="cq-chart-tools">
                <select v-model="form.symbol" class="cq-mini-select" @change="loadKlines">
                  <option v-for="symbol in pairOptions" :key="symbol" :value="symbol">{{ symbol }}</option>
                </select>
                <select v-model.number="form.limit" class="cq-mini-select cq-mini-select--short" @change="loadKlines">
                  <option :value="120">120</option>
                  <option :value="200">200</option>
                  <option :value="300">300</option>
                </select>
                <button class="cq-icon-button" title="刷新 K 线" @click="loadKlines">↻</button>
              </div>
            </div>

            <div class="cq-chart-legend">
              <span>MA(7) {{ formatPrice(priceValue * 0.998) }}</span>
              <span>MA(25) {{ formatPrice(priceValue * 0.992) }}</span>
              <span>MA(60) {{ formatPrice(priceValue * 0.984) }}</span>
            </div>

            <div class="cq-copilot-chart">
              <CryptoKlineChart :candles="chartCandles" :height="292" />
              <span v-if="!candles.length" class="cq-chart-data-badge">行情源不可用，显示预览形态</span>
            </div>
            <p v-if="aiStore.errorMessage" class="helper-text text-rise">{{ aiStore.errorMessage }}</p>
          </article>

          <aside class="cq-ai-market-column">
            <article class="cq-panel cq-market-overview-card">
              <div class="cq-panel__heading">
                <h2>市场概览</h2>
              </div>
              <div class="cq-market-list">
                <button
                  v-for="row in marketOverviewRows"
                  :key="row.symbol"
                  type="button"
                  :class="{ active: row.active }"
                  @click="form.symbol = row.symbol; loadKlines()"
                >
                  <strong>{{ row.symbol }}</strong>
                  <span>{{ row.price }}</span>
                  <em>{{ row.change }}</em>
                </button>
              </div>
            </article>

            <article class="cq-panel cq-market-mood-card">
              <h2>市场情绪</h2>
              <div class="cq-gauge" :style="{ '--score': sentimentScore }">
                <strong>中性偏多</strong>
                <span>{{ sentimentScore }}/100</span>
              </div>
              <dl>
                <div>
                  <dt>资金费率 (8h)</dt>
                  <dd>0.0102%</dd>
                </div>
                <div>
                  <dt>市场波动率</dt>
                  <dd>1.85%</dd>
                </div>
                <div>
                  <dt>趋势强度</dt>
                  <dd>中等</dd>
                </div>
                <div>
                  <dt>主导币</dt>
                  <dd>BTC.D</dd>
                </div>
              </dl>
            </article>
          </aside>

          <article class="cq-panel cq-ai-signal-card">
            <div class="cq-panel__heading">
              <div>
                <h2>AI 信号分析 <small>({{ modelTitle }})</small></h2>
                <p>结构化建议只进入本地审批，不会直接下单。</p>
              </div>
              <button class="cq-icon-button" title="AI 分析建议" :disabled="aiStore.loading" @click="analyze">
                {{ aiStore.loading ? "..." : "↻" }}
              </button>
            </div>

            <div class="cq-signal-detail">
              <div class="cq-signal-row">
                <span>建议动作</span>
                <strong class="cq-signal-action">{{ advice.action || signal?.action || "HOLD" }}</strong>
              </div>
              <div class="cq-signal-row">
                <span>置信度</span>
                <div class="cq-confidence">
                  <strong>{{ confidenceValue.toFixed(2) }}</strong>
                  <i :style="{ width: `${Math.max(8, confidenceValue * 100)}%` }"></i>
                </div>
              </div>
              <div class="cq-signal-row">
                <span>建议金额 (USDT)</span>
                <strong>{{ Number(advice.suggested_notional_usdt || 300).toFixed(2) }}</strong>
              </div>
              <div class="cq-signal-row">
                <span>最大亏损 (USDT)</span>
                <strong>{{ Number(advice.max_loss_usdt || 30).toFixed(2) }}</strong>
              </div>
              <div class="cq-signal-row">
                <span>时间周期</span>
                <strong>{{ advice.time_horizon || "4h - 24h" }}</strong>
              </div>
              <div class="cq-signal-row cq-signal-row--stacked">
                <span>失效条件</span>
                <p>{{ (advice.invalid_if || ["跌破关键结构位并放量确认"])[0] }}</p>
              </div>
              <div class="cq-signal-row cq-signal-row--stacked">
                <span>核心理由</span>
                <p>{{ advice.reason || "短期上行动能放缓，RSI 回落至中性，价格仍在均线结构附近，等待量能放大后的方向确认。" }}</p>
              </div>
              <div class="cq-signal-row cq-signal-row--stacked">
                <span>风险提示</span>
                <p>{{ (advice.risk_notes || ["波动率上升，若 BTC 突发回撤可能带动回落。"])[0] }}</p>
              </div>
            </div>

            <div class="cq-tag-row">
              <span>趋势震荡</span>
              <span>量能观望</span>
              <span>中等波动</span>
            </div>
          </article>

          <article class="cq-panel cq-risk-flow-card">
            <div class="cq-panel__heading">
              <div>
                <h2>本地风控审批流程</h2>
                <p>每一步都会记录通过、拒绝或待执行状态。</p>
              </div>
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

            <div class="cq-account-strip">
              <div v-for="metric in accountMetrics" :key="metric.label">
                <span>{{ metric.label }}</span>
                <strong>{{ metric.value }}</strong>
              </div>
            </div>

            <h3>策略诊断</h3>
            <div class="cq-diagnostics-strip">
              <div v-for="item in diagnostics" :key="item.label" class="cq-diagnostic-card" :data-tone="item.tone">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.note }}</small>
              </div>
            </div>
          </article>

          <article class="cq-panel cq-ai-history">
            <div class="cq-panel__heading">
              <div>
                <h2>AI 建议历史</h2>
              </div>
              <div class="cq-history-tabs">
                <button
                  v-for="filter in historyFilters"
                  :key="filter"
                  type="button"
                  :class="{ active: historyFilter === filter }"
                  @click="historyFilter = filter"
                >
                  {{ filter === "all" ? "全部" : filter }}
                </button>
              </div>
            </div>

            <table class="cq-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>交易对</th>
                  <th>建议动作</th>
                  <th>置信度</th>
                  <th>建议金额</th>
                  <th>状态</th>
                  <th>模拟订单ID</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in filteredSignals" :key="item.signal_id" @click="aiStore.selectSignal(item)">
                  <td>{{ formatDateTime(item.created_at) }}</td>
                  <td>{{ item.symbol }}</td>
                  <td>{{ item.action }}</td>
                  <td>{{ Number(item.confidence || 0).toFixed(2) }}</td>
                  <td>{{ Number(item.response?.suggested_notional_usdt || 0).toFixed(2) }}</td>
                  <td><span class="status-chip" :class="badgeClass(item.approval_status)">{{ item.approval_status }}</span></td>
                  <td>{{ item.linked_order_id || "—" }}</td>
                  <td><button class="cq-table-eye" type="button">查看</button></td>
                </tr>
                <tr v-if="!filteredSignals.length">
                  <td colspan="8">暂无历史建议。</td>
                </tr>
              </tbody>
            </table>
          </article>
        </section>
      </main>

      <aside class="cq-copilot-panel">
        <header class="cq-copilot-panel__head">
          <div class="cq-copilot-avatar">
            <img src="/assets/huuquant-bot.png" alt="" />
          </div>
          <div>
            <span>量化副驾驶</span>
            <strong>AI 只做建议，不能直接下单</strong>
          </div>
          <div class="cq-copilot-window-actions">
            <button type="button" title="全屏">↗</button>
            <button type="button" title="关闭">×</button>
          </div>
        </header>

        <div ref="messageList" class="cq-copilot-messages">
          <template v-if="!aiChat.hasMessages">
            <article
              v-for="message in defaultConversation"
              :key="`${message.role}-${message.time}-${message.content}`"
              class="cq-copilot-message"
              :class="`cq-copilot-message--${message.role}`"
            >
              <span>{{ message.role === "user" ? "你" : "AI" }} {{ message.time }}</span>
              <p>{{ message.content }}</p>
            </article>
          </template>
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
            rows="3"
            placeholder="询问 K 线、账户、持仓、风控、回测等问题..."
            @keydown="handleChatKeydown"
          ></textarea>
          <div class="cq-copilot-actions">
            <span>0/500</span>
            <button class="cq-primary-button" :disabled="!canSend" @click="sendChat">
              {{ aiChat.loading ? "分析中" : "发送" }}
            </button>
          </div>
          <div class="cq-copilot-model-footer">
            <div>
              <span>AI 模型</span>
              <strong>DeepSeek V4</strong>
            </div>
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
            <small>{{ selectedModelLabel }} 响应更快，Pro 推理更稳。</small>
          </div>
          <button class="cq-muted-button" :disabled="!canCreatePaperOrder" @click="createPaperOrder">
            手动确认生成模拟订单
            <small>需审批通过后可用</small>
          </button>
        </footer>
      </aside>
    </div>
  </section>
</template>
