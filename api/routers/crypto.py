"""Crypto-only market data and paper-trading endpoints."""

from collections import defaultdict, deque
from time import monotonic

from fastapi import APIRouter, Depends, Query, Request

from api.dependencies import get_crypto_service
from api.error_codes import ApiError, ErrorCode
from api.models.request import (
    AiChatRequest,
    AiSignalAnalyzeRequest,
    AutoTradingConfigRequest,
    BinanceTestnetCredentialsRequest,
    BinanceTestnetEnableRequest,
    BinanceTestnetOrderRequest,
    CryptoPaperOrderRequest,
    CryptoShadowOrderRequest,
    CryptoStrategyBacktestRequest,
    CryptoStrategyRunRequest,
    CryptoStrategyWalkForwardRequest,
    PortfolioReturnsRequest,
)
from api.models.response import (
    AiChatResponse,
    AiChatSessionDetailResponse,
    AiChatSessionListResponse,
    AiSignalAnalyzeResponse,
    AiSignalListResponse,
    AiSignalPaperOrderResponse,
    AiSignalRecordResponse,
    AutoTradingStatusResponse,
    AutoTradingLogsResponse,
    BinanceTestnetActionResponse,
    BinanceTestnetOrderResponse,
    BinanceTestnetStatusResponse,
    ConnectionHealthResponse,
    CryptoKLinesResponse,
    CryptoOrderBookResponse,
    CryptoPaperAccountResponse,
    CryptoPaperEquityCurveResponse,
    CryptoPaperLogsResponse,
    CryptoPaperOrdersResponse,
    CryptoPaperOrderResponse,
    CryptoPaperPositionsResponse,
    CryptoQuotesResponse,
    CryptoSymbolInfoResponse,
    CryptoSymbolListResponse,
    CryptoShadowLogsResponse,
    CryptoShadowPositionsResponse,
    CryptoShadowTradeResponse,
    CryptoStrategyBacktestResponse,
    CryptoStrategyRunResponse,
    CryptoStrategyTemplatesResponse,
    CryptoWalkForwardResponse,
    MacroOverviewResponse,
    MarketRegimeBatchResponse,
    MessageResponse,
    PortfolioReturnsResponse,
)
from api.services.crypto_service import CryptoService


router = APIRouter(prefix="/crypto", tags=["crypto"])
_MARKET_RATE_LIMIT_WINDOW_SECONDS = 60.0
_MARKET_RATE_LIMIT_MAX_REQUESTS = 600
_market_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def _parse_symbols(symbols: str | None) -> list[str] | None:
    if symbols is None:
        return None
    parsed = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    return parsed or None


