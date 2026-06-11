"""Request models for the crypto-only API."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.crypto_market_data_provider import normalize_crypto_symbol


class BootstrapUserRequest(BaseModel):
    """Create the first local administrator account."""

    username: str = Field(default="owner", min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    """Login request."""

    username: str = Field(default="owner", min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class PreferencesUpdateRequest(BaseModel):
    """Persist user workspace preferences."""

    preferences: dict[str, Any] = Field(default_factory=dict)


class CryptoPaperOrderRequest(BaseModel):
    """Manual crypto paper order request."""

    model_config = ConfigDict(title="Crypto paper order request")

    symbol: str = Field(..., min_length=1, max_length=32, title="Symbol", examples=["BTC/USDT"])
    action: Literal["BUY", "SELL"] = Field(..., title="Action", examples=["BUY"])
    quantity: float = Field(..., gt=0, title="Quantity", examples=[0.001])
    price: float = Field(..., gt=0, title="Price", examples=[65000])
    order_type: Literal["LIMIT"] = Field(default="LIMIT", title="Order type")
    strategy: str = Field(default="crypto_manual", min_length=1, max_length=64, title="Strategy")

    @field_validator("symbol")
    @classmethod
    def normalize_crypto_order_symbol(cls, value: str) -> str:
        normalized = normalize_crypto_symbol(value)
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class CryptoShadowOrderRequest(BaseModel):
    """Shadow trade request; no real or paper account funds are moved."""

    symbol: str = Field(..., min_length=1, max_length=32, examples=["BTC/USDT"])
    action: Literal["BUY", "SELL"] = Field(..., examples=["BUY"])
    quantity: float = Field(..., gt=0)
    strategy_id: str = Field(default="shadow_manual", min_length=1, max_length=64)
    stop_loss_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)

    @field_validator("symbol")
    @classmethod
    def normalize_shadow_symbol(cls, value: str) -> str:
        normalized = normalize_crypto_symbol(value)
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class PortfolioReturnsRequest(BaseModel):
    """Portfolio return analytics request."""

    mode: Literal["live", "demo", "shadow"] = "live"
    range: Literal["7d", "30d", "90d", "all"] = "30d"
    limit: int = Field(default=200, ge=1, le=1000)
    capital_base: float = Field(default=0.0, ge=0)


class AiSignalAnalyzeRequest(BaseModel):
    """Manual AI advisory signal analysis request."""

    symbol: str = Field(..., min_length=1, max_length=32, examples=["BTC/USDT"])
    period: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    limit: int = Field(default=120, ge=30, le=500)

    @field_validator("symbol")
    @classmethod
    def normalize_ai_signal_symbol(cls, value: str) -> str:
        normalized = normalize_crypto_symbol(value)
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class AiChatRequest(BaseModel):
    """Advisory AI chat request."""

    session_id: str | None = Field(default=None, max_length=80)
    message: str = Field(..., min_length=1, max_length=4000)
    model: Literal["deepseek-v4-flash", "deepseek-v4-pro"] | None = Field(default=None)
    symbol: str = Field(default="BTC/USDT", min_length=1, max_length=32, examples=["BTC/USDT"])
    period: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    limit: int = Field(default=120, ge=30, le=500)
    include_context: bool = True
    current_route: str | None = Field(default=None, max_length=128)
    current_module: str | None = Field(default=None, max_length=64)
    current_view_title: str | None = Field(default=None, max_length=80)
    visible_context: dict[str, Any] = Field(default_factory=dict)
    guide_mode: bool = False
    user_goal: str | None = Field(default=None, max_length=300)

    @field_validator("symbol")
    @classmethod
    def normalize_ai_chat_symbol(cls, value: str) -> str:
        normalized = normalize_crypto_symbol(value)
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @field_validator("message")
    @classmethod
    def strip_ai_chat_message(cls, value: str) -> str:
        stripped = str(value or "").strip()
        if not stripped:
            raise ValueError("message is required")
        return stripped

    @field_validator("current_route", "current_module", "current_view_title", "user_goal")
    @classmethod
    def strip_ai_chat_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value or "").strip()
        return stripped or None


class BinanceTestnetCredentialsRequest(BaseModel):
    """Local Binance Spot Testnet credential save request."""

    api_key: str = Field(..., min_length=1, max_length=256)
    api_secret: str = Field(..., min_length=1, max_length=256)


class BinanceTestnetEnableRequest(BaseModel):
    """Unlock Binance Spot Testnet order gate for the current runtime."""

    confirmation_phrase: str = Field(..., min_length=1, max_length=128)


class BinanceTestnetOrderRequest(BaseModel):
    """Dry-run Binance Spot Testnet order request."""

    symbol: str = Field(..., min_length=1, max_length=32, examples=["BTC/USDT"])
    action: Literal["BUY", "SELL"] = Field(..., examples=["BUY"])
    quantity: float = Field(..., gt=0)
    price: float = Field(default=0.0, ge=0)
    order_type: Literal["LIMIT", "MARKET"] = "LIMIT"
    dry_run: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_testnet_order_symbol(cls, value: str) -> str:
        normalized = normalize_crypto_symbol(value)
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class CryptoStrategyConfigRequest(BaseModel):
    """One crypto strategy instance config."""

    strategy_id: str = Field(..., min_length=1, max_length=64, examples=["btc_dual_ma"])
    type: Literal["dual_ma", "rsi", "macd", "bollinger", "momentum"] = Field(..., examples=["dual_ma"])
    symbols: list[str] = Field(default_factory=list, examples=[["BTC/USDT"]])
    weight: float = Field(default=1.0, ge=0, le=10)
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbols")
    @classmethod
    def normalize_strategy_symbols(cls, value: list[str]) -> list[str]:
        return [symbol for symbol in (normalize_crypto_symbol(item) for item in value or []) if symbol]


class AutoTradingConfigRequest(BaseModel):
    """Paper-only automatic trading runtime config."""

    enabled: bool = False
    mode: Literal["paper"] = "paper"
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    period: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    timeframes: list[Literal["1m", "5m", "15m", "1h", "4h", "1d"]] = Field(default_factory=list)
    scan_interval_seconds: int = Field(default=30, ge=5, le=3600)
    max_positions: int = Field(default=3, ge=1, le=20)
    per_trade_position_ratio: float = Field(default=0.1, ge=0.001, le=1)
    max_order_notional: float = Field(default=1000, ge=1)
    min_order_notional: float = Field(default=10, ge=0)
    confidence_threshold: float = Field(default=0.35, ge=0, le=1)
    max_daily_loss: float = Field(default=0, ge=0)
    max_consecutive_losses: int = Field(default=0, ge=0, le=100)
    cooldown_minutes: int = Field(default=30, ge=1, le=1440)
    real_trading_enabled: bool = False
    strategies: list[CryptoStrategyConfigRequest] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def normalize_auto_symbols(cls, value: list[str]) -> list[str]:
        normalized = [symbol for symbol in (normalize_crypto_symbol(item) for item in value or []) if symbol]
        return normalized or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


class CryptoStrategyRunRequest(BaseModel):
    """Run configured crypto strategies against recent K lines."""

    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    period: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    timeframes: list[Literal["1m", "5m", "15m", "1h", "4h", "1d"]] = Field(default_factory=list)
    limit: int = Field(default=240, ge=30, le=1000)
    conflict_threshold: float = Field(default=0.15, ge=0, le=10)
    strategies: list[CryptoStrategyConfigRequest] = Field(default_factory=list)
    max_positions: int = Field(default=2, ge=1, le=10)

    @field_validator("symbols")
    @classmethod
    def normalize_run_symbols(cls, value: list[str]) -> list[str]:
        normalized = [symbol for symbol in (normalize_crypto_symbol(item) for item in value or []) if symbol]
        return normalized or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    @field_validator("timeframes")
    @classmethod
    def normalize_timeframes(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value or []:
            timeframe = str(item or "").strip().lower()
            if timeframe and timeframe not in seen:
                seen.append(timeframe)
        return seen


class CryptoStrategyBacktestRequest(CryptoStrategyRunRequest):
    """Backtest configured crypto strategies independently."""

    initial_cash: float = Field(default=10000, gt=0)
    fee_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    min_quantity: float = Field(default=0.000001, gt=0)
    position_sizing: Literal["strategy_position_ratio"] = "strategy_position_ratio"


class CryptoStrategyWalkForwardRequest(CryptoStrategyRunRequest):
    """Walk-forward backtest with rolling training/validation windows."""

    train_ratio: float = Field(default=0.6, ge=0.3, le=0.8, description="Fraction of each window used for training")
    validation_ratio: float = Field(default=0.2, ge=0.05, le=0.5, description="Fraction of each window used for validation")
    min_train_candles: int = Field(default=50, ge=20, le=500, description="Minimum candles for both train and validation windows")
    step_size: int = Field(default=20, ge=5, le=100, description="Candles to slide each window forward")
    perturbation_runs: int = Field(default=200, ge=0, le=500, description="Number of perturbed initial-capital runs for fragility detection")
    perturbation_pct: float = Field(default=0.025, ge=0, le=0.2)
    initial_cash: float = Field(default=10000, gt=0)
    fee_rate: float = Field(default=0.001, ge=0, le=0.1)
    param_grid: list[dict[str, Any]] | dict[str, list[dict[str, Any]]] = Field(
        default_factory=list,
        description="Custom parameter grid. List applies to every strategy; dict can be keyed by strategy type.",
    )
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.1)
    min_quantity: float = Field(default=0.000001, gt=0)
    position_sizing: Literal["strategy_position_ratio"] = "strategy_position_ratio"
