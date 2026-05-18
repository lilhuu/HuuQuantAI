<script setup>
import { computed } from "vue";

import { useTradingStore } from "../stores/trading";

const store = useTradingStore();

const riskItems = computed(() => [
  { label: "真实交易", value: "永久默认关闭", tone: "status-chip--idle" },
  { label: "做空", value: "禁止", tone: "status-chip--idle" },
  { label: "杠杆", value: "禁止", tone: "status-chip--idle" },
  { label: "默认单笔上限", value: "2,000 USDT", tone: "status-chip--connected" },
  { label: "单币种仓位", value: "50%", tone: "status-chip--connected" },
  { label: "总仓位", value: "按模拟账户权益校验", tone: "status-chip--connected" },
]);

const rejectedLogs = computed(() => store.cryptoLogs.filter((log) => String(log.event || "").includes("rejected")));
</script>

<template>
  <section class="workspace-grid">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Risk Guard</span>
          <h3>加密货币风控</h3>
        </div>
        <span class="status-chip status-chip--idle">Live Trading Off</span>
      </div>

      <div class="metric-grid">
        <div v-for="item in riskItems" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Account Exposure</span>
          <h3>账户暴露</h3>
        </div>
        <button class="ghost-button" @click="store.refreshOverview">刷新</button>
      </div>
      <div class="metric-grid">
        <div>
          <span>总权益</span>
          <strong>{{ store.formatCurrency(store.liveAccountValue) }}</strong>
        </div>
        <div>
          <span>持仓市值</span>
          <strong>{{ store.formatCurrency(store.livePositionValue) }}</strong>
        </div>
        <div>
          <span>持仓占比</span>
          <strong>
            {{ store.liveAccountValue ? store.formatPercent((store.livePositionValue / store.liveAccountValue) * 100) : "0.00%" }}
          </strong>
        </div>
      </div>
    </article>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Rejected Orders</span>
        <h3>拒单日志</h3>
      </div>
    </div>
    <div class="timeline-list">
      <div v-for="item in rejectedLogs" :key="`${item.timestamp}-${item.message}`" class="timeline-item">
        <div>
          <strong>{{ item.event }}</strong>
          <p>{{ item.message }}</p>
        </div>
        <span class="timeline-item__side">{{ item.timestamp }}</span>
      </div>
      <div v-if="!rejectedLogs.length" class="timeline-item">
        <div>
          <strong>暂无拒单</strong>
          <p>超过现金、超过持仓或触发风控时会出现在这里。</p>
        </div>
      </div>
    </div>
  </section>
</template>
