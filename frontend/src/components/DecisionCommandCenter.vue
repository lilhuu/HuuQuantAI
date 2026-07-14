<script setup>
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import {
  PhArrowsClockwise,
  PhArrowRight,
  PhBrain,
  PhChartLineUp,
  PhCheckCircle,
  PhClock,
  PhInfo,
  PhPlay,
  PhRobot,
  PhShieldCheck,
  PhStrategy,
  PhWarning,
} from "@phosphor-icons/vue";

import CryptoKlineChart from "./CryptoKlineChart.vue";
import { formatCurrency, formatPrice } from "../lib/tradingUtils";
import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useAiChatStore } from "../stores/aiChat";
import { useAutoTradingStore } from "../stores/autoTrading";
import { useMarketStore } from "../stores/market";
import { useSystemStore } from "../stores/system";

const router = useRouter();
const aiAdvisor = useAiAdvisorStore();
const aiChat = useAiChatStore();
const autoTrading = useAutoTradingStore();
const market = useMarketStore();
const system = useSystemStore();

const selectedSymbol = computed(() => market.selectedCryptoSymbol || "BTC/USDT");
const selectedQuote = computed(
  () => market.cryptoQuotes.find((item) => item.symbol === selectedSymbol.value) || market.cryptoQuotes[0] || null,
);
const candles = computed(() => market.cryptoKlines || []);
const latestPrice = computed(() => Number(selectedQuote.value?.price || candles.value.at(-1)?.close || 0));
const priceChange = computed(() => Number(selectedQuote.value?.change || 0));
const latestSignal = computed(() => aiAdvisor.currentSignal || aiAdvisor.signals[0] || null);
const action = computed(() => String(latestSignal.value?.action || "HOLD").toUpperCase());
const confidence = computed(() => {
  const raw = Number(latestSignal.value?.confidence ?? 0.68);
  return Math.max(0, Math.min(raw > 1 ? raw / 100 : raw, 1));
});
const confidenceText = computed(() => `${Math.round(confidence.value * 100)}%`);
const signalReason = computed(
  () => latestSignal.value?.reason || "价格位于关键阻力区间下方，动能尚未确认，等待突破后重新评估。",
);
const autoDecisions = computed(() => autoTrading.decisions || []);
const latestDecision = computed(() => autoDecisions.value[0] || null);
const latestOrder = computed(() => system.cryptoOrders?.[0] || null);
const positions = computed(() => system.cryptoPositions || []);
const closeValues = computed(() => candles.value.map((item) => Number(item.close || 0)).filter((item) => item > 0));
const ma50 = computed(() => average(closeValues.value.slice(-50)));
const rsi = computed(() => calculateRsi(closeValues.value, 14));
const atrPercent = computed(() => calculateAtrPercent(candles.value.slice(-15)));
const volumeRatio = computed(() => {
  const values = candles.value.slice(-24).map((item) => Number(item.volume || 0)).filter((item) => item > 0);
  if (values.length < 2) return 1;
  const baseline = average(values.slice(0, -1));
  return baseline > 0 ? values.at(-1) / baseline : 1;
});
const resistance = computed(() => Math.max(0, ...candles.value.slice(-40).map((item) => Number(item.high || 0))));
const support = computed(() => {
  const values = candles.value.slice(-40).map((item) => Number(item.low || 0)).filter((item) => item > 0);
  return values.length ? Math.min(...values) : 0;
});
const riskApproved = computed(() => !autoTrading.configDraft.real_trading_enabled && autoTrading.state !== "blocked");
const modelLabel = computed(() => (aiChat.selectedModel === "deepseek-v4-pro" ? "DeepSeek V4 Pro" : "DeepSeek V4 Flash"));

