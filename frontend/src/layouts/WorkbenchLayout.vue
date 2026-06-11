<script setup>
import { computed, onBeforeUnmount, onErrorCaptured, onMounted, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import AiChatDrawer from "../components/AiChatDrawer.vue";
import { useBoot } from "../composables/useBoot";
import { useToast } from "../composables/useToast";
import { useWorkspaceActions } from "../composables/useWorkspaceActions";
import { useAiChatStore } from "../stores/aiChat";
import { useAuthStore } from "../stores/auth";
import { useMarketStore } from "../stores/market";

const aiChat = useAiChatStore();
const authStore = useAuthStore();
const marketStore = useMarketStore();
const route = useRoute();
const router = useRouter();
const { errorInfo: toastErrorInfo, setError: setToastError, clearError: clearToastError } = useToast();
const { initializeWorkbench, teardownWorkbench } = useBoot();
const {
  pairOptions,
  selectedCryptoSymbol,
  priceText,
  changeText,
  changeClass,
  errorInfo: workspaceErrorInfo,
  changeSymbol,
  refreshWorkspace,
  clearWorkspaceError,
  primeAlertAudio,
} = useWorkspaceActions();

const navItems = [
  { label: "仪表盘", icon: "grid", to: "/" },
  { label: "市场分析", icon: "trend", to: "/market" },
  { label: "手动交易", icon: "clock", to: "/trade" },
  { label: "自动交易", icon: "target", to: "/auto" },
  { label: "AI 助手", icon: "target", to: "/ai" },
  { label: "策略验证", icon: "flask", to: "/strategy" },
  { label: "回测中心", icon: "audit", to: "/backtest" },
  { label: "投资组合", icon: "wallet", to: "/portfolio" },
  { label: "账户状态", icon: "wallet", to: "/account" },
  { label: "执行可靠性", icon: "shield", to: "/risk" },
  { label: "监控审计", icon: "audit", to: "/audit" },
  { label: "策略诊断", icon: "target", to: "/diagnostics" },
  { label: "系统设置", icon: "settings", to: "/settings" },
];

const visibleErrorInfo = computed(() => toastErrorInfo.value || workspaceErrorInfo.value);
const selectedQuote = computed(
  () => marketStore.cryptoQuotes.find((item) => item.symbol === selectedCryptoSymbol.value) || null,
);
const periodText = computed(() => marketStore.selectedCryptoPeriod || "1h");
const highText = computed(() => formatTopPrice(selectedQuote.value?.high || selectedQuote.value?.high24h || 0));
const lowText = computed(() => formatTopPrice(selectedQuote.value?.low || selectedQuote.value?.low24h || 0));
const volumeText = computed(() =>
  formatTopVolume(selectedQuote.value?.volume || selectedQuote.value?.quote_volume || selectedQuote.value?.baseVolume || 0),
);

async function logout() {
  teardownWorkbench({ reset: true });
  await authStore.logout();
  router.push({ name: "auth" });
}

function handleUserInteraction() {
  primeAlertAudio();
}

onErrorCaptured((error, _instance, info) => {
  setToastError(error, `界面组件异常：${info || "未知位置"}`);
  return false;
});

onMounted(async () => {
  window.addEventListener("pointerdown", handleUserInteraction, { passive: true });
  await authStore.ensureInitialized();
  if (authStore.isAuthenticated) {
    await initializeWorkbench();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("pointerdown", handleUserInteraction);
  teardownWorkbench();
});

watch(
  () => authStore.isAuthenticated,
  async (nextValue, previousValue) => {
    if (nextValue && !previousValue) {
      await initializeWorkbench();
    }
    if (!nextValue && previousValue) {
      teardownWorkbench({ reset: true });
    }
  },
);

function clearVisibleError() {
  clearToastError();
  clearWorkspaceError();
}

function isActiveNavItem(item) {
  return route.path === item.to || (item.to !== "/" && route.path.startsWith(`${item.to}/`));
}

function formatTopPrice(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "--";
  return number >= 100 ? number.toLocaleString("en-US", { maximumFractionDigits: 2 }) : number.toFixed(5);
}

function formatTopVolume(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "--";
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(2)}K`;
  return number.toFixed(2);
}
</script>

<template>
  <div class="cq-shell">
    <aside class="cq-sidebar">
      <div class="cq-brand">
        <div class="cq-brand__mark" aria-hidden="true">
          <img src="/assets/huuquant-bot.png" alt="" />
        </div>
        <div>
          <strong>HuuQuantAI</strong>
          <span>本地量化工作台</span>
        </div>
      </div>

      <nav class="cq-nav" aria-label="主功能栏">
        <RouterLink
          v-for="item in navItems"
          :key="`${item.label}-${item.to}`"
          :to="item.to"
          class="cq-nav__item"
          :class="{ active: isActiveNavItem(item) }"
        >
          <span class="cq-icon" :data-icon="item.icon" aria-hidden="true"></span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="cq-sidebar-card">
        <div class="cq-sidebar-status-row">
          <span>系统状态</span>
          <strong>正常运行</strong>
        </div>
        <div class="cq-sidebar-status-row">
          <span>行情连接</span>
          <strong>实时监听</strong>
        </div>
        <div class="cq-sidebar-status-row">
          <span>交易引擎</span>
          <strong>模拟模式</strong>
        </div>
        <small>v1.3.0</small>
      </div>
    </aside>

    <section class="cq-main">
      <header class="cq-topbar">
        <div class="cq-market-strip">
          <button class="cq-menu-button" type="button" title="主菜单" aria-label="主菜单">☰</button>
          <select v-model="selectedCryptoSymbol" class="cq-pair-select" aria-label="选择交易对" @change="changeSymbol">
            <option v-for="symbol in pairOptions" :key="symbol" :value="symbol">{{ symbol }}</option>
          </select>
          <span class="cq-favorite-star" aria-hidden="true">★</span>
          <div class="cq-top-stat">
            <span>最新价</span>
            <strong>{{ priceText }}</strong>
          </div>
          <div class="cq-top-stat cq-top-stat--green">
            <span>24h 涨跌</span>
            <strong :class="changeClass">{{ changeText }}</strong>
          </div>
          <div class="cq-top-stat">
            <span>24h 最高</span>
            <strong>{{ highText }}</strong>
          </div>
          <div class="cq-top-stat">
            <span>24h 最低</span>
            <strong>{{ lowText }}</strong>
          </div>
          <div class="cq-top-stat cq-top-stat--volume">
            <span>24h 成交量</span>
            <strong>{{ volumeText }}</strong>
          </div>
          <div class="cq-period-pill">
            <strong>{{ periodText }}</strong>
            <span>周期</span>
          </div>
        </div>

        <div class="cq-top-actions">
          <div class="cq-model-toggle" aria-label="AI 模型">
            <span>AI 模型</span>
            <div>
              <button class="active" type="button">Flash</button>
              <button type="button">Pro</button>
            </div>
          </div>
          <div class="cq-mode-card">
            <span>账户模式</span>
            <strong>Binance 模拟</strong>
          </div>
          <div class="cq-mode-card">
            <span>真实交易</span>
            <strong class="number-down">已关闭</strong>
          </div>
          <button
            class="cq-icon-button cq-user-button"
            :title="`打开 AI 助手：${authStore.user?.username || 'admin'}`"
            aria-label="打开 AI 助手"
            @click="aiChat.openDrawer()"
          >
            <span aria-hidden="true">AI</span>
          </button>
          <button class="cq-icon-button" title="刷新工作台" aria-label="刷新工作台" @click="refreshWorkspace">↻</button>
          <button class="cq-outline-button cq-logout-button" @click="logout">退出</button>
        </div>
      </header>

      <section v-if="visibleErrorInfo" class="cq-error">
        <div>
          <strong>{{ visibleErrorInfo.title }}</strong>
          <p>{{ visibleErrorInfo.message }}</p>
        </div>
        <button class="cq-outline-button" @click="clearVisibleError">我知道了</button>
      </section>

      <main class="cq-content">
        <RouterView />
      </main>
    </section>

    <AiChatDrawer />
  </div>
</template>
