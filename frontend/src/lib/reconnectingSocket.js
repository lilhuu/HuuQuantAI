import { sendSocketAuth } from "./ws";

const DEFAULT_RECONNECT_OPTIONS = {
  initialDelayMs: 1000,
  maxDelayMs: 15000,
  jitterMs: 350,
};

const AUTH_CLOSE_CODES = new Set([1008, 4001, 4401, 4408]);

function delayForAttempt(attempt, options) {
  const base = Math.min(options.initialDelayMs * 2 ** Math.max(attempt - 1, 0), options.maxDelayMs);
  const jitter = options.jitterMs > 0 ? Math.floor(Math.random() * options.jitterMs) : 0;
  return base + jitter;
}

function safeClose(socket, code = 1000, reason = "client disconnect") {
  if (!socket) {
    return;
  }

  try {
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close(code, reason);
    }
  } catch (_) {
    // Closing a socket is best-effort; reconnect state is managed separately.
  }
}

export function createReconnectingSocket(options) {
  const reconnectOptions = {
    ...DEFAULT_RECONNECT_OPTIONS,
    ...(options.reconnect || {}),
  };

  let socket = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let manuallyClosed = true;
  let lastArgs = [];

  function setState(state) {
    options.onStateChange?.(state);
  }

  function setSocket(nextSocket) {
    socket = nextSocket;
    options.onSocketChange?.(nextSocket);
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function shouldReconnect(event) {
    if (event && AUTH_CLOSE_CODES.has(event.code)) {
      return false;
    }
    if (manuallyClosed) {
      return false;
    }
    return options.shouldReconnect ? options.shouldReconnect(event) : true;
  }

  function scheduleReconnect(event) {
    if (!shouldReconnect(event)) {
      setState(event && AUTH_CLOSE_CODES.has(event.code) ? "error" : "idle");
      return;
    }

    reconnectAttempt += 1;
    const delayMs = delayForAttempt(reconnectAttempt, reconnectOptions);
    setState("reconnecting");
    options.onReconnectScheduled?.({ attempt: reconnectAttempt, delayMs, event });

    clearReconnectTimer();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      openSocket();
    }, delayMs);
  }

  function openSocket() {
    clearReconnectTimer();
    if (manuallyClosed) {
      return;
    }

    setState(reconnectAttempt > 0 ? "reconnecting" : "connecting");

    let nextSocket;
    try {
      nextSocket = options.createSocket(...lastArgs);
    } catch (error) {
      options.onError?.(error);
      scheduleReconnect({ code: 0, reason: error?.message || "create socket failed" });
      return;
    }

    setSocket(nextSocket);

    nextSocket.onopen = () => {
      if (!sendSocketAuth(nextSocket)) {
        setState("error");
        manuallyClosed = true;
        safeClose(nextSocket, 4001, "missing auth token");
      }
    };

    nextSocket.onmessage = (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        options.onError?.(error);
        return;
      }

      if (payload.type === "auth_ok") {
        reconnectAttempt = 0;
        setState("connected");
        options.onAuthenticated?.(payload, event);
        return;
      }

      options.onMessage?.(payload, event);
    };

    nextSocket.onerror = (event) => {
      if (socket === nextSocket) {
        setState("error");
        options.onError?.(event);
      }
    };

    nextSocket.onclose = (event) => {
      if (socket !== nextSocket) {
        return;
      }

      setSocket(null);
      options.onClose?.(event);
      scheduleReconnect(event);
    };
  }

  function connect(...args) {
    manuallyClosed = false;
    reconnectAttempt = 0;
    lastArgs = args;
    clearReconnectTimer();

    if (socket) {
      const previousSocket = socket;
      setSocket(null);
      safeClose(previousSocket, 1000, "reconnect requested");
    }

    openSocket();
  }

  function disconnect() {
    manuallyClosed = true;
    reconnectAttempt = 0;
    clearReconnectTimer();

    if (socket) {
      const previousSocket = socket;
      setSocket(null);
      safeClose(previousSocket);
    }

    setState("idle");
  }

  function send(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }

    socket.send(typeof payload === "string" ? payload : JSON.stringify(payload));
    return true;
  }

  return {
    connect,
    disconnect,
    send,
    getSocket: () => socket,
  };
}
