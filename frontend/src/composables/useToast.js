import { computed, ref } from "vue";

import { classifyApiError } from "../lib/api";

const currentError = ref(null);

function hasSpecificMessage(error) {
  return Boolean(
    error?.message ||
      error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.response?.data?.error_code ||
      error?.response?.data?.business_code,
  );
}

export function useToast() {
  const errorInfo = computed(() => currentError.value);

  function setError(error, fallbackMessage = "请求失败") {
    const classified = classifyApiError(error);
    const message =
      hasSpecificMessage(error) && classified.message ? classified.message : fallbackMessage || classified.message;

    currentError.value = {
      ...classified,
      message,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    };
  }

  function clearError() {
    currentError.value = null;
  }

  return {
    errorInfo,
    setError,
    clearError,
  };
}
