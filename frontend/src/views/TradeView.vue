<script setup>
import { computed, reactive, ref } from "vue";

import { useTradingStore } from "../stores/trading";
import { normalizeCryptoSymbol } from "../stores/tradingUtils";

const store = useTradingStore();
const formMessage = ref("");
const form = reactive({
  symbol: store.selectedCryptoSymbol || "BTC/USDT",
  action: "BUY",
  quantity: 0.001,
  price: 65000,
  strategy: "crypto_manual",
});

const selectedQuote = computed(() => {
  const symbol = normalizeCryptoSymbol(form.symbol);
  return store.cryptoQuotes.find((item) => item.symbol === symbol) || null;
});

function useQuotePrice() {
  if (selectedQuote.value?.price) {
    form.price = Number(selectedQuote.value.price);
  }
}

async function submitOrder() {
  formMessage.value = "";
  const symbol = normalizeCryptoSymbol(form.symbol);
  if (!symbol) {
    formMessage.value = "请输入交易对";
    return;
  }
  if (Number(form.quantity) <= 0 || Number(form.price) <= 0) {
    formMessage.value = "数量和价格必须大于 0";
    return;
  }

  try {
    const result = await store.placeCryptoPaperOrder({
      symbol,
      action: form.action,
      quantity: Number(form.quantity),
      price: Number(form.price),
      order_type: "LIMIT",
      strategy: form.strategy || "crypto_manual",
    });
    formMessage.value = result.message || "模拟订单已提交";
  } catch (error) {
    store.setError(error, "提交模拟订单失败");
  }
}
</script>

<template>
  <section class="workspace-grid">
    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">Crypto Paper Trading</span>
          <h3>模拟下单</h3>
        </div>
        <span class="status-chip status-chip--idle">真实交易关闭</span>
      </div>

      <div class="form-grid">
        <label>
          <span>交易对</span>
          <input v-model="form.symbol" placeholder="BTC/USDT" />
        </label>
        <label>
          <span>方向</span>
          <select v-model="form.action">
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>
        <label>
          <span>数量</span>
          <input v-model.number="form.quantity" type="number" min="0.00000001" step="0.000001" />
        </label>
        <label>
          <span>限价 USDT</span>
          <input v-model.number="form.price" type="number" min="0.00000001" step="0.01" />
        </label>
        <label>
          <span>策略标签</span>
          <input v-model="form.strategy" />
        </label>
      </div>

      <div class="button-row">
        <button class="ghost-button" @click="useQuotePrice">使用最新价</button>
        <button class="primary-button" :disabled="store.cryptoLoading" @click="submitOrder">
          {{ store.cryptoLoading ? "提交中" : "提交模拟订单" }}
        </button>
      </div>

      <p v-if="formMessage" class="helper-text">{{ formMessage }}</p>

      <div v-if="store.errorInfo" class="error-banner error-banner--business">
        <div>
          <strong>{{ store.errorInfo.title || '订单错误' }}</strong>
          <p>{{ store.errorInfo.message }}</p>
        </div>
        <button class="ghost-button" @click="store.clearError()">关闭</button>
      </div>
    </article>

    <article class="panel-card">
      <div class="panel-heading">
        <div>
          <span class="eyebrow">账户</span>
          <h3>USDT 模拟资金</h3>
        </div>
        <button class="ghost-button" @click="store.refreshOverview">刷新</button>
      </div>

      <div class="metric-grid">
        <div>
          <span>现金</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.cash || 0) }}</strong>
        </div>
        <div>
          <span>总权益</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.equity || 0) }}</strong>
        </div>
        <div>
          <span>累计手续费</span>
          <strong>{{ store.formatCurrency(store.cryptoAccount?.total_fee || 0) }}</strong>
        </div>
      </div>
    </article>
  </section>

  <section class="panel-card">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">订单流</span>
        <h3>模拟订单</h3>
      </div>
      <button class="ghost-button" @click="store.fetchCryptoPaperOrders()">刷新订单</button>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>订单号</th>
            <th>交易对</th>
            <th>方向</th>
            <th>数量</th>
            <th>价格</th>
            <th>成交</th>
            <th>状态</th>
            <th>时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="order in store.cryptoOrders" :key="order.order_id">
            <td>{{ order.order_id }}</td>
            <td>{{ order.symbol }}</td>
            <td>{{ order.action }}</td>
            <td>{{ order.quantity }}</td>
            <td>{{ store.formatPrice(order.price) }}</td>
            <td>{{ order.filled_quantity }} @ {{ store.formatPrice(order.filled_price) }}</td>
            <td>
              <span class="status-chip" :class="store.badgeClassForOrder(order.status)">{{ order.status }}</span>
            </td>
            <td>{{ order.created_time }}</td>
            <td>
              <button
                class="inline-button"
                :disabled="!['pending', 'partial_filled'].includes(order.status)"
                @click="store.cancelCryptoPaperOrder(order.order_id)"
              >
                撤单
              </button>
            </td>
          </tr>
          <tr v-if="!store.cryptoOrders.length">
            <td colspan="9">暂无模拟订单。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
