const TOKEN_KEY = "auto_trader_access_token";
const USER_KEY = "auto_trader_user";

export function getStoredToken() {
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function getStoredUser() {
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function storeSession(token, user) {
  window.localStorage.setItem(TOKEN_KEY, token || "");
  window.localStorage.setItem(USER_KEY, JSON.stringify(user || null));
}

export function clearStoredSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}