def _rate_limit_market_data(request: Request) -> None:
    client_host = request.client.host if request.client else "local"
    key = f"{client_host}:{request.url.path}"
    now = monotonic()
    bucket = _market_rate_buckets[key]
    while bucket and now - bucket[0] > _MARKET_RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _MARKET_RATE_LIMIT_MAX_REQUESTS:
        retry_after = max(1, int(_MARKET_RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        raise ApiError(
            429,
            "Crypto market data rate limit exceeded; please retry later.",
            ErrorCode.RATE_LIMITED,
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)


@router.get("/quotes", response_model=CryptoQuotesResponse, summary="Get crypto quotes")
async def get_crypto_quotes(
    symbols: str | None = Query(default=None, description="Comma-separated symbols, for example BTC/USDT,ETH/USDT."),
    search: str | None = Query(default=None, description="Search by symbol or base asset."),
    quote: str | None = Query(default=None, description="Quote currency filter, e.g. USDT."),
    limit: int = Query(default=0, ge=0, le=500, description="Page size. 0 returns all."),
    offset: int = Query(default=0, ge=0, description="Page offset."),
    _: None = Depends(_rate_limit_market_data),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoQuotesResponse:
    return await service.get_quotes(_parse_symbols(symbols), search=search, quote=quote, limit=limit, offset=offset)


@router.get("/symbols", response_model=CryptoSymbolListResponse, summary="List available trading pairs")
async def get_crypto_symbols(
    quote: str | None = Query(default=None, description="Quote currency filter, e.g. USDT."),
    search: str | None = Query(default=None, description="Search by symbol or base asset."),
    status: str = Query(default="active", description="Symbol status filter."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoSymbolListResponse:
    return await service.get_available_symbols(quote=quote, search=search, status=status, limit=limit, offset=offset)


@router.get("/klines", response_model=CryptoKLinesResponse, summary="Get crypto OHLCV candles")
async def get_crypto_klines(
    symbol: str = Query(..., description="Trading pair, for example BTC/USDT."),
    period: str = Query(default="1h", description="Timeframe: 1m, 5m, 15m, 1h, 4h, 1d."),
    limit: int = Query(default=200, ge=1, le=1000, description="Number of candles."),
    _: None = Depends(_rate_limit_market_data),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoKLinesResponse:
    return await service.get_klines(symbol=symbol, period=period, limit=limit)


@router.get("/orderbook", response_model=CryptoOrderBookResponse, summary="Get crypto order book")
async def get_crypto_orderbook(
    symbol: str = Query(..., description="Trading pair, for example BTC/USDT."),
    limit: int = Query(default=20, ge=1, le=100, description="Number of price levels per side."),
    _: None = Depends(_rate_limit_market_data),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoOrderBookResponse:
    return await service.get_orderbook(symbol=symbol, limit=limit)


@router.get("/market/regime", response_model=MarketRegimeBatchResponse, summary="Detect crypto market regime")
async def get_crypto_market_regime(
    symbols: str = Query(default="BTC/USDT,ETH/USDT", description="Comma-separated symbols."),
    period: str = Query(default="1h", description="Timeframe: 1m, 5m, 15m, 1h, 4h, 1d."),
    limit: int = Query(default=100, ge=30, le=500),
    service: CryptoService = Depends(get_crypto_service),
) -> MarketRegimeBatchResponse:
    symbol_list = [item.strip() for item in symbols.split(",") if item.strip()]
    return await service.detect_market_regime(symbol_list, period=period, limit=limit)


@router.get("/macro", response_model=MacroOverviewResponse, summary="Get macro risk overview")
async def get_crypto_macro_overview(
    service: CryptoService = Depends(get_crypto_service),
) -> MacroOverviewResponse:
    return await service.get_macro_overview()


@router.get("/health/connection", response_model=ConnectionHealthResponse, summary="Get exchange connection health")
async def get_crypto_connection_health(
    service: CryptoService = Depends(get_crypto_service),
) -> ConnectionHealthResponse:
    return await service.get_connection_health()


@router.post("/paper/orders", response_model=CryptoPaperOrderResponse, summary="Place crypto paper order")
async def place_crypto_paper_order(
    request: CryptoPaperOrderRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoPaperOrderResponse:
    return await service.place_paper_order(request)


@router.get("/paper/orders", response_model=CryptoPaperOrdersResponse, summary="List crypto paper orders")
async def get_crypto_paper_orders(
    status: str | None = Query(default=None, description="Order status, for example filled or rejected."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoPaperOrdersResponse:
    return await service.get_paper_orders(status=status, limit=limit, offset=offset)


@router.delete("/paper/orders/{order_id}", response_model=MessageResponse, summary="Cancel crypto paper order")
async def cancel_crypto_paper_order(
    order_id: str,
    service: CryptoService = Depends(get_crypto_service),
) -> MessageResponse:
    result = await service.cancel_paper_order(order_id)
    if not result.get("success"):
        raise ApiError(400, result.get("message", "crypto paper order cannot be cancelled"), ErrorCode.ORDER_CANCEL_FAILED)
    return MessageResponse(success=True, message=result.get("message", "crypto paper order cancelled"))


@router.get("/paper/account", response_model=CryptoPaperAccountResponse, summary="Get crypto paper account")
async def get_crypto_paper_account(
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoPaperAccountResponse:
    return await service.get_paper_account()


@router.get("/paper/positions", response_model=CryptoPaperPositionsResponse, summary="Get crypto paper positions")
async def get_crypto_paper_positions(
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoPaperPositionsResponse:
    return await service.get_paper_positions()


@router.get("/paper/equity-curve", response_model=CryptoPaperEquityCurveResponse, summary="Get crypto paper equity curve")
async def get_crypto_paper_equity_curve(
    limit: int = Query(default=200, ge=1, le=1000),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoPaperEquityCurveResponse:
    return await service.get_paper_equity_curve(limit=limit)


@router.get("/paper/logs", response_model=CryptoPaperLogsResponse, summary="Get crypto paper logs")
async def get_crypto_paper_logs(
    limit: int = Query(default=100, ge=1, le=500),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoPaperLogsResponse:
    return await service.get_paper_logs(limit=limit)


@router.get("/auto/status", response_model=AutoTradingStatusResponse, summary="Get paper auto-trading status")
async def get_crypto_auto_trading_status(
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingStatusResponse:
    return await service.get_auto_trading_status()


@router.put("/auto/config", response_model=AutoTradingStatusResponse, summary="Update paper auto-trading config")
async def update_crypto_auto_trading_config(
    request: AutoTradingConfigRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingStatusResponse:
    return await service.update_auto_trading_config(request)


@router.post("/auto/start", response_model=AutoTradingStatusResponse, summary="Start paper auto-trading")
async def start_crypto_auto_trading(
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingStatusResponse:
    return await service.start_auto_trading()


@router.post("/auto/pause", response_model=AutoTradingStatusResponse, summary="Pause paper auto-trading")
async def pause_crypto_auto_trading(
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingStatusResponse:
    return await service.pause_auto_trading()


@router.post("/auto/stop", response_model=AutoTradingStatusResponse, summary="Stop paper auto-trading")
async def stop_crypto_auto_trading(
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingStatusResponse:
    return await service.stop_auto_trading()


@router.post("/auto/scan", response_model=AutoTradingStatusResponse, summary="Run one paper auto-trading scan")
async def scan_crypto_auto_trading(
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingStatusResponse:
    return await service.run_auto_trading_cycle()


@router.get("/auto/logs", response_model=AutoTradingLogsResponse, summary="Get paper auto-trading logs")
async def get_crypto_auto_trading_logs(
    limit: int = Query(default=100, ge=1, le=500),
    service: CryptoService = Depends(get_crypto_service),
) -> AutoTradingLogsResponse:
    return await service.get_auto_trading_logs(limit=limit)


@router.post("/ai/analyze", response_model=AiSignalAnalyzeResponse, summary="Run manual AI advisory analysis")
async def analyze_crypto_ai_signal(
    request: AiSignalAnalyzeRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> AiSignalAnalyzeResponse:
    return await service.analyze_ai_signal(request)


@router.post("/ai/chat", response_model=AiChatResponse, summary="Chat with the advisory-only AI assistant")
async def chat_crypto_ai_assistant(
    request: AiChatRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> AiChatResponse:
    return await service.chat_ai_assistant(request)


@router.get("/ai/chat/sessions", response_model=AiChatSessionListResponse, summary="List AI chat sessions")
async def list_crypto_ai_chat_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: CryptoService = Depends(get_crypto_service),
) -> AiChatSessionListResponse:
    return await service.list_ai_chat_sessions(limit=limit, offset=offset)


@router.get("/ai/chat/sessions/{session_id}", response_model=AiChatSessionDetailResponse, summary="Get AI chat session")
async def get_crypto_ai_chat_session(
    session_id: str,
    service: CryptoService = Depends(get_crypto_service),
) -> AiChatSessionDetailResponse:
    return await service.get_ai_chat_session(session_id)


@router.delete("/ai/chat/sessions/{session_id}", response_model=MessageResponse, summary="Delete AI chat session")
async def delete_crypto_ai_chat_session(
    session_id: str,
    service: CryptoService = Depends(get_crypto_service),
) -> MessageResponse:
    result = await service.delete_ai_chat_session(session_id)
    return MessageResponse(success=bool(result.get("success")), message=str(result.get("message") or "AI chat session deleted"))


@router.get("/ai/signals", response_model=AiSignalListResponse, summary="List AI advisory signals")
async def list_crypto_ai_signals(
    symbol: str | None = Query(default=None, description="Optional trading pair filter."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: CryptoService = Depends(get_crypto_service),
) -> AiSignalListResponse:
    return await service.list_ai_signals(limit=limit, offset=offset, symbol=symbol)


@router.get("/ai/signals/{signal_id}", response_model=AiSignalRecordResponse, summary="Get one AI advisory signal")
async def get_crypto_ai_signal(
    signal_id: str,
    service: CryptoService = Depends(get_crypto_service),
) -> AiSignalRecordResponse:
    return await service.get_ai_signal(signal_id)


@router.post("/ai/signals/{signal_id}/paper-order", response_model=AiSignalPaperOrderResponse, summary="Manually convert AI signal to paper order")
async def create_crypto_ai_paper_order(
    signal_id: str,
    service: CryptoService = Depends(get_crypto_service),
) -> AiSignalPaperOrderResponse:
    return await service.create_ai_signal_paper_order(signal_id)


@router.post("/shadow/orders", response_model=CryptoShadowTradeResponse, summary="Execute shadow trade")
async def place_crypto_shadow_order(
    request: CryptoShadowOrderRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoShadowTradeResponse:
    return await service.place_shadow_order(request)


@router.get("/shadow/positions", response_model=CryptoShadowPositionsResponse, summary="Get shadow positions")
async def get_crypto_shadow_positions(
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoShadowPositionsResponse:
    return await service.get_shadow_positions()


@router.get("/shadow/logs", response_model=CryptoShadowLogsResponse, summary="Get shadow trade logs")
async def get_crypto_shadow_logs(
    limit: int = Query(default=100, ge=1, le=500),
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoShadowLogsResponse:
    return await service.get_shadow_logs(limit=limit)


@router.post("/portfolio/returns", response_model=PortfolioReturnsResponse, summary="Build portfolio return analytics")
async def get_crypto_portfolio_returns(
    request: PortfolioReturnsRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> PortfolioReturnsResponse:
    return await service.build_portfolio_returns(request)


@router.get("/testnet/status", response_model=BinanceTestnetStatusResponse, summary="Get Binance Spot Testnet safety status")
async def get_binance_testnet_status(
    service: CryptoService = Depends(get_crypto_service),
) -> BinanceTestnetStatusResponse:
    return await service.get_testnet_status()


@router.post("/testnet/credentials", response_model=BinanceTestnetActionResponse, summary="Save encrypted Binance Testnet API key")
async def save_binance_testnet_credentials(
    request: BinanceTestnetCredentialsRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> BinanceTestnetActionResponse:
    return await service.save_testnet_credentials(request)


@router.delete("/testnet/credentials", response_model=BinanceTestnetActionResponse, summary="Clear Binance Testnet API key")
async def clear_binance_testnet_credentials(
    service: CryptoService = Depends(get_crypto_service),
) -> BinanceTestnetActionResponse:
    return await service.clear_testnet_credentials()


@router.post("/testnet/enable", response_model=BinanceTestnetActionResponse, summary="Unlock Binance Testnet gate")
async def enable_binance_testnet_orders(
    request: BinanceTestnetEnableRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> BinanceTestnetActionResponse:
    return await service.enable_testnet_orders(request)


@router.post("/testnet/orders", response_model=BinanceTestnetOrderResponse, summary="Dry-run Binance Testnet order")
async def place_binance_testnet_order(
    request: BinanceTestnetOrderRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> BinanceTestnetOrderResponse:
    return await service.place_testnet_order(request)


@router.get("/strategies/templates", response_model=CryptoStrategyTemplatesResponse, summary="List built-in crypto strategies")
async def get_crypto_strategy_templates(
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoStrategyTemplatesResponse:
    return await service.get_strategy_templates()


@router.post("/strategies/run", response_model=CryptoStrategyRunResponse, summary="Run crypto strategy signals")
async def run_crypto_strategies(
    request: CryptoStrategyRunRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoStrategyRunResponse:
    return await service.run_strategies(request)


@router.post("/strategies/backtest", response_model=CryptoStrategyBacktestResponse, summary="Backtest crypto strategies")
async def backtest_crypto_strategies(
    request: CryptoStrategyBacktestRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoStrategyBacktestResponse:
    return await service.backtest_strategies(request)


@router.post("/strategies/walk-forward", response_model=CryptoWalkForwardResponse, summary="Walk-forward backtest crypto strategies")
async def walk_forward_crypto_strategies(
    request: CryptoStrategyWalkForwardRequest,
    service: CryptoService = Depends(get_crypto_service),
) -> CryptoWalkForwardResponse:
    return await service.walk_forward_backtest(request)
