<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { useAiChatStore } from "../stores/aiChat";

const emit = defineEmits(["toggle"]);
const aiChat = useAiChatStore();
const sleeping = ref(false);
const reduceMotion = ref(false);
const imageFallback = ref(false);
let sleepTimer = null;
let mediaQuery = null;

const activeState = computed(() => {
  if (sleeping.value && aiChat.petState === "idle" && !aiChat.drawerOpen) return "sleep";
  return aiChat.petState;
});
const statusText = computed(() => {
  const labels = {
    thinking: "正在思考...",
    speaking: "正在实时回答...",
    attention: "回复好了",
    error: "需要重试",
    sleep: "休息中",
    idle: "随时问我",
  };
  return labels[activeState.value] || labels.idle;
});
const stateAsset = computed(() => {
  if (imageFallback.value) return "/assets/huuquant-bot.png";
  if (reduceMotion.value) return "/assets/huuquant-pet/static.png";
  return `/assets/huuquant-pet/${activeState.value}.webp`;
});
const buttonLabel = computed(() => `${aiChat.drawerOpen ? "收起" : "打开"}量化副驾驶，${statusText.value}`);

function scheduleSleep() {
  sleeping.value = false;
  if (sleepTimer) window.clearTimeout(sleepTimer);
  sleepTimer = window.setTimeout(() => {
    if (!aiChat.drawerOpen && aiChat.petState === "idle") sleeping.value = true;
  }, 90000);
}

function handleToggle() {
  scheduleSleep();
  emit("toggle");
}

function handleImageError() {
  imageFallback.value = true;
}

function syncReducedMotion(event) {
  reduceMotion.value = Boolean(event.matches);
}

onMounted(() => {
  mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  reduceMotion.value = mediaQuery.matches;
  mediaQuery.addEventListener?.("change", syncReducedMotion);
  window.addEventListener("pointerdown", scheduleSleep, { passive: true });
  window.addEventListener("keydown", scheduleSleep);
  scheduleSleep();
});

onBeforeUnmount(() => {
  if (sleepTimer) window.clearTimeout(sleepTimer);
  mediaQuery?.removeEventListener?.("change", syncReducedMotion);
  window.removeEventListener("pointerdown", scheduleSleep);
  window.removeEventListener("keydown", scheduleSleep);
});

watch(
  () => [aiChat.petState, aiChat.drawerOpen],
  () => {
    imageFallback.value = false;
    if (aiChat.petState !== "idle" || aiChat.drawerOpen) sleeping.value = false;
  },
);
</script>

<template>
  <div class="copilot-pet" :class="[`copilot-pet--${activeState}`, { 'copilot-pet--open': aiChat.drawerOpen }]">
    <span class="copilot-pet__bubble" aria-live="polite">{{ statusText }}</span>
    <button
      class="copilot-pet__button"
      type="button"
      data-copilot-pet
      :data-pet-state="activeState"
      :aria-label="buttonLabel"
      :aria-pressed="String(aiChat.drawerOpen)"
      @click="handleToggle"
    >
      <span class="copilot-pet__halo" aria-hidden="true"></span>
      <img :src="stateAsset" alt="" draggable="false" @error="handleImageError" />
      <span v-if="aiChat.unreadCount" class="copilot-pet__badge" aria-label="有新的 AI 回复">{{ aiChat.unreadCount }}</span>
    </button>
  </div>
</template>
