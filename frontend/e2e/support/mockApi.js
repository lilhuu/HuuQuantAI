const USER = {
  user_id: 1,
  username: "owner",
  display_name: "E2E 工作台",
};

const QUOTE = {
  symbol: "BTC/USDT",
  market_type: "spot",
  price: 50_000,
  open: 49_000,
  high: 51_000,
  low: 48_500,
  volume: 1_200,
  amount: 60_000_000,
  change: 0.0204,
  change_amount: 1_000,
  bid: 49_999,
  ask: 50_001,
  timestamp: "2026-07-14T00:00:00Z",
  source: "e2e",
};

const AUTO_CONFIG = {
  enabled: false,
  mode: "paper",
  decision_mode: "ai_supervised",
  symbols: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
  period: "1h",
  timeframes: [],
  scan_interval_seconds: 30,
  max_positions: 3,
  per_trade_position_ratio: 0.1,
  max_order_notional: 300,
  min_order_notional: 10,
  confidence_threshold: 0.35,
  ai_model: "deepseek-v4-pro",
  ai_fallback_model: "deepseek-v4-flash",
  ai_on_new_candle_only: true,
  ai_confidence_threshold: 0.65,
  stop_loss_pct: 0.02,
  take_profit_pct: 0.04,
  max_daily_loss: 200,
  max_consecutive_losses: 3,
  cooldown_minutes: 60,
  real_trading_enabled: false,
  strategies: [
    {
      strategy_id: "auto_rsi",
      type: "rsi",
      symbols: ["BTC/USDT"],
      weight: 1,
      enabled: true,
      parameters: { period: 14, oversold: 30, overbought: 70 },
    },
  ],
};

function autoStatus(state, config = state.autoConfig) {
  return {
    state: state.autoState,
    enabled: state.autoState === "running",
    mode: "paper",
    loop_running: state.autoState === "running",
    next_run_at: "",
    last_error_type: "",
    last_message: state.autoState === "running" ? "AI 模拟托管已启动" : "自动交易已停止",
    last_run_at: "",
    cycle_count: 0,
    signal_count: 0,
    order_count: 0,
    last_decisions: [],
    logs: [],
    config,
    ai_supervisor: {
      enabled: state.autoState === "running",
      model: config.ai_model,
      fallback_model: config.ai_fallback_model,
      provider_failure_count: 0,
      last_action: "HOLD",
      last_candle_at: "",
    },
  };
}

async function fulfillJson(route, data, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(data),
  });
}

export async function seedAuthenticatedSession(page) {
  await page.addInitScript(({ user }) => {
    window.localStorage.setItem("huu_quant_ai_access_token", "e2e-token");
    window.localStorage.setItem("huu_quant_ai_user", JSON.stringify(user));
  }, { user: USER });
}

export async function waitForMockApiIdle(page, state, { quietMs = 350, timeoutMs = 5_000 } = {}) {
  const startedAt = Date.now();
  let observedCount = state.requests.length;
  let quietSince = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    await page.waitForTimeout(25);
    if (state.requests.length !== observedCount) {
      observedCount = state.requests.length;
      quietSince = Date.now();
      continue;
    }
    if (Date.now() - quietSince >= quietMs) return;
  }

  throw new Error(`E2E mock API did not become idle after ${timeoutMs}ms`);
}

