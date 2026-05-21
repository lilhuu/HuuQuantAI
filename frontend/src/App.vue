<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { useAuthStore } from "./stores/auth";
import { useAutoTradingStore } from "./stores/autoTrading";
import { useTradingStore } from "./stores/trading";
import { normalizeCryptoSymbol } from "./stores/tradingUtils";

const authStore = useAuthStore();
const autoStore = useAutoTradingStore();
const store = useTradingStore();
const route = useRoute();
const router = useRouter();

const navItems = [
  { label: "仪表盘", icon: "grid", to: "/" },
  { label: "市场分析", icon: "trend", to: "/market" },
  { label: "手动交易", icon: "clock", to: "/trade" },
  { label: "自动交易", icon: "target", to: "/auto" },
  { label: "账户状态", icon: "wallet", to: "/account" },
  { label: "组合分析", icon: "wallet", to: "/portfolio" },
  { label: "策略验证", icon: "flask", to: "/strategy" },
  { label: "执行可靠性", icon: "shield", to: "/risk" },
  { label: "监控审计", icon: "audit", to: "/audit" },
  { label: "策略诊断", icon: "target", to: "/diagnostics" },
  { label: "系统设置", icon: "settings", to: "/settings" },
];

const pairOptions = computed(() => {
  const base = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", ...store.cryptoWatchSymbols];
  return [...new Set(base.map((item) => normalizeCryptoSymbol(item)).filter(Boolean))];
});

const selectedQuote = computed(() => {
  const symbol = normalizeCryptoSymbol(store.selectedCryptoSymbol);
  return store.cryptoQuotes.find((item) => item.symbol === symbol) || null;
});

const priceText = computed(() => store.formatPrice(selectedQuote.value?.price || 0));
const changeText = computed(() => store.formatPercent((selectedQuote.value?.change || 0) * 100));
const changeClass = computed(() => (Number(selectedQuote.value?.change || 0) >= 0 ? "number-up" : "number-down"));
const showShell = computed(() => !route.meta.authPage);

async function initializeWorkbench() {
  if (!authStore.isAuthenticated) {
    return;
  }
  try {
    await authStore.ensureInitialized();
    await store.loadUserPreferences();
    await Promise.allSettled([store.bootstrap(), autoStore.fetchStatus()]);
    store.connectRealtimeStreams();
  } catch (error) {
    store.setError(error, "初始化 HuuQuantAI 工作台失败");
  }
}

async function changeSymbol() {
  const symbol = normalizeCryptoSymbol(store.selectedCryptoSymbol);
  if (!symbol) {
    return;
  }
  store.selectedCryptoSymbol = symbol;
  if (!store.cryptoWatchSymbols.includes(symbol)) {
    store.cryptoWatchSymbols = [...store.cryptoWatchSymbols, symbol];
  }
  await Promise.allSettled([
    store.fetchCryptoQuotes(store.cryptoWatchSymbols),
    store.fetchCryptoKlines({ symbol, period: store.selectedCryptoPeriod || "1h", limit: 200 }),
  ]);
  store.subscribeMarketSocket(store.cryptoWatchSymbols);
}

async function refreshWorkspace() {
  await Promise.allSettled([
    store.refreshOverview(),
    autoStore.fetchStatus(),
    store.fetchCryptoQuotes(store.cryptoWatchSymbols),
    store.fetchCryptoKlines({
      symbol: store.selectedCryptoSymbol,
      period: store.selectedCryptoPeriod || "1h",
      limit: 200,
    }),
  ]);
}

async function logout() {
  store.disconnectRealtimeStreams();
  store.resetState();
  await authStore.logout();
  router.push({ name: "auth" });
}

function handleUserInteraction() {
  store.primeAlertAudio();
}

onMounted(async () => {
  window.addEventListener("pointerdown", handleUserInteraction, { passive: true });
  await authStore.ensureInitialized();
  if (authStore.isAuthenticated) {
    await initializeWorkbench();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("pointerdown", handleUserInteraction);
  store.disconnectRealtimeStreams();
});

watch(
  () => authStore.isAuthenticated,
  async (nextValue, previousValue) => {
    if (nextValue && !previousValue) {
      await initializeWorkbench();
    }
    if (!nextValue && previousValue) {
      store.disconnectRealtimeStreams();
      store.resetState();
    }
  },
);
</script>

<template>
  <RouterView v-if="!showShell" />

  <div v-else class="cq-shell">
    <aside class="cq-sidebar">
      <div class="cq-brand">
        <div class="cq-brand__mark" aria-hidden="true">
          <span></span>
        </div>
        <div>
          <strong>HuuQuantAI</strong>
          <span>量化控制台</span>
        </div>
      </div>

      <nav class="cq-nav" aria-label="主功能表">
        <RouterLink
          v-for="item in navItems"
          :key="`${item.label}-${item.to}`"
          :to="item.to"
          class="cq-nav__item"
          :class="{ active: route.path === item.to || item.match?.includes(route.path) }"
        >
          <span class="cq-icon" :data-icon="item.icon" aria-hidden="true"></span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="cq-sidebar-card">
        <strong>系统状态</strong>
        <button class="cq-outline-button cq-legacy-button" @click="refreshWorkspace">
          <span class="cq-lock-icon" aria-hidden="true"></span>
          刷新工作台
        </button>
      </div>
    </aside>

    <section class="cq-main">
      <header class="cq-topbar">
        <div class="cq-market-strip">
          <select v-model="store.selectedCryptoSymbol" class="cq-pair-select" @change="changeSymbol">
            <option v-for="symbol in pairOptions" :key="symbol" :value="symbol">{{ symbol }}</option>
          </select>
          <div class="cq-top-stat">
            <span>当前价格</span>
            <strong>{{ priceText }}</strong>
          </div>
          <div class="cq-top-stat cq-top-stat--green">
            <span>24H</span>
            <strong :class="changeClass">{{ changeText }}</strong>
          </div>
        </div>

        <div class="cq-top-actions">
          <div class="cq-mode-card">
            <span>自动交易</span>
            <strong>{{ autoStore.stateLabel }}</strong>
          </div>
          <div class="cq-mode-card">
            <span>账户模式</span>
            <strong>Binance 模拟</strong>
          </div>
          <div class="cq-mode-card">
            <span>当前用户</span>
            <strong>{{ authStore.user?.username || "admin" }}</strong>
          </div>
          <button class="cq-icon-button" title="刷新" @click="refreshWorkspace">刷新</button>
          <button class="cq-outline-button" @click="logout">退出</button>
        </div>
      </header>

      <section v-if="store.errorInfo" class="cq-error">
        <div>
          <strong>{{ store.errorInfo.title }}</strong>
          <p>{{ store.errorInfo.message }}</p>
        </div>
        <button class="cq-outline-button" @click="store.clearError()">知道了</button>
      </section>

      <main class="cq-content">
        <RouterView />
      </main>
    </section>
  </div>
</template>
