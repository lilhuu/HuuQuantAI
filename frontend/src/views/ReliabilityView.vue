<script setup>
import { computed, onMounted } from "vue";

import { useTradingStore } from "../stores/trading";

const store = useTradingStore();

const rejectedLogs = computed(() => store.cryptoLogs.filter((log) => String(log.event || "").includes("rejected")));
const safetyItems = computed(() => [
  { label: "真实交易", value: "永久默认关闭", tone: "status-chip--idle" },
  { label: "做空", value: "禁止", tone: "status-chip--idle" },
  { label: "杠杆", value: "禁止", tone: "status-chip--idle" },
  { label: "最大单笔", value: "2,000 USDT", tone: "status-chip--connected" },
  { label: "连接状态", value: store.marketSocketState || "idle", tone: store.marketBannerTone },
]);

onMounted(() => {
  store.refreshOverview();
});
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Reliability</span>
          <h3>执行可靠性</h3>
        </div>
        <button class="ghost-button" @click="store.refreshOverview">刷新</button>
      </div>
      <div class="metric-grid">
        <div v-for="item in safetyItems" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Order Lifecycle</span>
          <h3>订单生命周期</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ store.cryptoOrders.length }} 条</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>标的</th>
              <th>方向</th>
              <th>数量</th>
              <th>状态</th>
              <th>来源</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in store.cryptoOrders" :key="order.order_id">
              <td>{{ order.created_time || "-" }}</td>
              <td>{{ order.symbol }}</td>
              <td>{{ order.action }}</td>
              <td>{{ order.quantity }}</td>
              <td><span class="status-chip status-chip--idle">{{ order.status }}</span></td>
              <td>{{ order.strategy || "manual" }}</td>
            </tr>
            <tr v-if="!store.cryptoOrders.length">
              <td colspan="6">暂无订单。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Safety Events</span>
          <h3>安全事件</h3>
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
            <strong>暂无拒单事件</strong>
            <p>超额、超仓或触发保护规则时会记录在这里。</p>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>