export async function installApiMocks(page, { authenticated = true } = {}) {
  const state = {
    authenticated,
    loginPayload: null,
    autoConfig: structuredClone(AUTO_CONFIG),
    autoConfigPayload: null,
    autoStartCount: 0,
    autoState: "stopped",
    requests: [],
    unexpectedRequests: [],
  };

  await page.routeWebSocket("**/ws/**", (webSocket) => {
    webSocket.onMessage(() => {});
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    state.requests.push({ method, path });

    if (path === "/auth/status") {
      return fulfillJson(route, {
        setup_required: false,
        authenticated: state.authenticated,
        user: state.authenticated ? USER : null,
      });
    }
    if (path === "/auth/login" && method === "POST") {
      state.loginPayload = request.postDataJSON();
      state.authenticated = true;
      return fulfillJson(route, {
        access_token: "e2e-token",
        token_type: "bearer",
        expires_at: "2099-01-01T00:00:00Z",
        user: USER,
      });
    }
    if (path === "/auth/logout" && method === "POST") {
      state.authenticated = false;
      return fulfillJson(route, { success: true });
    }
    if (path === "/auth/preferences") {
      return fulfillJson(route, method === "GET" ? { preferences: {} } : request.postDataJSON());
    }
    if (path === "/crypto/quotes") {
      return fulfillJson(route, { items: [QUOTE], count: 1, total: 1, source: "e2e" });
    }
    if (path === "/crypto/symbols") {
      return fulfillJson(route, {
        items: [{ symbol: "BTC/USDT", base: "BTC", quote: "USDT", status: "TRADING", market_type: "spot" }],
        count: 1,
        total: 1,
      });
    }
    if (path === "/crypto/klines") {
      return fulfillJson(route, {
        symbol: "BTC/USDT",
        period: "1h",
        count: 2,
        items: [
          { symbol: "BTC/USDT", period: "1h", start_time: "2026-07-13T22:00:00Z", end_time: "2026-07-13T22:59:59Z", open: 49_000, high: 50_100, low: 48_900, close: 50_000, volume: 100, amount: 5_000_000, count: 10 },
          { symbol: "BTC/USDT", period: "1h", start_time: "2026-07-13T23:00:00Z", end_time: "2026-07-13T23:59:59Z", open: 50_000, high: 50_500, low: 49_800, close: 50_200, volume: 120, amount: 6_000_000, count: 12 },
        ],
      });
    }
    if (path === "/crypto/orderbook") {
      return fulfillJson(route, { symbol: "BTC/USDT", bids: [[49_999, 1]], asks: [[50_001, 1]], timestamp: "2026-07-14T00:00:00Z" });
    }
    if (path === "/crypto/derivatives/metrics") {
      return fulfillJson(route, { items: [], count: 0, total: 0 });
    }
    if (path === "/crypto/paper/account") {
      return fulfillJson(route, { cash: 10_000, available_cash: 10_000, market_value: 0, equity: 10_000, total_profit: 0, total_return_percent: 0, total_trades: 0, total_fee: 0, position_count: 0, real_trading_enabled: false });
    }
    if (["/crypto/paper/positions", "/crypto/paper/orders", "/crypto/paper/equity-curve", "/crypto/paper/logs"].includes(path)) {
      return fulfillJson(route, { items: [], count: 0, total: 0 });
    }
    if (path === "/crypto/auto/status") {
      return fulfillJson(route, autoStatus(state));
    }
    if (path === "/crypto/auto/config" && method === "PUT") {
      state.autoConfigPayload = request.postDataJSON();
      state.autoConfig = { ...state.autoConfig, ...state.autoConfigPayload, real_trading_enabled: false };
      return fulfillJson(route, autoStatus(state));
    }
    if (path === "/crypto/auto/start" && method === "POST") {
      state.autoStartCount += 1;
      state.autoState = "running";
      return fulfillJson(route, autoStatus(state));
    }
    if (path.startsWith("/crypto/auto/") && method === "POST") {
      return fulfillJson(route, autoStatus(state));
    }
    if (path === "/crypto/ai/chat/sessions") {
      return fulfillJson(route, { items: [], count: 0, total: 0 });
    }
    if (path === "/crypto/ai/signals") {
      return fulfillJson(route, { items: [], count: 0, total: 0 });
    }
    if (path === "/crypto/strategies/templates") {
      return fulfillJson(route, { items: [], count: 0 });
    }

    state.unexpectedRequests.push({ method, path });
    return fulfillJson(route, { message: `Unexpected E2E API request: ${method} ${path}` }, 501);
  });

  return state;
}

export async function installStreamingChatMock(page) {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.__e2eStreamRequests = [];
    window.__e2eReleaseStreamChunk = () => false;
    window.fetch = async (input, init = {}) => {
      const url = typeof input === "string" ? input : input?.url || "";
      if (!url.includes("/crypto/ai/chat/stream")) {
        return originalFetch(input, init);
      }

      const headers = new Headers(init.headers || {});
      const payload = JSON.parse(String(init.body || "{}"));
      const requestRecord = {
        method: String(init.method || "GET").toUpperCase(),
        accept: headers.get("Accept"),
        authorization: headers.get("Authorization"),
        payload,
      };
      window.__e2eStreamRequests.push(requestRecord);
      if (
        requestRecord.method !== "POST" ||
        requestRecord.accept !== "text/event-stream" ||
        requestRecord.authorization !== "Bearer e2e-token"
      ) {
        return new Response(JSON.stringify({ message: "Invalid streaming request contract" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        });
      }
      const encoder = new TextEncoder();
      const donePayload = {
        session: { session_id: "E2E_SESSION", title: "行情检查" },
        user_message: { message_id: "E2E_USER_MESSAGE", role: "user", content: payload.message },
        assistant_message: {
          message_id: "E2E_ASSISTANT_MESSAGE",
          role: "assistant",
          content: "实时行情正常",
          context_summary: {},
        },
        context_summary: {},
      };
      const chunks = [
        'event: delta\ndata: {"content":"实时"}\n\n',
        'event: delta\ndata: {"content":"行情正常"}\n\n',
        `event: done\ndata: ${JSON.stringify(donePayload)}\n\n`,
      ];
      let streamController = null;
      let chunkIndex = 0;
      window.__e2eReleaseStreamChunk = () => {
        if (!streamController || chunkIndex >= chunks.length) return false;
        streamController.enqueue(encoder.encode(chunks[chunkIndex]));
        chunkIndex += 1;
        if (chunkIndex === chunks.length) streamController.close();
        return true;
      };
      const body = new ReadableStream({
        start(controller) {
          streamController = controller;
        },
      });
      return new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream; charset=utf-8" },
      });
    };
  });
}
