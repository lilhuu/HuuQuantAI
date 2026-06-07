<script setup>
import { computed, onBeforeUnmount, onErrorCaptured, onMounted, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import AiChatDrawer from "../components/AiChatDrawer.vue";
import { useBoot } from "../composables/useBoot";
import { useToast } from "../composables/useToast";
import { useWorkspaceActions } from "../composables/useWorkspaceActions";
import { useAiChatStore } from "../stores/aiChat";
import { useAuthStore } from "../stores/auth";

const aiChat = useAiChatStore();
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const { errorInfo: toastErrorInfo, setError: setToastError, clearError: clearToastError } = useToast();
const { initializeWorkbench, teardownWorkbench } = useBoot();
const {
  autoStateLabel,
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
  { label: "AI 信号", icon: "target", to: "/ai" },
  { label: "账户状态", icon: "wallet", to: "/account" },
  { label: "组合分析", icon: "wallet", to: "/portfolio" },
  { label: "策略验证", icon: "flask", to: "/strategy" },
  { label: "执行可靠性", icon: "shield", to: "/risk" },
  { label: "监控审计", icon: "audit", to: "/audit" },
  { label: "策略诊断", icon: "target", to: "/diagnostics" },
  { label: "系统设置", icon: "settings", to: "/settings" },
];

const visibleErrorInfo = computed(() => toastErrorInfo.value || workspaceErrorInfo.value);

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
          <select v-model="selectedCryptoSymbol" class="cq-pair-select" @change="changeSymbol">
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
            <strong>{{ autoStateLabel }}</strong>
          </div>
          <div class="cq-mode-card">
            <span>账户模式</span>
            <strong>Binance 模拟</strong>
          </div>
          <div class="cq-mode-card">
            <span>当前用户</span>
            <strong>{{ authStore.user?.username || "admin" }}</strong>
          </div>
          <button class="cq-accent-button" title="打开 AI 对话助手" @click="aiChat.openDrawer()">AI 对话</button>
          <button class="cq-icon-button" title="刷新" @click="refreshWorkspace">刷</button>
          <button class="cq-outline-button" @click="logout">退出</button>
        </div>
      </header>

      <section v-if="visibleErrorInfo" class="cq-error">
        <div>
          <strong>{{ visibleErrorInfo.title }}</strong>
          <p>{{ visibleErrorInfo.message }}</p>
        </div>
        <button class="cq-outline-button" @click="clearVisibleError">知道了</button>
      </section>

      <main class="cq-content">
        <RouterView />
      </main>
    </section>

    <AiChatDrawer />
  </div>
</template>