const evidenceItems = computed(() => [
  {
    icon: PhChartLineUp,
    label: "趋势结构",
    value: latestPrice.value >= ma50.value ? "偏多" : "偏空",
    detail: ma50.value ? `价格 ${latestPrice.value >= ma50.value ? "高于" : "低于"} MA50` : "等待更多 K 线",
    score: latestPrice.value >= ma50.value ? 0.12 : -0.12,
  },
  {
    icon: PhStrategy,
    label: "动量 RSI (14)",
    value: rsi.value.toFixed(1),
    detail: rsi.value > 70 ? "偏热，追涨风险增加" : rsi.value < 30 ? "偏弱，等待企稳" : "中性区域",
    score: (rsi.value - 50) / 250,
  },
  {
    icon: PhWarning,
    label: "波动率 ATR",
    value: `${atrPercent.value.toFixed(2)}%`,
    detail: atrPercent.value > 3 ? "波动偏高" : "波动可控",
    score: atrPercent.value > 3 ? -0.08 : 0.05,
  },
  {
    icon: PhChartLineUp,
    label: "成交量",
    value: `${volumeRatio.value.toFixed(2)}x`,
    detail: volumeRatio.value > 1.2 ? "成交量放大" : "量能尚未放大",
    score: volumeRatio.value > 1.2 ? 0.09 : -0.04,
  },
  {
    icon: PhShieldCheck,
    label: "关键区间",
    value: resistance.value ? formatPrice(resistance.value) : "--",
    detail: support.value ? `支撑 ${formatPrice(support.value)}` : "等待区间确认",
    score: latestPrice.value && resistance.value ? (latestPrice.value < resistance.value ? -0.05 : 0.08) : 0,
  },
  {
    icon: PhRobot,
    label: "账户风险敞口",
    value: `${positions.value.length} 个持仓`,
    detail: `可用现金 ${formatCurrency(system.liveCash || 0)}`,
    score: positions.value.length < Number(autoTrading.configDraft.max_positions || 3) ? 0.08 : -0.12,
  },
]);

const pipeline = computed(() => [
  { icon: PhChartLineUp, title: "市场证据", value: `${candles.value.length} 根 K 线`, status: candles.value.length ? "已更新" : "等待数据", tone: candles.value.length ? "ready" : "idle" },
  { icon: PhStrategy, title: "策略候选", value: `${(autoTrading.configDraft.strategies || []).filter((item) => item.enabled).length} 个策略`, status: latestDecision.value?.strategy_id || "等待扫描", tone: latestDecision.value ? "ready" : "idle" },
  { icon: PhBrain, title: "AI 最终裁决", value: action.value, status: confidenceText.value, tone: "ai" },
  { icon: PhShieldCheck, title: "本地风险审批", value: riskApproved.value ? "通过" : "阻断", status: riskApproved.value ? "规则正常" : autoTrading.state, tone: riskApproved.value ? "approved" : "blocked" },
  { icon: PhRobot, title: "模拟订单", value: latestOrder.value?.status || "无操作", status: latestOrder.value?.order_id || "等待条件", tone: latestOrder.value ? "ready" : "idle" },
]);

const historyRows = computed(() => {
  const rows = autoDecisions.value.slice(0, 6).map((item) => ({
    time: compactTime(item.timestamp || item.created_at),
    symbol: item.symbol || selectedSymbol.value,
    action: String(item.action || item.signal || "HOLD").toUpperCase(),
    confidence: `${Math.round(Number(item.confidence || 0) * 100)}%`,
    result: item.status || "已完成",
    reason: item.reason || item.message || "等待更多证据",
  }));
  if (rows.length) return rows;
  return [
    { time: "--", symbol: selectedSymbol.value, action: action.value, confidence: confidenceText.value, result: "观察中", reason: signalReason.value },
  ];
});

function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length;
}

function calculateRsi(values, period) {
  if (values.length <= period) return 50;
  const changes = values.slice(-(period + 1)).slice(1).map((value, index) => value - values.slice(-(period + 1))[index]);
  const gains = changes.map((value) => Math.max(value, 0));
  const losses = changes.map((value) => Math.max(-value, 0));
  const averageLoss = average(losses);
  if (averageLoss === 0) return 100;
  return 100 - 100 / (1 + average(gains) / averageLoss);
}

function calculateAtrPercent(items) {
  if (items.length < 2) return 0;
  const ranges = items.slice(1).map((item, index) => {
    const previousClose = Number(items[index].close || 0);
    const high = Number(item.high || 0);
    const low = Number(item.low || 0);
    return Math.max(high - low, Math.abs(high - previousClose), Math.abs(low - previousClose));
  });
  const close = Number(items.at(-1)?.close || 0);
  return close > 0 ? (average(ranges) / close) * 100 : 0;
}

function compactTime(value) {
  if (!value) return "--";
  return String(value).replace("T", " ").slice(5, 16);
}

async function runScan() {
  await autoTrading.scan();
}

