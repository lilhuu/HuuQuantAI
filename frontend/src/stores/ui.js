import { ref } from "vue";
import { defineStore } from "pinia";

import {
  badgeClassForEvent,
  badgeClassForOrder,
  eventToneFromType,
  formatCurrency,
  formatPercent,
  formatPrice,
} from "./tradingUtils";

const ORDER_EVENT_CLEAR_MS = 4200;
const SYSTEM_EVENT_CLEAR_MS = 4200;
const ORDER_HIGHLIGHT_CLEAR_MS = 3600;

function createTonePlayer() {
  /** @type {AudioContext | null} */
  let audioContext = null;

  function getAudioContext() {
    if (typeof window === "undefined") {
      return null;
    }

    const AudioContextClass =
      window.AudioContext ||
      /** @type {Window & { webkitAudioContext?: typeof AudioContext }} */ (window).webkitAudioContext;
    if (!AudioContextClass) {
      return null;
    }

    if (!audioContext) {
      audioContext = new AudioContextClass();
    }

    if (audioContext.state === "suspended") {
      audioContext.resume().catch(() => {});
    }

    return audioContext;
  }

  function play(kind = "info") {
    const ctx = getAudioContext();
    if (!ctx) {
      return;
    }

    const profiles = {
      success: [
        { frequency: 784, duration: 0.08, delay: 0 },
        { frequency: 988, duration: 0.12, delay: 0.1 },
      ],
      error: [
        { frequency: 220, duration: 0.14, delay: 0 },
        { frequency: 164, duration: 0.18, delay: 0.12 },
      ],
      warn: [
        { frequency: 392, duration: 0.1, delay: 0 },
        { frequency: 330, duration: 0.1, delay: 0.12 },
      ],
      info: [{ frequency: 660, duration: 0.08, delay: 0 }],
    };

    const notes = profiles[kind] || profiles.info;
    const startAt = ctx.currentTime + 0.01;

    for (const note of notes) {
      const oscillator = ctx.createOscillator();
      const gainNode = ctx.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = note.frequency;
      oscillator.connect(gainNode);
      gainNode.connect(ctx.destination);

      const noteStart = startAt + note.delay;
      gainNode.gain.setValueAtTime(0.0001, noteStart);
      gainNode.gain.exponentialRampToValueAtTime(0.09, noteStart + 0.01);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, noteStart + note.duration);

      oscillator.start(noteStart);
      oscillator.stop(noteStart + note.duration + 0.02);
    }
  }

  return {
    prime() {
      getAudioContext();
    },
    play,
  };
}

const tonePlayer = createTonePlayer();

export const useUiStore = defineStore("trading-ui", () => {
  const soundEnabled = ref(true);
  const recentOrderEvent = ref(null);
  const recentSystemEvent = ref(null);
  const highlightedOrders = ref({});

  let orderEventTimer = null;
  let systemEventTimer = null;
  const orderHighlightTimers = new Map();

  function publishOrderEvent(event) {
    recentOrderEvent.value = {
      ...event,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    };

    markOrderHighlight(event.orderId, event.tone);
    if (["success", "error", "warn"].includes(event.tone)) {
      playAlertTone(event.tone);
    }

    if (orderEventTimer) {
      clearTimeout(orderEventTimer);
    }
    orderEventTimer = setTimeout(() => {
      recentOrderEvent.value = null;
    }, ORDER_EVENT_CLEAR_MS);
  }

  function publishSystemEvent(event) {
    recentSystemEvent.value = {
      ...event,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    };

    if (["success", "error", "warn"].includes(event.tone)) {
      playAlertTone(event.tone);
    }

    if (systemEventTimer) {
      clearTimeout(systemEventTimer);
    }
    systemEventTimer = setTimeout(() => {
      recentSystemEvent.value = null;
    }, SYSTEM_EVENT_CLEAR_MS);
  }

  function markOrderHighlight(orderId, tone) {
    if (!orderId) {
      return;
    }

    highlightedOrders.value = {
      ...highlightedOrders.value,
      [orderId]: tone,
    };

    if (orderHighlightTimers.has(orderId)) {
      clearTimeout(orderHighlightTimers.get(orderId));
    }

    const timer = setTimeout(() => {
      const next = { ...highlightedOrders.value };
      delete next[orderId];
      highlightedOrders.value = next;
      orderHighlightTimers.delete(orderId);
    }, ORDER_HIGHLIGHT_CLEAR_MS);

    orderHighlightTimers.set(orderId, timer);
  }

  function playAlertTone(tone) {
    if (!soundEnabled.value) {
      return;
    }

    const profile = tone === "success" ? "success" : tone === "error" ? "error" : tone === "warn" ? "warn" : "info";
    tonePlayer.play(profile);
  }

  function primeAlertAudio() {
    tonePlayer.prime();
  }

  function setSoundEnabled(nextValue) {
    soundEnabled.value = Boolean(nextValue);
    if (soundEnabled.value) {
      primeAlertAudio();
    }
  }

  function toggleSound() {
    setSoundEnabled(!soundEnabled.value);
  }

  function getOrderRowClass(orderId) {
    const tone = highlightedOrders.value[orderId];
    return tone ? `table-row--flash-${tone}` : "";
  }

  function getOrderPulseClass(orderId) {
    const tone = highlightedOrders.value[orderId];
    return tone ? `timeline-item--flash-${tone}` : "";
  }

  function eventCardClass(tone) {
    return tone ? `alert-card--${tone}` : "";
  }

  function resetUiState() {
    if (orderEventTimer) {
      clearTimeout(orderEventTimer);
      orderEventTimer = null;
    }
    if (systemEventTimer) {
      clearTimeout(systemEventTimer);
      systemEventTimer = null;
    }
    for (const timer of orderHighlightTimers.values()) {
      clearTimeout(timer);
    }
    orderHighlightTimers.clear();

    recentOrderEvent.value = null;
    recentSystemEvent.value = null;
    highlightedOrders.value = {};
  }

  return {
    soundEnabled,
    recentOrderEvent,
    recentSystemEvent,
    highlightedOrders,
    publishOrderEvent,
    publishSystemEvent,
    primeAlertAudio,
    setSoundEnabled,
    toggleSound,
    badgeClassForOrder,
    badgeClassForEvent,
    eventToneFromType,
    getOrderRowClass,
    getOrderPulseClass,
    eventCardClass,
    resetUiState,
    formatCurrency,
    formatPercent,
    formatPrice,
  };
});
