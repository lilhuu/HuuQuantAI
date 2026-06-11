<script setup>
import { computed, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { extractApiError } from "../lib/api";
import { useAuthStore } from "../stores/auth";

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();
const submitting = ref(false);
const formMessage = ref("");

const bootstrapForm = reactive({
  username: "owner",
  display_name: "我的加密货币工作台",
  password: "",
});

const loginForm = reactive({
  username: "owner",
  password: "",
});

const isSetupMode = computed(() => authStore.setupRequired);
const submitText = computed(() => {
  if (submitting.value) {
    return "处理中...";
  }
  return isSetupMode.value ? "创建并进入工作台" : "登录工作台";
});

async function submit() {
  submitting.value = true;
  formMessage.value = "";

  try {
    if (isSetupMode.value) {
      await authStore.bootstrap({ ...bootstrapForm });
    } else {
      await authStore.login({ ...loginForm });
    }

    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    router.push(redirect);
  } catch (error) {
    formMessage.value = extractApiError(error);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="auth-page">
    <div class="auth-market-grid" aria-hidden="true"></div>

    <section class="auth-hero">
      <div class="auth-brand-row">
        <div class="auth-brand-mark">HQ</div>
        <div>
          <p class="auth-kicker">HuuQuantAI</p>
          <span>本地量化交易工作台</span>
        </div>
      </div>

      <h1>{{ isSetupMode ? "初始化你的加密货币量化工作台" : "欢迎回到 HuuQuantAI" }}</h1>
      <p class="auth-copy">
        专注加密货币行情、策略验证和本地模拟交易。第一版使用 Binance 公共行情，真实交易默认关闭。
      </p>

      <div class="auth-trust-grid">
        <article>
          <span>行情源</span>
          <strong>Binance 公共行情</strong>
        </article>
        <article>
          <span>交易模式</span>
          <strong>本地模拟交易</strong>
        </article>
        <article>
          <span>安全边界</span>
          <strong>真实交易默认关闭</strong>
        </article>
      </div>

      <div class="auth-telemetry">
        <div>
          <span>BTC/USDT</span>
          <strong>Paper Ready</strong>
        </div>
        <svg viewBox="0 0 420 96" role="img" aria-label="模拟行情走势">
          <path d="M4 68 L44 68 L72 54 L104 60 L138 34 L172 48 L206 28 L244 58 L278 46 L318 20 L356 38 L416 24" fill="none" stroke="rgba(21,219,219,0.95)" stroke-width="3" />
          <path d="M4 82 L58 76 L104 80 L150 70 L202 72 L254 58 L306 64 L356 50 L416 54" fill="none" stroke="rgba(66,232,158,0.72)" stroke-width="2" />
        </svg>
      </div>
    </section>

    <article class="auth-card">
      <header class="auth-card-header">
        <p class="auth-kicker">{{ isSetupMode ? "首次初始化" : "本地登录" }}</p>
        <h2>{{ isSetupMode ? "创建管理员账户" : "输入管理员账户" }}</h2>
        <p>{{ isSetupMode ? "设置本机管理员，用于保护本地量化工作台。" : "登录后进入行情、策略、模拟交易和审计工作区。" }}</p>
      </header>

      <form class="form-stack auth-form" @submit.prevent="submit">
        <label v-if="isSetupMode" class="field auth-field">
          <span>用户名</span>
          <input v-model="bootstrapForm.username" autocomplete="username" />
        </label>

        <label v-else class="field auth-field">
          <span>用户名</span>
          <input v-model="loginForm.username" autocomplete="username" />
        </label>

        <label v-if="isSetupMode" class="field auth-field">
          <span>显示名称</span>
          <input v-model="bootstrapForm.display_name" autocomplete="nickname" />
        </label>

        <label v-if="isSetupMode" class="field auth-field">
          <span>密码</span>
          <input
            v-model="bootstrapForm.password"
            type="password"
            autocomplete="new-password"
            placeholder="至少 8 位"
          />
        </label>

        <label v-else class="field auth-field">
          <span>密码</span>
          <input
            v-model="loginForm.password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入登录密码"
          />
        </label>

        <button class="primary-button auth-submit" type="submit" :disabled="submitting">
          {{ submitText }}
        </button>

        <p class="auth-safety-note">本地认证只保护当前工作台。真实交易需要单独确认流程，本页不会开启真实下单。</p>
        <p v-if="formMessage" class="inline-message auth-message">{{ formMessage }}</p>
      </form>
    </article>
  </section>
</template>
