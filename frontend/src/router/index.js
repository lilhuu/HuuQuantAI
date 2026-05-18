import { createRouter, createWebHistory } from "vue-router";

import AccountView from "../views/AccountView.vue";
import AuthView from "../views/AuthView.vue";
import DashboardView from "../views/DashboardView.vue";
import MarketView from "../views/MarketView.vue";
import RiskView from "../views/RiskView.vue";
import { useAuthStore } from "../stores/auth";
import { pinia } from "../stores/pinia";
import StrategyView from "../views/StrategyView.vue";
import TradeView from "../views/TradeView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/auth",
      name: "auth",
      component: AuthView,
      meta: { title: "登录工作台", public: true, authPage: true },
    },
    {
      path: "/",
      name: "dashboard",
      component: DashboardView,
      meta: { title: "总览大屏", requiresAuth: true },
    },
    {
      path: "/account",
      name: "account",
      component: AccountView,
      meta: { title: "账户状态", requiresAuth: true },
    },
    {
      path: "/market",
      name: "market",
      component: MarketView,
      meta: { title: "实时行情", requiresAuth: true },
    },
    {
      path: "/trade",
      name: "trade",
      component: TradeView,
      meta: { title: "手动交易", requiresAuth: true },
    },
    {
      path: "/strategy",
      name: "strategy",
      component: StrategyView,
      meta: { title: "策略管理", requiresAuth: true },
    },
    {
      path: "/risk",
      name: "risk",
      component: RiskView,
      meta: { title: "风控中心", requiresAuth: true },
    },
    {
      path: "/audit",
      name: "audit",
      component: RiskView,
      meta: { title: "监控审计", requiresAuth: true },
    },
    {
      path: "/diagnostics",
      name: "diagnostics",
      component: StrategyView,
      meta: { title: "策略诊断", requiresAuth: true },
    },
    {
      path: "/settings",
      name: "settings",
      component: AccountView,
      meta: { title: "系统设置", requiresAuth: true },
    },
  ],
});

router.beforeEach(async (to) => {
  const authStore = useAuthStore(pinia);
  try {
    await authStore.ensureInitialized();
  } catch {
    if (to.name !== "auth") {
      return { name: "auth" };
    }
    return true;
  }

  if (authStore.setupRequired) {
    if (to.name !== "auth") {
      return { name: "auth" };
    }
    return true;
  }

  if (to.meta.public) {
    if (authStore.isAuthenticated && to.name === "auth") {
      return { name: "dashboard" };
    }
    return true;
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return {
      name: "auth",
      query: { redirect: to.fullPath },
    };
  }

  return true;
});

export default router;
