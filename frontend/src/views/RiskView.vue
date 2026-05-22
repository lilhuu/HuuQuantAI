<script setup>
import { computed, onMounted } from "vue";

import { useAutoTradingStore } from "../stores/autoTrading";
import { useTradingStore } from "../stores/trading";

const store = useTradingStore();
const autoStore = useAutoTradingStore();

const riskItems = computed(() => [
  { label: "真实交易", value: autoStore.configDraft.real_trading_enabled ? "⚠ 已开启" : "永久关闭", tone: "status-chip--idle" },
  { label: "做空", value: "禁止", tone: "status-chip--idle" },
  { label: "杠杆", value: "禁止", tone: "status-chip--idle" },
  {
    label: "单笔上限",
    value: `${autoStore.configDraft.max_order_notional || "-"} USDT`,
    tone: "status-chip--connected",
  },
  {
    label: "单币仓位占比",
    value: `${((autoStore.configDraft.per_trade_position_ratio || 0) * 100).toFixed(0)}%`,
    tone: "status-chip--connected",
  },
  {
    label: "最大持仓数",
    value: String(autoStore.configDraft.max_positions || "-"),
    tone: "status-chip--connected",
  },
]);

const rejectedLogs = computed(() =>
  store.cryptoLogs.filter((log) =>
    String(log.event || log.message || "").toLowerCase().includes("reject"),
  ),
);

const blockedDecisions = computed(() =>
  (autoStore.decisions || []).filter(
    (item) => String(item.status || "").toLowerCase() === "blocked",
  ),
);

const failedDecisions = computed(() =>
  (autoStore.decisions || []).filter(
    (item) => String(item.status || "").toLowerCase() === "failed",
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
          <span class="eyebrow">Risk Guard</span>
          <h3>风控参数</h3>
        </div>
        <span class="status-chip status-chip--idle">Live Trading Off</span>
      </div>

      <div class="metric-grid">
        <div v-for="item in riskItems" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <div class="metric-grid">
        <div>
          <span>扫描间隔</span>
          <strong>{{ autoStore.configDraft.scan_interval_seconds || 30 }}s</strong>
        </div>
        <div>
          <span>置信度阈值</span>
          <strong>{{ Number(autoStore.configDraft.confidence_threshold || 0).toFixed(2) }}</strong>
        </div>
        <div>
          <span>自动交易</span>
          <strong>{{ autoStore.stateLabel }}</strong>
        </div>
        <div>
          <span>策略数</span>
          <strong>{{ (autoStore.configDraft.strategies || []).length }}</strong>
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
        <div>
          <span>可用现金</span>
          <strong>{{ store.formatCurrency(store.liveCash) }}</strong>
        </div>
      </div>
    </article>

    <article class="panel-card" v-if="autoStore.decisions.length">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Decision Audit</span>
          <h3>决策审计</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ autoStore.decisions.length }} 条</span>
      </div>

      <div class="table-wrap">
        <table>
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
            <tr v-for="(item, idx) in autoStore.decisions.slice(-30)" :key="idx">
              <td>{{ item.timestamp || "-" }}</td>
              <td>{{ item.symbol || "-" }}</td>
              <td>{{ item.strategy_id || "-" }}</td>
              <td>{{ item.signal || "-" }}</td>
              <td>{{ (Number(item.confidence || 0) * 100).toFixed(1) }}%</td>
              <td>
                <span
                  class="status-chip"
                  :class="{
                    'status-chip--connected': item.status === 'executed',
                    'status-chip--error': item.status === 'failed' || item.status === 'blocked',
                    'status-chip--idle': item.status !== 'executed' && item.status !== 'failed' && item.status !== 'blocked',
                  }"
                >{{ item.status || "-" }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card" v-if="blockedDecisions.length">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Blocked Signals</span>
          <h3>阻断信号</h3>
        </div>
      </div>
      <div class="timeline-list">
        <div v-for="(item, idx) in blockedDecisions" :key="idx" class="timeline-item">
          <strong>{{ item.symbol }} · {{ item.strategy_id || "—" }}</strong>
          <p>{{ item.reason || "风控阻断" }}</p>
          <small>{{ item.timestamp || "" }}</small>
        </div>
      </div>
    </article>

    <article class="panel-card" v-if="failedDecisions.length">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Failed Decisions</span>
          <h3>失败决策</h3>
        </div>
      </div>
      <div class="timeline-list">
        <div v-for="(item, idx) in failedDecisions" :key="idx" class="timeline-item">
          <strong>{{ item.symbol }} · {{ item.strategy_id || "—" }}</strong>
          <p>{{ item.reason || item.error || "执行失败" }}</p>
          <small>{{ item.timestamp || "" }}</small>
        </div>
      </div>
    </article>
  </section>

  <section class="panel-card" style="margin-top: 18px">
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
