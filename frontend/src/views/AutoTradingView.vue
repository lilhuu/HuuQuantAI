<script setup>
import { computed, onMounted, ref } from "vue";

import { useAutoTradingStore } from "../stores/autoTrading";

const autoStore = useAutoTradingStore();
const symbolsInput = ref("BTC/USDT, ETH/USDT, SOL/USDT");

const decisions = computed(() => autoStore.decisions);
const logs = computed(() => autoStore.logs.slice().reverse());
const statusTone = computed(() => {
  if (autoStore.state === "running") return "status-chip--connected";
  if (autoStore.state === "blocked") return "status-chip--error";
  if (autoStore.state === "paused") return "status-chip--connecting";
  return "status-chip--idle";
});

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function syncSymbolsFromDraft() {
  symbolsInput.value = autoStore.symbolsText();
}

async function saveConfig() {
  autoStore.setSymbolsText(symbolsInput.value);
  await autoStore.saveConfig();
  syncSymbolsFromDraft();
}

async function startAutoTrading() {
  autoStore.setSymbolsText(symbolsInput.value);
  await autoStore.start();
  syncSymbolsFromDraft();
}

onMounted(async () => {
  await autoStore.fetchStatus();
  syncSymbolsFromDraft();
});
</script>

<template>
  <section class="cq-page-head">
    <h1>自动交易</h1>
    <p>基于策略信号按周期扫描，只向本地模拟盘提交订单。真实交易保持关闭。</p>
  </section>

  <section v-if="autoStore.errorInfo" class="cq-error">
    <div>
      <strong>{{ autoStore.errorInfo.title }}</strong>
      <p>{{ autoStore.errorInfo.message }}</p>
    </div>
    <button class="cq-outline-button" @click="autoStore.clearError()">知道了</button>
  </section>

  <section class="cq-card-grid cq-card-grid--four">
    <article class="cq-metric-card">
      <span>运行状态</span>
      <strong>{{ autoStore.stateLabel }}</strong>
    </article>
    <article class="cq-metric-card">
      <span>后台循环</span>
      <strong>{{ autoStore.loopRunning ? "运行中" : "未运行" }}</strong>
    </article>
    <article class="cq-metric-card">
      <span>下次扫描</span>
      <strong>{{ formatDateTime(autoStore.nextRunAt) }}</strong>
    </article>
    <article class="cq-metric-card">
      <span>最近错误</span>
      <strong>{{ autoStore.lastErrorType || "无" }}</strong>
    </article>
  </section>

  <section class="cq-card-grid cq-card-grid--four">
    <article class="cq-metric-card">
      <span>扫描次数</span>
      <strong>{{ autoStore.status?.cycle_count || 0 }}</strong>
    </article>
    <article class="cq-metric-card">
      <span>信号数量</span>
      <strong>{{ autoStore.status?.signal_count || 0 }}</strong>
    </article>
    <article class="cq-metric-card">
      <span>模拟订单</span>
      <strong>{{ autoStore.status?.order_count || 0 }}</strong>
    </article>
    <article class="cq-metric-card">
      <span>扫描间隔</span>
      <strong>{{ autoStore.configDraft.scan_interval_seconds || 30 }}s</strong>
    </article>
  </section>

  <section class="workspace-grid">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Paper Auto Trading</span>
          <h3>自动交易配置</h3>
        </div>
        <span class="status-chip" :class="statusTone">{{ autoStore.stateLabel }}</span>
      </div>

      <div class="form-grid">
        <label>
          <span>交易对</span>
          <input v-model="symbolsInput" placeholder="BTC/USDT, ETH/USDT, SOL/USDT" />
        </label>
        <label>
          <span>主周期</span>
          <select v-model="autoStore.configDraft.period">
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
        </label>
        <label>
          <span>扫描间隔（秒）</span>
          <input v-model.number="autoStore.configDraft.scan_interval_seconds" type="number" min="5" max="3600" step="5" />
        </label>
        <label>
          <span>最大持仓数</span>
          <input v-model.number="autoStore.configDraft.max_positions" type="number" min="1" max="20" />
        </label>
        <label>
          <span>单笔仓位比例</span>
          <input v-model.number="autoStore.configDraft.per_trade_position_ratio" type="number" min="0.001" max="1" step="0.01" />
        </label>
        <label>
          <span>单笔上限 USDT</span>
          <input v-model.number="autoStore.configDraft.max_order_notional" type="number" min="1" step="10" />
        </label>
        <label>
          <span>最小下单 USDT</span>
          <input v-model.number="autoStore.configDraft.min_order_notional" type="number" min="0" step="1" />
        </label>
        <label>
          <span>信心阈值</span>
          <input v-model.number="autoStore.configDraft.confidence_threshold" type="number" min="0" max="1" step="0.05" />
        </label>
      </div>

      <div class="button-row">
        <button class="ghost-button" :disabled="autoStore.loading" @click="saveConfig">保存配置</button>
        <button class="primary-button" :disabled="autoStore.loading" @click="startAutoTrading">启动自动交易</button>
        <button class="ghost-button" :disabled="autoStore.loading" @click="autoStore.pause()">暂停</button>
        <button class="ghost-button" :disabled="autoStore.loading" @click="autoStore.stop()">停止</button>
        <button class="cq-accent-button" :disabled="autoStore.loading" @click="autoStore.scan()">立即扫描</button>
      </div>

      <p class="helper-text">
        当前模式：{{ autoStore.configDraft.mode }}，真实交易：关闭。启动后只会向 CryptoPaperBroker 发送模拟订单。
      </p>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Strategies</span>
          <h3>内置策略组合</h3>
        </div>
      </div>

      <div class="strategy-list">
        <article v-for="strategy in autoStore.configDraft.strategies" :key="strategy.strategy_id" class="strategy-card">
          <div>
            <strong>{{ strategy.strategy_id }}</strong>
            <p>{{ strategy.type }} / weight {{ strategy.weight }}</p>
          </div>
          <span class="status-chip" :class="strategy.enabled ? 'status-chip--connected' : 'status-chip--idle'">
            {{ strategy.enabled ? "启用" : "停用" }}
          </span>
        </article>
      </div>
    </article>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Decision Log</span>
        <h3>最近自动决策</h3>
      </div>
      <button class="ghost-button" @click="autoStore.fetchStatus()">刷新</button>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>交易对</th>
            <th>方向</th>
            <th>策略</th>
            <th>价格</th>
            <th>数量</th>
            <th>金额</th>
            <th>状态</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="decision in decisions" :key="`${decision.timestamp}-${decision.symbol}-${decision.action}`">
            <td>{{ decision.timestamp }}</td>
            <td>{{ decision.symbol }}</td>
            <td>{{ decision.action }}</td>
            <td>{{ decision.strategy_id }}</td>
            <td>{{ Number(decision.price || 0).toFixed(4) }}</td>
            <td>{{ decision.quantity }}</td>
            <td>{{ Number(decision.notional || 0).toFixed(2) }}</td>
            <td><span class="status-chip">{{ decision.status }}</span></td>
            <td>{{ decision.message || decision.reason }}</td>
          </tr>
          <tr v-if="!decisions.length">
            <td colspan="9">暂无自动交易决策。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">Runtime</span>
        <h3>运行日志</h3>
      </div>
    </div>

    <div class="paper-log-list">
      <article v-for="log in logs" :key="`${log.timestamp}-${log.event}`">
        <strong>{{ log.event }}</strong>
        <span>{{ log.message }}</span>
        <small>{{ log.timestamp }}</small>
      </article>
      <p v-if="!logs.length" class="helper-text">暂无自动交易日志。</p>
    </div>
  </section>
</template>
