<script setup>
import { computed, onMounted } from "vue";

import { useAutoTradingStore } from "../stores/autoTrading";
import { useTradingStore } from "../stores/trading";

const store = useTradingStore();
const autoStore = useAutoTradingStore();

const safetyItems = computed(() => [
  { label: "真实交易", value: "永久默认关闭", tone: "status-chip--idle" },
  { label: "做空", value: "禁止", tone: "status-chip--idle" },
  { label: "杠杆", value: "禁止", tone: "status-chip--idle" },
  {
    label: "自动交易",
    value: autoStore.enabled ? "运行中" : "未启动",
    tone: autoStore.enabled ? "status-chip--connected" : "status-chip--idle",
  },
  {
    label: "连接状态",
    value: store.marketSocketState === "connected" ? "已连接" : "未连接",
    tone: store.marketSocketState === "connected" ? "status-chip--connected" : "status-chip--idle",
  },
]);

const rejectedLogs = computed(() =>
  store.cryptoLogs.filter((log) =>
    String(log.event || log.message || "").toLowerCase().includes("reject"),
  ),
);

const recentOrderLifecycle = computed(() =>
  store.cryptoOrders.slice(0, 20).map((order) => ({
    timestamp: order.created_time || order.filled_time || "-",
    symbol: order.symbol,
    action: order.action,
    quantity: order.quantity,
    status: order.status,
    source: order.strategy || "manual",
  })),
);

const autoDecisionLogs = computed(() =>
  (autoStore.decisions || []).filter(
    (item) => String(item.status || "").toLowerCase() === "blocked",
  ),
);

onMounted(async () => {
  await Promise.allSettled([autoStore.fetchStatus(), store.refreshOverview()]);
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
        <button class="ghost-button" @click="autoStore.fetchStatus()">刷新状态</button>
      </div>

      <div class="metric-grid">
        <div v-for="item in safetyItems" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <div class="metric-grid">
        <div>
          <span>scan_interval</span>
          <strong>{{ autoStore.configDraft.scan_interval_seconds || 30 }}s</strong>
        </div>
        <div>
          <span>confidence_threshold</span>
          <strong>{{ Number(autoStore.configDraft.confidence_threshold || 0).toFixed(2) }}</strong>
        </div>
        <div>
          <span>max_positions</span>
          <strong>{{ autoStore.configDraft.max_positions || "-" }}</strong>
        </div>
        <div>
          <span>配置策略数</span>
          <strong>{{ (autoStore.configDraft.strategies || []).length }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Decision Pipeline</span>
          <h3>近期自动决策</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ autoStore.decisions.length }} 条</span>
      </div>

      <div class="table-wrap">
        <table v-if="autoStore.decisions.length">
          <thead>
            <tr>
              <th>时间</th>
              <th>标的</th>
              <th>策略</th>
              <th>信号</th>
              <th>置信度</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in autoStore.decisions.slice(-20)" :key="idx">
              <td>{{ item.timestamp || "-" }}</td>
              <td>{{ item.symbol || "-" }}</td>
              <td>{{ item.strategy_id || "-" }}</td>
              <td>{{ item.signal || "-" }}</td>
              <td>{{ (Number(item.confidence || 0) * 100).toFixed(1) }}%</td>
              <td>
                <span class="status-chip" :class="item.status === 'executed' ? 'status-chip--connected' : 'status-chip--idle'">{{ item.status || "-" }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!autoStore.decisions.length" class="helper-text">暂无决策记录。启动自动交易后，每个扫描周期会生成策略决策。</p>
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
        <table v-if="recentOrderLifecycle.length">
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
            <tr v-for="(row, idx) in recentOrderLifecycle" :key="idx">
              <td>{{ row.timestamp }}</td>
              <td>{{ row.symbol }}</td>
              <td>{{ row.action }}</td>
              <td>{{ row.quantity }}</td>
              <td>
                <span class="status-chip" :class="store.badgeClassForOrder(row.status)">{{ row.status }}</span>
              </td>
              <td>{{ row.source }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!recentOrderLifecycle.length" class="helper-text">暂无订单生命周期记录。</p>
    </article>

    <article class="panel-card" v-if="rejectedLogs.length">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Rejected Orders</span>
          <h3>拒单记录 (模拟账户)</h3>
        </div>
      </div>
      <div class="timeline-list">
        <div v-for="(item, idx) in rejectedLogs" :key="idx" class="timeline-item">
          <strong>{{ item.event }}</strong>
          <p>{{ item.message }}</p>
          <small>{{ item.timestamp }}</small>
        </div>
      </div>
    </article>

    <article class="panel-card" v-if="autoDecisionLogs.length">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Blocked Signals</span>
          <h3>阻断信号 (自动交易)</h3>
        </div>
      </div>
      <div class="timeline-list">
        <div v-for="(item, idx) in autoDecisionLogs" :key="idx" class="timeline-item">
          <strong>{{ item.symbol }} · {{ item.strategy_id || "—" }}</strong>
          <p>{{ item.reason || "风控阻断" }}</p>
          <small>{{ item.timestamp || "" }}</small>
        </div>
      </div>
    </article>
  </section>
</template>
