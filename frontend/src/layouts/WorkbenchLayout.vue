<script setup>
import { computed, onBeforeUnmount, onErrorCaptured, onMounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import {
  PhArrowsClockwise,
  PhChartLine,
  PhChartLineUp,
  PhClockCounterClockwise,
  PhCube,
  PhFlask,
  PhGearSix,
  PhListChecks,
  PhRobot,
  PhShieldCheck,
  PhSidebarSimple,
  PhSignOut,
  PhSquaresFour,
  PhTarget,
  PhTestTube,
  PhUserCircle,
  PhWallet,
} from "@phosphor-icons/vue";

import AiChatDrawer from "../components/AiChatDrawer.vue";
import CopilotPet from "../components/CopilotPet.vue";
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
const optimisticRoutePath = ref(route.path);
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
  { label: "决策中枢", icon: PhSquaresFour, to: "/" },
  { label: "市场行情", icon: PhChartLineUp, to: "/market" },
  { label: "手动交易", icon: PhClockCounterClockwise, to: "/trade" },
  { label: "自动交易", icon: PhTarget, to: "/auto" },
  { label: "AI 助手", icon: PhRobot, to: "/ai" },
  { label: "策略中心", icon: PhFlask, to: "/strategy" },
  { label: "回测中心", icon: PhTestTube, to: "/backtest" },
  { label: "投资组合", icon: PhCube, to: "/portfolio" },
  { label: "账户状态", icon: PhWallet, to: "/account" },
  { label: "风控中心", icon: PhShieldCheck, to: "/risk" },
  { label: "审计日志", icon: PhListChecks, to: "/audit" },
  { label: "诊断中心", icon: PhChartLine, to: "/diagnostics" },
  { label: "系统设置", icon: PhGearSix, to: "/settings" },
];

const periodOptions = ["15m", "1h", "4h", "1d"];

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

onMounted(() => {
  window.addEventListener("pointerdown", handleUserInteraction, { passive: true });
  authStore
    .ensureInitialized()
    .then(() => {
      if (authStore.isAuthenticated) {
        return initializeWorkbench();
      }
      return null;
    })
    .catch((error) => setToastError(error, "初始化 HuuQuantAI 工作台失败"));
});

onBeforeUnmount(() => {
  window.removeEventListener("pointerdown", handleUserInteraction);
  teardownWorkbench();
});

watch(
  () => authStore.isAuthenticated,
  (nextValue, previousValue) => {
    if (nextValue && !previousValue) {
      initializeWorkbench().catch((error) => setToastError(error, "初始化 HuuQuantAI 工作台失败"));
    }
    if (!nextValue && previousValue) {
      teardownWorkbench({ reset: true });
    }
  },
);

watch(
  () => route.path,
  (nextPath) => {
    optimisticRoutePath.value = nextPath;
  },
  { immediate: true },
);

function clearVisibleError() {
  clearToastError();
  clearWorkspaceError();
}

function isActiveNavItem(item) {
  const activePath = optimisticRoutePath.value || route.path;
  return activePath === item.to || (item.to !== "/" && activePath.startsWith(`${item.to}/`));
}

function navigateSidebar(item) {
  if (!item?.to || item.to === route.path) {
    optimisticRoutePath.value = route.path;
    return;
  }
  optimisticRoutePath.value = item.to;
  router.push(item.to).catch(() => {
    optimisticRoutePath.value = route.path;
  });
}

function toggleCopilot() {
  if (aiChat.drawerOpen) {
    aiChat.closeDrawer();
    return;
  }
  aiChat.openDrawer();
}

async function changePeriod(period) {
  if (!period || period === marketStore.selectedCryptoPeriod) return;
  marketStore.selectedCryptoPeriod = period;
  await marketStore.fetchCryptoKlines({
    symbol: selectedCryptoSymbol.value,
    period,
    limit: 200,
  });
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
        <RouterLink v-for="item in navItems" :key="`${item.label}-${item.to}`" :to="item.to" custom v-slot="{ href }">
          <a
            :href="href"
            class="cq-nav__item"
            :class="{ active: isActiveNavItem(item) }"
            @click.prevent="navigateSidebar(item)"
          >
            <component :is="item.icon" class="cq-nav__icon" :size="18" weight="regular" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </a>
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
        <small>v1.6.0 · Paper only</small>
      </div>
    </aside>

    <section class="cq-main">
      <header class="cq-topbar">
        <div class="cq-market-strip">
          <button class="cq-menu-button" type="button" title="主菜单" aria-label="主菜单">
            <PhSidebarSimple :size="18" />
          </button>
          <select v-model="selectedCryptoSymbol" class="cq-pair-select" aria-label="选择交易对" @change="changeSymbol">
            <option v-for="symbol in pairOptions" :key="symbol" :value="symbol">{{ symbol }}</option>
          </select>
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
          <div class="cq-period-switch" aria-label="K 线周期">
            <button
              v-for="period in periodOptions"
              :key="period"
              type="button"
              :class="{ active: periodText === period }"
              @click="changePeriod(period)"
            >
              {{ period }}
            </button>
          </div>
        </div>

        <div class="cq-top-actions">
          <div class="cq-model-toggle" aria-label="AI 模型">
            <span>AI 模型</span>
            <div>
              <button
                type="button"
                data-workbench-model="deepseek-v4-flash"
                :class="{ active: aiChat.selectedModel === 'deepseek-v4-flash' }"
                @click="aiChat.setSelectedModel('deepseek-v4-flash')"
              >Flash</button>
              <button
                type="button"
                data-workbench-model="deepseek-v4-pro"
                :class="{ active: aiChat.selectedModel === 'deepseek-v4-pro' }"
                @click="aiChat.setSelectedModel('deepseek-v4-pro')"
              >Pro</button>
            </div>
          </div>
          <div class="cq-mode-card">
            <span>账户模式</span>
            <strong><PhRobot :size="14" /> Binance 模拟</strong>
          </div>
          <div class="cq-mode-card">
            <span>真实交易</span>
            <strong class="number-down"><PhShieldCheck :size="14" /> 已关闭</strong>
          </div>
          <button class="cq-icon-button" title="刷新工作台" aria-label="刷新工作台" @click="refreshWorkspace">
            <PhArrowsClockwise :size="17" />
          </button>
          <button class="cq-icon-button cq-user-button" title="打开 AI 副驾驶" aria-label="打开 AI 副驾驶" @click="toggleCopilot">
            <PhUserCircle :size="18" />
          </button>
          <button class="cq-outline-button cq-logout-button" @click="logout"><PhSignOut :size="15" />退出</button>
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

    <CopilotPet v-if="!aiChat.drawerOpen" @toggle="toggleCopilot" />

    <aside v-if="aiChat.drawerOpen" class="cq-pet-chat-panel" data-copilot-panel>
      <AiChatDrawer surface="pet-panel" />
    </aside>
  </div>
</template>
