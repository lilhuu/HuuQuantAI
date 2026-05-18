"""Response models for the crypto-only API."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """Generic API response."""

    success: bool = True
    message: str = "ok"


class HealthCheckResponse(BaseModel):
    """Public health check response."""

    status: str = Field(..., title="Status")
    timestamp: str = Field(..., title="Timestamp")
    api_version: str = Field(..., title="API version")
    trading_system_running: bool = Field(..., title="Trading enabled")
    data_feed_connected: bool = Field(..., title="Data feed available")


class AuthUserResponse(BaseModel):
    """Authenticated local user."""

    user_id: int
    username: str
    display_name: str
    created_at: Optional[str] = None


class AuthStatusResponse(BaseModel):
    """Authentication bootstrap/login status."""

    setup_required: bool
    authenticated: bool
    user: Optional[AuthUserResponse] = None


class AuthSessionResponse(BaseModel):
    """Login session payload."""

    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: AuthUserResponse


class UserPreferencesResponse(BaseModel):
    """User workspace preferences."""

    preferences: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[str] = None


class CryptoQuoteResponse(BaseModel):
    """One cryptocurrency quote."""

    symbol: str
    price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    change: float = 0.0
    change_amount: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    timestamp: Optional[str] = None
    source: str = "ccxt"


class CryptoQuotesResponse(BaseModel):
    """Cryptocurrency quote list."""

    items: list[CryptoQuoteResponse] = Field(default_factory=list)
    count: int = 0
    source: str = "ccxt"


class CryptoKLineResponse(BaseModel):
    """One cryptocurrency OHLCV bar."""

    symbol: str
    period: str
    start_time: str
    end_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0
    count: int = 0


class CryptoKLinesResponse(BaseModel):
    """Cryptocurrency OHLCV list."""

    symbol: str
    period: str
    items: list[CryptoKLineResponse] = Field(default_factory=list)
    count: int = 0
    source: str = "ccxt"


class CryptoOrderBookResponse(BaseModel):
    """Cryptocurrency order book (bid/ask depth)."""

    symbol: str
    bids: list[list[float]] = Field(default_factory=list)
    asks: list[list[float]] = Field(default_factory=list)
    timestamp: Optional[str] = None
    source: str = "ccxt"


class MarketRegimeFeaturesResponse(BaseModel):
    """Raw 7-factor market regime features."""

    trend_strength: float = 0.0
    momentum: float = 0.0
    volume_anomaly: float = 0.0
    orderbook_imbalance: float = 0.0
    funding_overheat: float = 0.0
    volatility_spike: float = 0.0
    oi_change: float = 0.0


class MarketRegimeResponse(BaseModel):
    """Market regime detection response for one symbol."""

    symbol: str = ""
    regime: str = "UNKNOWN"
    score: float = 0.0
    confidence: float = 0.0
    description: str = ""
    features: MarketRegimeFeaturesResponse = Field(default_factory=MarketRegimeFeaturesResponse)
    timestamp: str = ""


class MarketRegimeBatchResponse(BaseModel):
    """Market regime detection response for multiple symbols."""

    items: list[MarketRegimeResponse] = Field(default_factory=list)
    count: int = 0


class MacroDataResponse(BaseModel):
    """Macro data snapshot."""

    timestamp: str = ""
    dxy_price: float = 0.0
    dxy_change_30d_pct: float = 0.0
    dxy_available: bool = False
    m2_latest: float = 0.0
    m2_change_3m_pct: float = 0.0
    m2_available: bool = False
    btc_dominance: float = 0.0
    btc_dom_change_30d_pct: float = 0.0
    btc_dom_available: bool = False
    gold_price: float = 0.0
    gold_change_30d_pct: float = 0.0
    gold_available: bool = False
    spx_price: float = 0.0
    spx_change_30d_pct: float = 0.0
    spx_available: bool = False
    yield_10y: float = 0.0
    yield_2y: float = 0.0
    yield_spread_10y2y: float = 0.0
    yields_available: bool = False


class MacroGateResponse(BaseModel):
    """Macro gate decision."""

    state: str = "ALLOW_FULL"
    score: float = 0.0
    reason: str = ""
    position_size_multiplier: float = 1.0
    max_concurrent_positions: int = 2
    confidence_penalty: float = 0.0
    entry_threshold_adjustment: float = 0.0
    dxy_change_pct: float = 0.0
    m2_change_pct: float = 0.0
    btc_dom_change_pct: float = 0.0
    yield_spread: float = 0.0
    gold_change_pct: float = 0.0
    spx_change_pct: float = 0.0


class MacroOverviewResponse(BaseModel):
    """Macro data and gate overview."""

    data: MacroDataResponse = Field(default_factory=MacroDataResponse)
    gate: MacroGateResponse = Field(default_factory=MacroGateResponse)


class CryptoPaperOrderResponse(BaseModel):
    """Crypto paper order response."""

    order_id: Optional[str] = None
    status: str
    message: str = ""
    symbol: str
    action: str
    quantity: float
    price: float
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0
    realized_pnl: float = 0.0
    strategy: str = "crypto_manual"
    created_time: Optional[str] = None
    filled_time: Optional[str] = None


class CryptoPaperOrdersResponse(BaseModel):
    """Crypto paper order page."""

    items: list[CryptoPaperOrderResponse] = Field(default_factory=list)
    count: int = 0
    total: int = 0
    limit: int = 100
    offset: int = 0


class CryptoPaperPositionResponse(BaseModel):
    """Crypto paper position."""

    symbol: str
    quantity: float = 0.0
    available: float = 0.0
    avg_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    cost_basis: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_percent: float = 0.0


class CryptoPaperPositionsResponse(BaseModel):
    """Crypto paper position list."""

    items: list[CryptoPaperPositionResponse] = Field(default_factory=list)
    count: int = 0
    total_market_value: float = 0.0
    total_unrealized_pnl: float = 0.0


class CryptoPaperAccountResponse(BaseModel):
    """Crypto paper account summary."""

    broker_name: str = "CryptoPaperBroker"
    quote_currency: str = "USDT"
    initial_cash: float = 0.0
    cash: float = 0.0
    available_cash: float = 0.0
    market_value: float = 0.0
    equity: float = 0.0
    total_profit: float = 0.0
    total_return_percent: float = 0.0
    total_trades: int = 0
    total_fee: float = 0.0
    position_count: int = 0
    real_trading_enabled: bool = False


class CryptoPaperEquityPointResponse(BaseModel):
    """One crypto paper equity point."""

    timestamp: str
    cash: float = 0.0
    market_value: float = 0.0
    equity: float = 0.0
    realized_pnl: float = 0.0
    order_id: str = ""
    reason: str = ""


class CryptoPaperEquityCurveResponse(BaseModel):
    """Crypto paper equity curve."""

    items: list[CryptoPaperEquityPointResponse] = Field(default_factory=list)
    count: int = 0


class CryptoPaperLogResponse(BaseModel):
    """One crypto paper runtime log."""

    timestamp: str
    level: str = "INFO"
    event: str = ""
    order_id: str = ""
    symbol: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class CryptoPaperLogsResponse(BaseModel):
    """Crypto paper runtime logs."""

    items: list[CryptoPaperLogResponse] = Field(default_factory=list)
    count: int = 0


class CryptoShadowTradeResponse(BaseModel):
    """Shadow trade simulation report."""

    timestamp: str = ""
    symbol: str = ""
    action: str = ""
    quantity: float = 0.0
    price: float = 0.0
    slippage_pct: float = 0.0
    levels_consumed: int = 0
    remaining_quantity: float = 0.0
    strategy_id: str = ""
    orderbook_available: bool = False


class CryptoShadowPositionResponse(BaseModel):
    """Shadow position tracked outside paper funds."""

    symbol: str = ""
    quantity: float = 0.0
    avg_price: float = 0.0
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    created_at: str = ""
    signal_source: str = ""
    estimated_slippage_pct: float = 0.0
    notional: float = 0.0


class CryptoShadowPositionsResponse(BaseModel):
    """Shadow position list."""

    items: list[CryptoShadowPositionResponse] = Field(default_factory=list)
    count: int = 0


class CryptoShadowLogsResponse(BaseModel):
    """Shadow trade log list."""

    items: list[CryptoShadowTradeResponse] = Field(default_factory=list)
    count: int = 0


class BinanceTestnetStatusResponse(BaseModel):
    """Binance Spot Testnet safety status."""

    exchange: str = "binance"
    network: str = "testnet"
    enabled: bool = False
    base_url: str = ""
    has_api_key: bool = False
    api_key_preview: str = ""
    real_trading_enabled: bool = False
    configured_real_trading_enabled: bool = False
    dry_run: bool = True
    confirmation_required: str = ""
    confirmation_ok: bool = False
    testnet_orders_allowed: bool = False
    mainnet_supported: bool = False
    mainnet_real_trading_enabled: bool = False
    message: str = ""


class BinanceTestnetActionResponse(BinanceTestnetStatusResponse):
    """Binance Testnet credential or gate action response."""

    success: bool = False


class BinanceTestnetOrderResponse(BaseModel):
    """Binance Spot Testnet dry-run order response."""

    client_order_id: str = ""
    status: str = "dry_run"
    message: str = ""
    symbol: str
    action: str
    quantity: float
    price: float = 0.0
    order_type: str = "LIMIT"
    dry_run: bool = True
    created_time: str = ""


class CryptoStrategyTemplateResponse(BaseModel):
    """Built-in crypto strategy template."""

    type: str
    name: str
    description: str = ""
    default_parameters: dict[str, Any] = Field(default_factory=dict)


class CryptoStrategyTemplatesResponse(BaseModel):
    """Built-in strategy template list."""

    items: list[CryptoStrategyTemplateResponse] = Field(default_factory=list)
    count: int = 0


class CryptoStrategySignalResponse(BaseModel):
    """One simulated strategy signal."""

    strategy_id: str
    strategy_name: str
    strategy_type: str
    symbol: str
    timeframe: str = "1h"
    action: str
    price: float = 0.0
    confidence: float = 0.0
    weight: float = 1.0
    weighted_score: float = 0.0
    reason: str = ""
    timestamp: str = ""
    indicators: dict[str, float] = Field(default_factory=dict)
    regime_score: float = 0.0


class CryptoStrategySummaryResponse(BaseModel):
    """Aggregated signal result for one symbol."""

    symbol: str
    action: str
    net_score: float = 0.0
    buy_score: float = 0.0
    sell_score: float = 0.0
    hold_count: int = 0
    conflict: bool = False
    reason: str = ""
    signal_count: int = 0
    source_strategy_ids: list[str] = Field(default_factory=list)
    price: float = 0.0


class CryptoStrategyResultResponse(BaseModel):
    """Signals produced by one configured strategy."""

    strategy_id: str
    strategy_name: str
    strategy_type: str
    enabled: bool = True
    weight: float = 1.0
    symbols: list[str] = Field(default_factory=list)
    signals: list[CryptoStrategySignalResponse] = Field(default_factory=list)


class ConflictResolutionDetailResponse(BaseModel):
    """One conflict-resolution winner or blocked signal."""

    symbol: str = ""
    timeframe: str = ""
    strategy_id: str = ""
    strategy_type: str = ""
    action: str = ""
    reason: str = ""
    confidence: float = 0.0
    score: float = 0.0
    position_multiplier: float = 1.0
    adjusted_position_ratio: float = 0.0


class AuditStepResponse(BaseModel):
    """One decision audit step."""

    stage: str = ""
    verdict: str = ""
    timestamp: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditTrailResponse(BaseModel):
    """Full decision audit trail."""

    trail_id: str = ""
    symbol: str = ""
    timeframe: str = ""
    strategy_id: str = ""
    trigger_time: str = ""
    steps: list[AuditStepResponse] = Field(default_factory=list)
    final_decision: str = ""
    final_reason: str = ""


class CryptoStrategyRunResponse(BaseModel):
    """Multi-strategy run response."""

    signals: list[CryptoStrategySignalResponse] = Field(default_factory=list)
    winners: list[ConflictResolutionDetailResponse] = Field(default_factory=list)
    blocked: list[ConflictResolutionDetailResponse] = Field(default_factory=list)
    audit_trails: list[AuditTrailResponse] = Field(default_factory=list)
    summary: list[CryptoStrategySummaryResponse] = Field(default_factory=list)
    strategy_results: list[CryptoStrategyResultResponse] = Field(default_factory=list)


class ConnectionEndpointHealthResponse(BaseModel):
    """One exchange endpoint circuit-breaker state."""

    state: str = "closed"
    failures: int = 0
    last_failure_at: str = ""


class ConnectionHealthResponse(BaseModel):
    """Exchange connection health response."""

    quotes: ConnectionEndpointHealthResponse = Field(default_factory=ConnectionEndpointHealthResponse)
    ohlcv: ConnectionEndpointHealthResponse = Field(default_factory=ConnectionEndpointHealthResponse)
    orderbook: ConnectionEndpointHealthResponse = Field(default_factory=ConnectionEndpointHealthResponse)


class CryptoStrategyBacktestResultResponse(BaseModel):
    """Independent backtest result for one strategy."""

    strategy_id: str
    strategy_name: str
    strategy_type: str
    symbols: list[str] = Field(default_factory=list)
    quote_currency: str = "USDT"
    period: str = "1h"
    initial_cash: float = 0.0
    final_equity: float = 0.0
    total_return_percent: float = 0.0
    max_drawdown_percent: float = 0.0
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    signal_count: int = 0
    trade_count: int = 0
    trades: list[dict[str, Any]] = Field(default_factory=list)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    drawdown_curve: list[dict[str, Any]] = Field(default_factory=list)
    fee_rate: float = 0.0
    slippage_rate: float = 0.0
    min_quantity: float = 0.000001
    position_sizing: str = "strategy_position_ratio"
    message: str = "ok"


class CryptoStrategyBacktestResponse(BaseModel):
    """Independent backtest results for configured strategies."""

    items: list[CryptoStrategyBacktestResultResponse] = Field(default_factory=list)
    count: int = 0


# ---------------------------------------------------------------------------
# Walk-forward backtest response models
# ---------------------------------------------------------------------------

class WalkForwardRoundResponse(BaseModel):
    """One walk-forward window result."""

    round_index: int = 0
    strategy_id: str = ""
    strategy_type: str = ""
    symbol: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    train_start: str = ""
    train_end: str = ""
    validation_start: str = ""
    validation_end: str = ""
    selection_score: float = 0.0
    is_fragile: bool = False
    train_result: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    perturbation_summary: dict[str, Any] | None = None


class WalkForwardStrategySummaryResponse(BaseModel):
    """Aggregated walk-forward metrics for one strategy."""

    strategy_id: str = ""
    strategy_type: str = ""
    round_count: int = 0
    fragile_count: int = 0
    avg_train_return_percent: float = 0.0
    avg_validation_return_percent: float = 0.0
    median_validation_return_percent: float = 0.0
    worst_validation_return_percent: float = 0.0
    total_validation_trades: int = 0


class WalkForwardSymbolSummaryResponse(BaseModel):
    """Aggregated walk-forward metrics for one symbol."""

    symbol: str = ""
    round_count: int = 0
    avg_validation_return_percent: float = 0.0
    median_validation_return_percent: float = 0.0


class WalkForwardConfigResponse(BaseModel):
    """Walk-forward config used."""

    train_ratio: float = 0.6
    validation_ratio: float = 0.2
    step_size: int = 20
    perturbation_runs: int = 200
    min_train_candles: int = 50
    initial_cash: float = 10000.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    min_quantity: float = 0.000001
    period: str = "1h"


class CryptoWalkForwardResponse(BaseModel):
    """Walk-forward backtest response."""

    rounds: list[WalkForwardRoundResponse] = Field(default_factory=list)
    by_strategy: list[WalkForwardStrategySummaryResponse] = Field(default_factory=list)
    by_symbol: list[WalkForwardSymbolSummaryResponse] = Field(default_factory=list)
    factor_audit: dict[str, Any] = Field(default_factory=dict)
    config: WalkForwardConfigResponse | None = None