onMounted(() => {
  Promise.allSettled([
    market.fetchCryptoQuotes(market.cryptoWatchSymbols?.length ? market.cryptoWatchSymbols : ["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
    market.fetchCryptoKlines({ symbol: selectedSymbol.value, period: market.selectedCryptoPeriod || "1h", limit: 200 }),
    system.refreshOverview(),
    autoTrading.fetchStatus(),
    aiAdvisor.fetchSignals(),
  ]);
});
</script>

<template>
  <section class="decision-canvas" data-feature-role="ai-decision-canvas">
    <div class="decision-canvas__primary">
      <section class="decision-market" aria-label="当前市场与 AI 裁决">
        <div class="decision-chart">
          <header class="decision-section-head">
            <div>
              <span>{{ selectedSymbol }} · {{ market.selectedCryptoPeriod || "1h" }} · Binance 模拟</span>
              <strong>{{ latestPrice ? formatPrice(latestPrice) : "--" }}</strong>
              <em :class="priceChange >= 0 ? 'number-up' : 'number-down'">
                {{ priceChange >= 0 ? "+" : "" }}{{ (priceChange * 100).toFixed(2) }}%
              </em>
            </div>
            <button type="button" class="decision-text-button" @click="router.push('/market')">
              查看行情 <PhArrowRight :size="14" />
            </button>
          </header>
          <CryptoKlineChart :candles="candles" :height="365" />
        </div>

        <aside class="decision-verdict">
          <div class="decision-verdict__model"><PhBrain :size="18" />{{ modelLabel }}</div>
          <span>AI 最终裁决 <PhInfo :size="14" /></span>
          <div class="decision-verdict__action">
            <PhRobot :size="44" weight="duotone" />
            <div><strong>{{ action }}</strong><small>置信度 <b>{{ confidenceText }}</b></small></div>
          </div>
          <div class="decision-verdict__reason">
            <strong>{{ action === "HOLD" ? "未满足入场条件" : "当前建议" }}</strong>
            <p>{{ signalReason }}</p>
          </div>
          <div class="decision-verdict__condition">
            <span>失效条件（触发后重新评估）</span>
            <strong>{{ support ? `跌破 ${formatPrice(support)}` : "等待关键价位确认" }}</strong>
          </div>
          <div class="decision-verdict__countdown"><PhClock :size="15" /> 下一次评估 <strong>新 K 线收盘后</strong></div>
        </aside>
      </section>

      <section class="decision-pipeline" aria-label="模拟交易决策流水">
        <article v-for="(step, index) in pipeline" :key="step.title" :class="`decision-step decision-step--${step.tone}`">
          <div class="decision-step__index"><component :is="step.icon" :size="16" />{{ index + 1 }}</div>
          <span>{{ step.title }}</span>
          <strong>{{ step.value }}</strong>
          <small>{{ step.status }}</small>
        </article>
      </section>

      <section class="decision-history">
        <div class="decision-history__command">
          <button type="button" class="decision-scan-button" @click="runScan"><PhPlay :size="18" weight="fill" />运行一次模拟扫描</button>
          <p><PhShieldCheck :size="18" />不会自动进行真实交易</p>
        </div>
        <div class="decision-history__table">
          <header><span>决策历史</span><button type="button" @click="router.push('/audit')">查看审计日志</button></header>
          <div class="decision-table-scroll">
            <table>
              <thead><tr><th>时间</th><th>交易对</th><th>AI 裁决</th><th>置信度</th><th>结果</th><th>主要原因</th></tr></thead>
              <tbody>
                <tr v-for="(row, index) in historyRows" :key="`${row.time}-${index}`">
                  <td>{{ row.time }}</td><td>{{ row.symbol }}</td><td :class="row.action === 'HOLD' ? 'decision-hold' : 'number-up'">{{ row.action }}</td>
                  <td>{{ row.confidence }}</td><td>{{ row.result }}</td><td>{{ row.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    <aside class="decision-evidence" aria-label="市场证据">
      <header><div><span>市场证据</span><small>实时上下文</small></div><PhArrowsClockwise :size="16" /></header>
      <div class="decision-evidence__list">
        <article v-for="item in evidenceItems" :key="item.label">
          <component :is="item.icon" :size="18" />
          <div><strong>{{ item.label }}</strong><small>{{ item.detail }}</small></div>
          <b>{{ item.value }}</b>
          <em :class="item.score >= 0 ? 'number-up' : 'number-down'">{{ item.score >= 0 ? "+" : "" }}{{ item.score.toFixed(2) }}</em>
        </article>
      </div>
      <footer>
        <span>综合置信度贡献</span>
        <strong>{{ confidenceText }}</strong>
        <div><i :style="{ width: confidenceText }"></i></div>
        <p><PhCheckCircle :size="16" />真实交易永久关闭，所有订单仅进入 PaperBroker。</p>
      </footer>
    </aside>
  </section>
</template>
