<script setup>
import { onMounted } from "vue";

import { useAuditData } from "../composables/useAuditData";

const audit = useAuditData();

onMounted(() => {
  audit.refreshAudit();
});
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked audit-view">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Audit Center</span>
          <h3>监控审计</h3>
        </div>
        <button class="ghost-button" @click="audit.refreshAudit">刷新审计</button>
      </div>

      <div class="metric-grid">
        <div v-for="item in audit.safetyItems.value" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>
            <span class="status-chip" :class="item.tone">{{ item.value }}</span>
          </strong>
        </div>
      </div>
    </article>

    <section class="workspace-grid">
      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Decision Blocks</span>
            <h3>阻断决策</h3>
          </div>
          <span class="status-chip status-chip--idle">{{ audit.blockedDecisions.value.length }} 条</span>
        </div>
        <div class="timeline-list">
          <div v-for="(item, index) in audit.blockedDecisions.value" :key="`${item.symbol}-${index}`" class="timeline-item">
            <div>
              <strong>{{ item.symbol || "-" }} · {{ item.strategy_id || "策略" }}</strong>
              <p>{{ item.reason || "风控或冲突处理阻断" }}</p>
              <small>{{ item.timestamp || "" }}</small>
            </div>
            <span class="status-chip status-chip--idle">{{ item.status || "blocked" }}</span>
          </div>
          <div v-if="!audit.blockedDecisions.value.length" class="empty-state-card">
            <strong>暂无阻断决策</strong>
            <p>自动交易扫描产生阻断信号后会显示在这里。</p>
          </div>
        </div>
      </article>

      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Rejected Orders</span>
            <h3>拒单记录</h3>
          </div>
          <span class="status-chip status-chip--idle">{{ audit.rejectedLogs.value.length }} 条</span>
        </div>
        <div class="timeline-list">
          <div v-for="item in audit.rejectedLogs.value" :key="item.id" class="timeline-item">
            <div>
              <strong>{{ item.event }}</strong>
              <p>{{ item.message }}</p>
              <small>{{ item.timestamp }}</small>
            </div>
            <span class="status-chip" :class="`status-chip--${item.tone}`">{{ item.tone }}</span>
          </div>
          <div v-if="!audit.rejectedLogs.value.length" class="empty-state-card">
            <strong>暂无拒单</strong>
            <p>模拟账户拒单、撤单或风控失败会被归档到日志。</p>
          </div>
        </div>
      </article>
    </section>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Order Lifecycle</span>
          <h3>订单生命周期</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ audit.orderLifecycle.value.length }} 条</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>交易对</th>
              <th>方向</th>
              <th>数量</th>
              <th>状态</th>
              <th>来源</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in audit.orderLifecycle.value" :key="order.id">
              <td>{{ order.timestamp }}</td>
              <td>{{ order.symbol }}</td>
              <td>{{ order.action }}</td>
              <td>{{ order.quantity }}</td>
              <td><span class="badge" :class="order.tone">{{ order.status }}</span></td>
              <td>{{ order.source }}</td>
            </tr>
            <tr v-if="!audit.orderLifecycle.value.length">
              <td colspan="6" class="empty-cell">暂无订单生命周期记录。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Paper Logs</span>
          <h3>模拟实盘日志</h3>
        </div>
        <span class="status-chip status-chip--idle">{{ audit.auditLogs.value.length }} 条</span>
      </div>
      <div class="event-timeline">
        <div
          v-for="item in audit.auditLogs.value"
          :key="item.id"
          class="event-timeline__item"
          :class="`event-timeline__item--${item.tone}`"
        >
          <span class="event-timeline__dot"></span>
          <div class="event-timeline__content">
            <div class="event-timeline__header">
              <strong>{{ item.event }}</strong>
              <small>{{ item.timestamp }}</small>
            </div>
            <p>{{ item.message }}</p>
          </div>
        </div>
        <div v-if="!audit.auditLogs.value.length" class="empty-state-card">
          <strong>暂无日志</strong>
          <p>提交模拟订单、撤单、撮合或自动交易扫描后会产生审计日志。</p>
        </div>
      </div>
    </article>
  </section>
</template>
