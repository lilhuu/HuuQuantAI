import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { apiClient, extractApiError } from "../lib/api";
import { clearStoredSession, getStoredToken, getStoredUser, storeSession } from "../lib/auth";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(getStoredToken());
  const user = ref(getStoredUser());
  const setupRequired = ref(false);
  const initialized = ref(false);
  const loading = ref(false);
  const errorMessage = ref("");

  const isAuthenticated = computed(() => Boolean(token.value && user.value));

  function applySession(session) {
    token.value = session.access_token;
    user.value = session.user;
    storeSession(session.access_token, session.user);
  }

  function clearSession() {
    token.value = "";
    user.value = null;
    clearStoredSession();
  }

  async function ensureInitialized() {
    if (initialized.value) {
      return;
    }
    await refreshStatus();
  }

  async function refreshStatus() {
    loading.value = true;
    errorMessage.value = "";

    try {
      const { data } = await apiClient.get("/auth/status");
      setupRequired.value = Boolean(data.setup_required);
      if (data.authenticated && data.user) {
        user.value = data.user;
        token.value = getStoredToken();
        storeSession(token.value, data.user);
      } else {
        clearSession();
      }
      initialized.value = true;
      return data;
    } catch (error) {
      clearSession();
      initialized.value = true;
      errorMessage.value = extractApiError(error);
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function bootstrap(payload) {
    loading.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.post("/auth/bootstrap", payload);
      applySession(data);
      setupRequired.value = false;
      initialized.value = true;
      return data;
    } catch (error) {
      errorMessage.value = extractApiError(error);
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function login(payload) {
    loading.value = true;
    errorMessage.value = "";
    try {
      const { data } = await apiClient.post("/auth/login", payload);
      applySession(data);
      setupRequired.value = false;
      initialized.value = true;
      return data;
    } catch (error) {
      errorMessage.value = extractApiError(error);
      throw error;
    } finally {
      loading.value = false;
    }
  }

  async function logout() {
    try {
      if (token.value) {
        await apiClient.post("/auth/logout");
      }
    } catch {
      // Ignore logout cleanup errors and clear local session anyway.
    } finally {
      clearSession();
      initialized.value = true;
      setupRequired.value = false;
    }
  }

  return {
    token,
    user,
    setupRequired,
    initialized,
    loading,
    errorMessage,
    isAuthenticated,
    ensureInitialized,
    refreshStatus,
    bootstrap,
    login,
    logout,
    clearSession,
  };
});
