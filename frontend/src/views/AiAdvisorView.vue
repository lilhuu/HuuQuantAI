<script setup>
import { computed, onMounted, reactive } from "vue";

import { useAiAdvisorStore } from "../stores/aiAdvisor";
import { useTradingStore } from "../stores/trading";

const aiStore = useAiAdvisorStore();
const trading = useTradingStore();

const form = reactive({
  symbol: trading.selectedCryptoSymbol || "BTC/USDT",
  period: trading.selectedCryptoPeriod || "1h",
  limit: 120,
});

const periods = ["1m", "5m", "15m", "1h", "4h", "1d"];
const signal = computed(() => aiStore.currentSignal);
const advice = computed(() => signal.value?.response || {});
const canCreatePaperOrder = computed(() => signal.value?.approval_status === "approved");

async function analyze() {
  await aiStore.analyze(form);
}

async function createPaperOrder() {
  await aiStore.createPaperOrder();
}

function badgeClass(status) {
  if (status === "approved" || status === "ordered") return "status-chip--connected";
  if (status === "blocked" || status === "rejected" || status === "failed") return "status-chip--error";
  return "status-chip--idle";
}

onMounted(() => {
  aiStore.fetchSignals().catch(() => {});
});
</script>

<template>
  <section class="cq-page-head">
    <h1>AI 助手</h1>
    <p>OpenAI 只生成加密货币交易建议。真实交易关闭，必须手动确认后才可生成模拟订单。</p>
  </section>

  <section class="cq-dashboard-grid">
    <article class="cq-panel">
      <div class="cq-panel__heading">
        <div>
          <h2>AI 分析</h2>
          <p>选择交易对和周期，AI 会基于行情、K 线、账户、持仓和风控状态给出结构化建议。</p>
        </div>
        <span class="cq-pill">Advisory Only</span>
      </div>

      <div class="form-grid">
        <label>
          <span>交易对</span>
          <input v-model="form.symbol" placeholder="BTC/USDT" />
        </label>
        <label>
          <span>周期</span>
          <select v-model="form.period">
            <option v-for="period in periods" :key="period" :value="period">{{ period }}</option>
          </select>
        </label>
        <label>
          <span>K 线数量</span>
          <input v-model.number="form.limit" type="number" min="30" max="500" />
        </label>
      </div>

      <div class="button-row">
        <button class="primary-button" :disabled="aiStore.loading" @click="analyze">
          {{ aiStore.loading ? "分析中..." : "AI 分析建议" }}
        </button>
        <button class="ghost-button" :disabled="!canCreatePaperOrder || aiStore.ordering" @click="createPaperOrder">
          {{ aiStore.ordering ? "生成中..." : "手动确认生成模拟订单" }}
        </button>
      </div>

      <p v-if="aiStore.errorMessage" class="helper-text">{{ aiStore.errorMessage }}</p>
    </article>

    <article class="cq-panel">
      <div class="cq-panel__heading">
        <div>
          <h2>当前建议</h2>
          <p>模型输出必须通过本地审批，低置信度、HOLD、超仓和做空都会被拦截。</p>
        </div>
        <span v-if="signal" class="status-chip" :class="badgeClass(signal.approval_status)">
          {{ signal.approval_status }}
        </span>
      </div>

      <div v-if="signal" class="cq-ai-signal">
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
          <h3>理由</h3>
          <p>{{ advice.reason || signal.approval_reason }}</p>
          <h3>风险点</h3>
          <ul>
            <li v-for="item in advice.risk_notes || []" :key="item">{{ item }}</li>
          </ul>
          <h3>失效条件</h3>
          <ul>
            <li v-for="item in advice.invalid_if || []" :key="item">{{ item }}</li>
          </ul>
          <h3>本地审批</h3>
          <p>{{ signal.approval_reason }}</p>
          <p v-if="signal.linked_order_id">已生成模拟订单：{{ signal.linked_order_id }}</p>
        </div>
      </div>
      <p v-else>暂无 AI 建议。</p>
    </article>
  </section>

  <section class="cq-panel cq-ai-history">
    <div class="cq-panel__heading">
      <div>
        <h2>历史建议</h2>
        <p>所有 AI 建议都会保存，方便后续复盘模型效果。</p>
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
          <th>订单</th>
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
  </section>
</template>
