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
    <div class="auth-hero">
      <p class="brand-kicker">HUU Crypto Quant</p>
      <h1>{{ isSetupMode ? "初始化你的加密货币工作台" : "欢迎回到加密货币工作台" }}</h1>
      <p class="auth-copy">
        这是本地运行的加密货币量化控制台。第一版只启用 Binance 公共行情和本地模拟交易，真实交易默认关闭。
      </p>
    </div>

    <article class="auth-card">
      <header class="panel-header">
        <div>
          <p class="eyebrow">{{ isSetupMode ? "首次初始化" : "本地登录" }}</p>
          <h3>{{ isSetupMode ? "创建管理员账户" : "输入管理员账户" }}</h3>
        </div>
      </header>

      <form class="form-stack" @submit.prevent="submit">
        <label v-if="isSetupMode" class="field">
          <span>用户名</span>
          <input v-model="bootstrapForm.username" autocomplete="username" />
        </label>

        <label v-else class="field">
          <span>用户名</span>
          <input v-model="loginForm.username" autocomplete="username" />
        </label>

        <label v-if="isSetupMode" class="field">
          <span>显示名称</span>
          <input v-model="bootstrapForm.display_name" autocomplete="nickname" />
        </label>

        <label v-if="isSetupMode" class="field">
          <span>密码</span>
          <input
            v-model="bootstrapForm.password"
            type="password"
            autocomplete="new-password"
            placeholder="至少 8 位"
          />
        </label>

        <label v-else class="field">
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

        <p v-if="formMessage" class="inline-message">{{ formMessage }}</p>
      </form>
    </article>
  </section>
</template>
