import { getStoredToken } from "./auth";

function normalizeBaseUrl() {
  const configured = import.meta.env.VITE_WS_BASE_URL;
  if (configured) {
    return configured.replace(/\/$/, "");
  }

  if (window.location.protocol === "https:") {
    return `wss://${window.location.host}`;
  }
  return `ws://${window.location.host}`;
}

function buildSocket(path, queryParams = {}) {
  const base = normalizeBaseUrl();
  const query = new URLSearchParams();

  Object.entries(queryParams).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    query.set(key, String(value));
  });

  const suffix = query.toString() ? `?${query.toString()}` : "";
  return new WebSocket(`${base}${path}${suffix}`);
}

export function sendSocketAuth(socket) {
  const token = getStoredToken();
  if (!socket || socket.readyState !== WebSocket.OPEN || !token) {
    return false;
  }

  socket.send(
    JSON.stringify({
      action: "auth",
      token,
    }),
  );
  return true;
}

export function createCryptoSocket(options = {}) {
  const params = {};
  const symbols = Array.isArray(options) ? options : options.symbols || [];
  if (symbols.length) {
    params.symbols = symbols.join(",");
  }
  if (!Array.isArray(options)) {
    params.period = options.period;
    params.selected_symbol = options.selectedSymbol;
    params.depth_limit = options.depthLimit;
  }
  return buildSocket("/ws/crypto", params);
}

export function createOrdersSocket(filters = {}) {
  return buildSocket("/ws/orders", filters);
}

export function createSystemSocket(options = {}) {
  return buildSocket("/ws/system", options);
}
