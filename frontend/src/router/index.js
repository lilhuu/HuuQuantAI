import { createRouter, createWebHistory } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { pinia } from "../stores/pinia";

const AccountView = () => import("../views/AccountView.vue");
const AiAdvisorView = () => import("../views/AiAdvisorView.vue");
const AuditView = () => import("../views/AuditView.vue");
const AutoTradingView = () => import("../views/AutoTradingView.vue");
const AuthView = () => import("../views/AuthView.vue");
const DashboardView = () => import("../views/DashboardView.vue");
const DiagnosticsView = () => import("../views/DiagnosticsView.vue");
const MarketView = () => import("../views/MarketView.vue");
const PortfolioView = () => import("../views/PortfolioView.vue");
const ReliabilityView = () => import("../views/ReliabilityView.vue");
const SettingsView = () => import("../views/SettingsView.vue");
const StrategyView = () => import("../views/StrategyView.vue");
const TradeView = () => import("../views/TradeView.vue");
const WorkbenchLayout = () => import("../layouts/WorkbenchLayout.vue");

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
      component: WorkbenchLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: "",
          name: "dashboard",
          component: DashboardView,
          meta: { title: "总览大屏", requiresAuth: true },
        },
        {
          path: "account",
          name: "account",
          component: AccountView,
          meta: { title: "账户状态", requiresAuth: true },
        },
        {
          path: "portfolio",
          name: "portfolio",
          component: PortfolioView,
          meta: { title: "组合分析", requiresAuth: true },
        },
        {
          path: "market",
          name: "market",
          component: MarketView,
          meta: { title: "实时行情", requiresAuth: true },
        },
        {
          path: "trade",
          name: "trade",
          component: TradeView,
          meta: { title: "手动交易", requiresAuth: true },
        },
        {
          path: "auto",
          name: "auto-trading",
          component: AutoTradingView,
          meta: { title: "自动交易", requiresAuth: true },
        },
        {
          path: "ai",
          name: "ai-advisor",
          component: AiAdvisorView,
          meta: { title: "AI 助手", requiresAuth: true },
        },
        {
          path: "strategy",
          name: "strategy",
          component: StrategyView,
          meta: { title: "策略管理", requiresAuth: true },
        },
        {
          path: "risk",
          name: "risk",
          component: ReliabilityView,
          meta: { title: "风控中心", requiresAuth: true },
        },
        {
          path: "audit",
          name: "audit",
          component: AuditView,
          meta: { title: "监控审计", requiresAuth: true },
        },
        {
          path: "diagnostics",
          name: "diagnostics",
          component: DiagnosticsView,
          meta: { title: "策略诊断", requiresAuth: true },
        },
        {
          path: "settings",
          name: "settings",
          component: SettingsView,
          meta: { title: "系统设置", requiresAuth: true },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: { name: "dashboard" } },
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
