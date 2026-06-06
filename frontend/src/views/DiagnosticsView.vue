<script setup>
import { onMounted } from "vue";

import { useDiagnosticsData } from "../composables/useDiagnosticsData";

const diagnostics = useDiagnosticsData();

onMounted(() => {
  diagnostics.refreshDiagnostics();
});
</script>

<template>
  <section class="workspace-grid workspace-grid--stacked diagnostics-view">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Strategy Diagnostics</span>
          <h3>策略诊断</h3>
        </div>
        <button class="ghost-button" :disabled="diagnostics.loading.value" @click="diagnostics.refreshDiagnostics">
          {{ diagnostics.loading.value ? "刷新中" : "刷新诊断" }}
        </button>
      </div>

      <div class="metric-grid">
        <div>
          <span>启用策略</span>
          <strong>{{ diagnostics.enabledStrategies.value.length }}</strong>
        </div>
        <div>
          <span>最近决策</span>
          <strong>{{ diagnostics.recentDecisions.value.length }}</strong>
        </div>
        <div>
          <span>阻断信号</span>
          <strong>{{ diagnostics.signalStats.value.blocked }}</strong>
        </div>
        <div>
          <span>内置模板</span>
          <strong>{{ diagnostics.templates.value.length }}</strong>
        </div>
      </div>
      <p v-if="diagnostics.errorMessage.value" class="helper-text text-rise">{{ diagnostics.errorMessage.value }}</p>
    </article>

    <section class="workspace-grid">
      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Signal Mix</span>
            <h3>信号分布</h3>
          </div>
        </div>
        <div class="metric-grid metric-grid-compact">
          <div>
            <span>BUY</span>
            <strong class="number-up">{{ diagnostics.signalStats.value.BUY }}</strong>
          </div>
          <div>
            <span>SELL</span>
            <strong class="number-down">{{ diagnostics.signalStats.value.SELL }}</strong>
          </div>
          <div>
            <span>HOLD</span>
            <strong>{{ diagnostics.signalStats.value.HOLD }}</strong>
          </div>
          <div>
            <span>BLOCKED</span>
            <strong>{{ diagnostics.signalStats.value.blocked }}</strong>
          </div>
        </div>
      </article>

      <article class="panel-card">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Built-in Templates</span>
            <h3>内置策略模板</h3>
          </div>
        </div>
        <div class="strategy-list">
          <div v-for="item in diagnostics.templates.value" :key="item.type" class="strategy-card">
            <div>
              <strong>{{ item.name || item.type }}</strong>
              <p>{{ item.description || "内置策略模板" }}</p>
            </div>
            <span class="status-chip status-chip--idle">{{ item.type }}</span>
          </div>
          <div v-if="!diagnostics.templates.value.length" class="empty-state-card">
            <strong>模板未加载</strong>
            <p>点击刷新诊断后会从后端读取策略模板。</p>
          </div>
        </div>
      </article>
    </section>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Active Strategy Config</span>
          <h3>当前策略配置</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>策略 ID</th>
              <th>类型</th>
              <th>状态</th>
              <th>权重</th>
              <th>交易对</th>
              <th>参数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in diagnostics.strategies.value" :key="item.strategy_id">
              <td>{{ item.strategy_id }}</td>
              <td>{{ item.type }}</td>
              <td>
                <span class="status-chip" :class="item.enabled ? 'status-chip--connected' : 'status-chip--idle'">
                  {{ item.enabled ? "启用" : "停用" }}
                </span>
              </td>
              <td>{{ item.weight }}</td>
              <td>{{ (item.symbols || []).join(", ") }}</td>
              <td>{{ JSON.stringify(item.parameters || {}) }}</td>
            </tr>
            <tr v-if="!diagnostics.strategies.value.length">
              <td colspan="6" class="empty-cell">暂无策略配置。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Recent Decisions</span>
          <h3>最近决策流水</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>交易对</th>
              <th>策略</th>
              <th>信号</th>
              <th>置信度</th>
              <th>状态</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in diagnostics.recentDecisions.value" :key="`${item.symbol}-${index}`">
              <td>{{ item.timestamp || "-" }}</td>
              <td>{{ item.symbol || "-" }}</td>
              <td>{{ item.strategy_id || "-" }}</td>
              <td>{{ item.signal || item.action || "-" }}</td>
              <td>{{ (Number(item.confidence || 0) * 100).toFixed(1) }}%</td>
              <td>{{ item.status || "-" }}</td>
              <td>{{ item.reason || "-" }}</td>
            </tr>
            <tr v-if="!diagnostics.recentDecisions.value.length">
              <td colspan="7" class="empty-cell">暂无自动交易决策。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>
