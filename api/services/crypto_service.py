"""Crypto market data and paper-trading service."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import os
import time
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from starlette.concurrency import iterate_in_threadpool

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
    AiChatMessageResponse,
    AiChatResponse,
    AiChatSessionDetailResponse,
    AiChatSessionListResponse,
    AiChatSessionResponse,
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
    CryptoKLineResponse,
    CryptoKLinesResponse,
    CryptoOrderBookResponse,
    CryptoDerivativeMetricsResponse,
    CryptoPaperAccountResponse,
    CryptoPaperEquityCurveResponse,
    CryptoPaperEquityPointResponse,
    CryptoPaperLogResponse,
    CryptoPaperLogsResponse,
    CryptoPaperOrderResponse,
    CryptoPaperOrdersResponse,
    CryptoPaperPositionResponse,
    CryptoPaperPositionsResponse,
    CryptoShadowLogsResponse,
    CryptoShadowPositionsResponse,
    CryptoShadowTradeResponse,
    CryptoQuoteResponse,
    CryptoQuotesResponse,
    CryptoSymbolInfoResponse,
    CryptoSymbolListResponse,
    CryptoStrategyBacktestResponse,
    CryptoStrategyBacktestResultResponse,
    ConflictResolutionDetailResponse,
    CryptoStrategyResultResponse,
    CryptoStrategyRunResponse,
    CryptoStrategySignalResponse,
    CryptoStrategySummaryResponse,
    CryptoStrategyTemplateResponse,
    CryptoStrategyTemplatesResponse,
    CryptoWalkForwardResponse,
    MacroOverviewResponse,
    MarketRegimeResponse,
    MarketRegimeBatchResponse,
    PortfolioReturnsResponse,
    WalkForwardRoundResponse,
    WalkForwardStrategySummaryResponse,
    WalkForwardSymbolSummaryResponse,
    WalkForwardConfigResponse,
)
from core.ai_chat_assistant import AiChatAssistant, AiChatStore, ProjectAssistantContextBuilder
from core.ai_signal_advisor import (
    AiAdvisorConfig,
    AiSignalAdvisor,
    AiSignalContextBuilder,
    AiSignalStore,
    validate_ai_advice,
)
from core.ai_paper_supervisor import AiPaperSupervisorRuntime
from core.auto_trading_engine import AutoTradingEngine
from core.binance_testnet_executor import BinanceTestnetExecutor
from core.audit_trail import AuditLogger, AuditSQLiteStore, AuditStage, AuditVerdict
from core.crypto_market_cache import CryptoMarketCache
from core.binance_public_market_provider import (
    BinancePublicMarketProvider,
    normalize_instrument_symbol,
    normalize_market_type,
)
from core.crypto_market_data_provider import CryptoMarketDataProvider, normalize_crypto_symbol
from core.crypto_paper_broker import CryptoPaperBrokerExecutor
from core.crypto_backtest_engine import CryptoBacktestEngine
from core.crypto_strategy_engine import CryptoStrategyEngine
from core.macro_data_provider import MacroDataProvider
from core.macro_risk import MacroRiskEvaluator
from core.portfolio_returns import build_portfolio_return_analytics
from core.regime_detector import RegimeDetector
from core.shadow_trading import ShadowTradingEngine
from core.walk_forward_backtest import WalkForwardConfig, WalkForwardRunner


class CryptoService:
    """Facade for crypto public data and local paper trading."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        crypto_config = self.config.get("crypto", {}) or {}
        self.crypto_config = crypto_config
        default_symbols = [
            normalize_crypto_symbol(symbol, crypto_config.get("default_quote_currency", "USDT"))
            for symbol in crypto_config.get("symbols", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        ]
        self.default_symbols = list(dict.fromkeys(symbol for symbol in default_symbols if symbol))
        provider_config = {
            "exchange": crypto_config.get("exchange", "binance"),
            "timeout": crypto_config.get("timeout", 10000),
            "default_quote_currency": crypto_config.get("default_quote_currency", "USDT"),
            "proxy": crypto_config.get("proxy", "") or "",
        }
        self.provider = CryptoMarketDataProvider(provider_config)
        self.public_provider = BinancePublicMarketProvider(
            {
                "timeout": crypto_config.get("timeout", 10000) / 1000
                if int(crypto_config.get("timeout", 10000) or 10000) > 100
                else crypto_config.get("timeout", 10),
            }
        )
        storage_config = self.config.get("storage", {}) or {}
        sqlite_storage_path = storage_config.get("db_path") or "data/trading.db"
        self.market_cache = CryptoMarketCache(
            storage_config.get("crypto_market_db_path") or sqlite_storage_path
        )
        paper_config = {
            "default_quote_currency": crypto_config.get("default_quote_currency", "USDT"),
            "storage_path": storage_config.get("crypto_paper_db_path") or sqlite_storage_path,
            **(crypto_config.get("paper", {}) or {}),
        }
        self.paper_broker = CryptoPaperBrokerExecutor(paper_config)
        self.audit_logger = AuditLogger(AuditSQLiteStore(storage_config.get("audit_db_path") or sqlite_storage_path))
        self.shadow_engine = ShadowTradingEngine(
            self.provider,
            storage_path=storage_config.get("shadow_db_path") or sqlite_storage_path,
        )
        testnet_config = dict(crypto_config.get("testnet", {}) or {})
        mainnet_config = dict(crypto_config.get("mainnet", {}) or {})
        testnet_config["mainnet_real_trading_enabled"] = bool(mainnet_config.get("real_trading_enabled", False))
        self.testnet_executor = BinanceTestnetExecutor(testnet_config, storage_config)
        self.strategy_engine = CryptoStrategyEngine()
        auto_config = dict(self.config.get("auto_trading", {}) or crypto_config.get("auto_trading", {}) or {})
        if "symbols" not in auto_config:
            auto_config["symbols"] = self.default_symbols
        risk_config = self.config.get("risk", {}) or {}
        auto_config.setdefault("max_order_notional", risk_config.get("max_order_notional", 1000))
        self.auto_trading_engine = AutoTradingEngine(auto_config)
        self.ai_supervisor = AiPaperSupervisorRuntime(max_provider_failures=3)
        macro_config = dict(crypto_config.get("macro", {}) or {})
        self.macro_provider = MacroDataProvider(
            fred_api_key=os.environ.get("FRED_API_KEY") or macro_config.get("fred_api_key")
        )
        self.macro_evaluator = MacroRiskEvaluator(macro_config)
        self.regime_detector_config = dict(crypto_config.get("regime", {}) or {})
        self._macro_cache: MacroOverviewResponse | None = None
        self._macro_cache_time = 0.0
        self.ai_config = AiAdvisorConfig.from_dict(self.config.get("ai", {}) or {})
        self.ai_advisor = AiSignalAdvisor(self.ai_config)
        self.ai_store = AiSignalStore(storage_config.get("ai_signals_db_path") or sqlite_storage_path)
        self.ai_chat_assistant = AiChatAssistant(self.ai_config)
        self.ai_chat_store = AiChatStore(storage_config.get("ai_chat_db_path") or sqlite_storage_path)
        self._auto_scan_lock = asyncio.Lock()
        self._auto_loop_task: asyncio.Task | None = None
        self._auto_loop_consecutive_errors = 0
        self._protective_loop_task: asyncio.Task | None = None
        self._protective_interval_seconds = max(
            0.1,
            float(paper_config.get("tpsl_check_interval_seconds", 5) or 5),
        )
        self._sync_ai_supervisor_status()

    async def get_quotes(
        self,
        symbols: Optional[list[str]] = None,
        search: str | None = None,
        quote: str | None = None,
        limit: int = 0,
        offset: int = 0,
        market_type: str = "spot",
    ) -> CryptoQuotesResponse:
        normalized_market_type = self._normalize_market_type(market_type)
        if normalized_market_type != "spot":
            return await self._get_public_market_quotes(
                normalized_market_type,
                symbols=symbols,
                search=search,
                quote=quote,
                limit=limit,
                offset=offset,
            )
        target_symbols = self._normalize_symbols(symbols) if symbols is not None else None
        quote_filter = self._normalize_quote_filter(quote)
        if target_symbols is not None and len(target_symbols) == 0:
            return CryptoQuotesResponse(items=[], count=0, source="ccxt")

        try:
            if target_symbols:
                rows = self.provider.fetch_quotes(target_symbols)
            else:
                rows = self.provider.fetch_all_tickers(quote=quote_filter)
            self.record_quote_snapshots(rows)
        except Exception as exc:
            if target_symbols:
                cached_rows = self.market_cache.get_quotes(target_symbols)
                if cached_rows:
                    items = [CryptoQuoteResponse(**row) for row in cached_rows]
                    return CryptoQuotesResponse(items=items, count=len(items), source="cache_binance")
            else:
                cached_rows, total = self.market_cache.get_quote_page(
                    quote=quote_filter,
                    search=search,
                    limit=limit,
                    offset=offset,
                )
                if cached_rows:
                    safe_offset = max(int(offset or 0), 0)
                    safe_limit = max(int(limit or 0), 0)
                    items = [CryptoQuoteResponse(**row) for row in cached_rows]
                    return CryptoQuotesResponse(
                        items=items,
                        count=len(items),
                        total=total,
                        limit=safe_limit,
                        offset=safe_offset,
                        source="cache_binance",
                    )
            raise ApiError(
                503,
                f"Crypto market data source unavailable and no local cache is available: {exc}",
                ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

        if search:
            search_upper = search.strip().upper()
            rows = [r for r in rows if search_upper in str(r.get("symbol", "")).upper() or search_upper in str(r.get("symbol", "")).upper()]

        total = len(rows)
        safe_offset = max(int(offset or 0), 0)
        safe_limit = max(int(limit or 0), 0)
        if safe_limit > 0:
            rows = rows[safe_offset : safe_offset + safe_limit]

        items = [CryptoQuoteResponse(**row) for row in rows]
        source = rows[0].get("source", "ccxt") if rows else "ccxt"
        return CryptoQuotesResponse(
            items=items,
            count=len(items),
            total=total,
            limit=safe_limit,
            offset=safe_offset,
            source=str(source),
        )

    async def get_available_symbols(
        self,
        quote: str | None = None,
        search: str | None = None,
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
        market_type: str = "spot",
    ) -> CryptoSymbolListResponse:
        normalized_market_type = self._normalize_market_type(market_type)
        if normalized_market_type != "spot":
            return await self._get_public_market_symbols(
                normalized_market_type,
                quote=quote,
                search=search,
                status=status,
                limit=limit,
                offset=offset,
            )
        quote_filter = self._normalize_quote_filter(quote)
        items, total = self.market_cache.get_symbols(
            quote=quote_filter, search=search, status=status, limit=limit, offset=offset
        )
        should_refresh_markets = total == 0 or str(quote or "").strip().upper() == "ALL"
        if should_refresh_markets:
            try:
                markets = await asyncio.get_event_loop().run_in_executor(
                    None, self.provider.load_markets, False
                )
            except Exception:
                try:
                    markets = self.provider.load_markets(reload=False)
                except Exception:
                    markets = {}
            if markets:
                self.market_cache.upsert_exchange_info(markets)
                items, total = self.market_cache.get_symbols(
                    quote=quote_filter, search=search, status=status, limit=limit, offset=offset
                )
        return CryptoSymbolListResponse(
            items=[CryptoSymbolInfoResponse(**item) for item in items],
            count=len(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_klines(self, symbol: str, period: str = "1h", limit: int = 200, market_type: str = "spot") -> CryptoKLinesResponse:
        normalized_market_type = self._normalize_market_type(market_type)
        if normalized_market_type != "spot":
            normalized_symbol = normalize_instrument_symbol(symbol, normalized_market_type)
            if not normalized_symbol:
                raise ApiError(400, "symbol is required", ErrorCode.BAD_REQUEST)
            try:
                rows = self.public_provider.fetch_klines(normalized_market_type, normalized_symbol, period=period, limit=limit)
            except ValueError as exc:
                raise ApiError(400, str(exc), ErrorCode.BAD_REQUEST) from exc
            except Exception as exc:
                raise ApiError(
                    503,
                    f"Binance public market data source unavailable: {exc}",
                    ErrorCode.INTERNAL_SERVER_ERROR,
                ) from exc
            items = [CryptoKLineResponse(**row) for row in rows]
            response_period = items[0].period if items else str(period)
            return CryptoKLinesResponse(
                symbol=normalized_symbol,
                period=response_period,
                items=items,
                count=len(items),
                source=f"binance_{normalized_market_type}",
            )
        normalized_symbol = normalize_crypto_symbol(symbol, self.crypto_config.get("default_quote_currency", "USDT"))
        if not normalized_symbol:
            raise ApiError(400, "symbol is required", ErrorCode.BAD_REQUEST)
        try:
            rows = self.provider.fetch_ohlcv(normalized_symbol, timeframe=period, limit=limit)
            self.record_klines(rows)
        except ValueError as exc:
            raise ApiError(400, str(exc), ErrorCode.BAD_REQUEST) from exc
        except Exception as exc:
            cached_rows = self.market_cache.get_klines(normalized_symbol, str(period or "1h"), limit=limit)
            if cached_rows:
                items = [CryptoKLineResponse(**row) for row in cached_rows]
                response_period = items[0].period if items else str(period)
                return CryptoKLinesResponse(
                    symbol=normalized_symbol,
                    period=response_period,
                    items=items,
                    count=len(items),
                    source="cache_binance",
                )
            raise ApiError(
                503,
                f"Crypto market data source unavailable and no local cache is available: {exc}",
                ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc
        items = [CryptoKLineResponse(**row) for row in rows]
        response_period = items[0].period if items else str(period)
        return CryptoKLinesResponse(
            symbol=normalized_symbol,
            period=response_period,
            items=items,
            count=len(items),
            source=str(self.crypto_config.get("exchange", "binance")),
        )

    async def get_orderbook(self, symbol: str, limit: int = 20, market_type: str = "spot") -> CryptoOrderBookResponse:
        """Fetch current order book depth for a symbol."""
        normalized_market_type = self._normalize_market_type(market_type)
        if normalized_market_type != "spot":
            normalized_symbol = normalize_instrument_symbol(symbol, normalized_market_type)
            if not normalized_symbol:
                raise ApiError(400, "symbol is required", ErrorCode.BAD_REQUEST)
            try:
                book = self.public_provider.fetch_order_book(normalized_market_type, normalized_symbol, limit=limit)
            except ValueError as exc:
                raise ApiError(400, str(exc), ErrorCode.BAD_REQUEST) from exc
            except Exception as exc:
                raise ApiError(
                    503,
                    f"Binance public market data source unavailable: {exc}",
                    ErrorCode.INTERNAL_SERVER_ERROR,
                ) from exc
            return CryptoOrderBookResponse(**book)
        normalized_symbol = normalize_crypto_symbol(symbol, self.crypto_config.get("default_quote_currency", "USDT"))
        if not normalized_symbol:
            raise ApiError(400, "symbol is required", ErrorCode.BAD_REQUEST)
        try:
            book = self.provider.fetch_order_book(normalized_symbol, limit=limit)
        except ValueError as exc:
            raise ApiError(400, str(exc), ErrorCode.BAD_REQUEST) from exc
        except Exception as exc:
            raise ApiError(
                503,
                f"Crypto market data source unavailable: {exc}",
                ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc
        return CryptoOrderBookResponse(**book)

    async def get_derivative_metrics(self, market_type: str, symbol: str) -> CryptoDerivativeMetricsResponse:
        normalized_market_type = self._normalize_market_type(market_type)
        normalized_symbol = normalize_instrument_symbol(symbol, normalized_market_type)
        if not normalized_symbol:
            raise ApiError(400, "symbol is required", ErrorCode.BAD_REQUEST)
        try:
            metrics = self.public_provider.fetch_derivative_metrics(normalized_market_type, normalized_symbol)
        except ValueError as exc:
            raise ApiError(400, str(exc), ErrorCode.BAD_REQUEST) from exc
        except Exception as exc:
            raise ApiError(
                503,
                f"Binance derivative metrics source unavailable: {exc}",
                ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc
        return CryptoDerivativeMetricsResponse(**metrics)

    async def _get_public_market_quotes(
        self,
        market_type: str,
        symbols: Optional[list[str]] = None,
        search: str | None = None,
        quote: str | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> CryptoQuotesResponse:
        target_symbols = (
            [normalize_instrument_symbol(symbol, market_type) for symbol in symbols]
            if symbols is not None
            else None
        )
        target_symbols = [symbol for symbol in (target_symbols or []) if symbol] if target_symbols is not None else None
        quote_filter = self._normalize_quote_filter(quote)
        if target_symbols is not None and len(target_symbols) == 0:
            return CryptoQuotesResponse(items=[], count=0, source=f"binance_{market_type}")
        try:
            rows = (
                self.public_provider.fetch_quotes(market_type, target_symbols)
                if target_symbols
                else self.public_provider.fetch_all_tickers(market_type, quote=quote_filter)
            )
            self.market_cache.upsert_market_quotes(rows, market_type=market_type)
        except Exception as exc:
            if target_symbols:
                cached_rows = self.market_cache.get_market_quotes(target_symbols, market_type=market_type)
                if cached_rows:
                    items = [CryptoQuoteResponse(**row) for row in cached_rows]
                    return CryptoQuotesResponse(items=items, count=len(items), source=f"cache_binance_{market_type}")
            else:
                cached_rows, total = self.market_cache.get_market_quote_page(
                    market_type=market_type,
                    quote=quote_filter,
                    search=search,
                    limit=limit,
                    offset=offset,
                )
                if cached_rows:
                    safe_offset = max(int(offset or 0), 0)
                    safe_limit = max(int(limit or 0), 0)
                    items = [CryptoQuoteResponse(**row) for row in cached_rows]
                    return CryptoQuotesResponse(
                        items=items,
                        count=len(items),
                        total=total,
                        limit=safe_limit,
                        offset=safe_offset,
                        source=f"cache_binance_{market_type}",
                    )
            raise ApiError(
                503,
                f"Binance public market data source unavailable and no local cache is available: {exc}",
                ErrorCode.INTERNAL_SERVER_ERROR,
            ) from exc

        if search:
            search_upper = search.strip().upper()
            rows = [
                row
                for row in rows
                if search_upper in str(row.get("symbol", "")).upper()
                or search_upper in str(row.get("base", "")).upper()
                or search_upper in str(row.get("quote", "")).upper()
            ]
        total = len(rows)
        safe_offset = max(int(offset or 0), 0)
        safe_limit = max(int(limit or 0), 0)
        if safe_limit > 0:
            rows = rows[safe_offset : safe_offset + safe_limit]
        items = [CryptoQuoteResponse(**row) for row in rows]
        return CryptoQuotesResponse(
            items=items,
            count=len(items),
            total=total,
            limit=safe_limit,
            offset=safe_offset,
            source=f"binance_{market_type}",
        )

    async def _get_public_market_symbols(
        self,
        market_type: str,
        quote: str | None = None,
        search: str | None = None,
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> CryptoSymbolListResponse:
        quote_filter = self._normalize_quote_filter(quote)
        items, total = self.market_cache.get_instruments(
            market_type=market_type,
            quote=quote_filter,
            search=search,
            status=status,
            limit=limit,
            offset=offset,
        )
        if total == 0 or str(quote or "").strip().upper() == "ALL":
            try:
                markets = await asyncio.get_event_loop().run_in_executor(
                    None, self.public_provider.load_markets, market_type
                )
            except Exception:
                try:
                    markets = self.public_provider.load_markets(market_type)
                except Exception:
                    markets = []
            if markets:
                self.market_cache.upsert_instruments(markets, market_type=market_type)
                items, total = self.market_cache.get_instruments(
                    market_type=market_type,
                    quote=quote_filter,
                    search=search,
                    status=status,
                    limit=limit,
                    offset=offset,
                )
        return CryptoSymbolListResponse(
            items=[CryptoSymbolInfoResponse(**item) for item in items],
            count=len(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def detect_market_regime(
        self,
        symbols: list[str],
        period: str = "1h",
        limit: int = 100,
    ) -> MarketRegimeBatchResponse:
        """Detect the market regime for one or more crypto symbols."""
        detector = RegimeDetector(config=self.regime_detector_config)
        items: list[MarketRegimeResponse] = []
        market_data = await self._load_strategy_market_data(symbols, period, limit)

        for symbol, candles in market_data.items():
            closes = [float(row.get("close", 0) or 0) for row in candles]
            highs = [float(row.get("high", 0) or 0) for row in candles]
            lows = [float(row.get("low", 0) or 0) for row in candles]
            volumes = [float(row.get("volume", 0) or 0) for row in candles]

            funding_rate = None
            orderbook_bid_depth = None
            orderbook_ask_depth = None
            open_interest_current = None

            try:
                funding = self.provider.fetch_funding_rate(symbol)
                if funding:
                    funding_rate = float(funding.get("funding_rate", 0) or 0)
            except Exception:
                funding_rate = None

            try:
                open_interest = self.provider.fetch_open_interest(symbol)
                if open_interest:
                    open_interest_current = float(open_interest.get("open_interest", 0) or 0)
            except Exception:
                open_interest_current = None

            try:
                orderbook = self.provider.fetch_order_book(symbol, limit=5)
                if orderbook:
                    orderbook_bid_depth = sum(float(level[1] or 0) for level in (orderbook.get("bids") or [])[:5])
                    orderbook_ask_depth = sum(float(level[1] or 0) for level in (orderbook.get("asks") or [])[:5])
            except Exception:
                orderbook_bid_depth = None
                orderbook_ask_depth = None

            result = detector.detect(
                closes=closes,
                highs=highs,
                lows=lows,
                volumes=volumes,
                funding_rate=funding_rate,
                orderbook_bid_depth=orderbook_bid_depth,
                orderbook_ask_depth=orderbook_ask_depth,
                open_interest_current=open_interest_current,
                open_interest_previous=None,
                symbol=symbol,
            )
            items.append(
                MarketRegimeResponse(
                    symbol=symbol,
                    regime=result.regime.value,
                    score=result.score,
                    confidence=result.confidence,
                    description=result.description,
                    features=asdict(result.features),
                    timestamp=str(candles[-1].get("end_time") or candles[-1].get("start_time") or "") if candles else "",
                )
            )
        return MarketRegimeBatchResponse(items=items, count=len(items))

    async def get_macro_overview(self) -> MacroOverviewResponse:
        """Get macro data and the current three-level macro gate."""
        now = time.time()
        if self._macro_cache is not None and now - self._macro_cache_time < 300:
            return self._macro_cache

        snapshot = self.macro_provider.fetch_snapshot()
        gate = self.macro_evaluator.evaluate(snapshot)
        response = MacroOverviewResponse(data=snapshot.to_dict(), gate=gate.to_dict())
        self._macro_cache = response
        self._macro_cache_time = now
        return response

    async def place_paper_order(self, request: CryptoPaperOrderRequest) -> CryptoPaperOrderResponse:
        order = self.paper_broker.place_order(
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            price=request.price,
            strategy=request.strategy,
            order_type=request.order_type,
        )
        return CryptoPaperOrderResponse(**order.to_response())

    async def get_paper_orders(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> CryptoPaperOrdersResponse:
        page = self.paper_broker.get_orders(status=status, limit=limit, offset=offset)
        return CryptoPaperOrdersResponse(
            items=[CryptoPaperOrderResponse(**item) for item in page["items"]],
            count=page["count"],
            total=page["total"],
            limit=page["limit"],
            offset=page["offset"],
        )

    async def cancel_paper_order(self, order_id: str) -> dict[str, Any]:
        success = self.paper_broker.cancel_order(order_id)
        return {
            "success": success,
            "message": "crypto paper order cancelled" if success else "crypto paper order cannot be cancelled",
        }

    async def get_paper_account(self) -> CryptoPaperAccountResponse:
        await self._refresh_paper_marks()
        account = self.paper_broker.get_account_info()
        return CryptoPaperAccountResponse(
            broker_name=str(account.get("broker_name", "CryptoPaperBroker")),
            quote_currency=str(account.get("quote_currency", "USDT")),
            initial_cash=float(account.get("initial_cash", 0) or 0),
            cash=float(account.get("cash", 0) or 0),
            available_cash=float(account.get("available_cash", 0) or 0),
            market_value=float(account.get("market_value", 0) or 0),
            equity=float(account.get("equity", 0) or 0),
            total_profit=float(account.get("total_profit", 0) or 0),
            total_return_percent=float(account.get("total_return_percent", 0) or 0),
            total_trades=int(account.get("total_trades", 0) or 0),
            total_fee=float(account.get("total_fee", 0) or 0),
            position_count=len(account.get("positions", []) or []),
            real_trading_enabled=bool(account.get("real_trading_enabled", False)),
        )

    async def get_paper_positions(self) -> CryptoPaperPositionsResponse:
        await self._refresh_paper_marks()
        positions = self.paper_broker.get_positions()
        items = [CryptoPaperPositionResponse(**position) for position in positions]
        return CryptoPaperPositionsResponse(
            items=items,
            count=len(items),
            total_market_value=sum(float(item.market_value or 0) for item in items),
            total_unrealized_pnl=sum(float(item.unrealized_pnl or 0) for item in items),
        )

    async def get_paper_equity_curve(self, limit: int = 200) -> CryptoPaperEquityCurveResponse:
        await self._refresh_paper_marks(record_equity=True)
        points = [CryptoPaperEquityPointResponse(**item) for item in self.paper_broker.get_equity_curve(limit)]
        return CryptoPaperEquityCurveResponse(items=points, count=len(points))

    async def get_paper_logs(self, limit: int = 100) -> CryptoPaperLogsResponse:
        logs = [CryptoPaperLogResponse(**item) for item in self.paper_broker.get_paper_logs(limit)]
        return CryptoPaperLogsResponse(items=logs, count=len(logs))

    async def _refresh_paper_marks(self, *, record_equity: bool = False, require_complete: bool = False) -> None:
        symbols = [
            symbol
            for symbol, position in self.paper_broker.positions.items()
            if float(position.get("quantity", 0) or 0) > 0
        ]
        if not symbols:
            return

        if not require_complete:
            cached_rows = self.market_cache.get_quotes(symbols)
            self.paper_broker.mark_to_market(
                {str(row.get("symbol") or ""): row.get("price") for row in cached_rows},
                record_equity=record_equity,
            )
            return

        quotes = await self.get_quotes(symbols)
        if str(getattr(quotes, "source", "")).startswith("cache"):
            raise ApiError(
                503,
                "Current paper-position mark prices are unavailable; automatic trading is skipped for this cycle",
                ErrorCode.INTERNAL_SERVER_ERROR,
            )
        mark_prices = {
            normalize_crypto_symbol(item.symbol, self.paper_broker.quote_currency): float(item.price or 0)
            for item in quotes.items
            if float(item.price or 0) > 0
        }
        missing = [symbol for symbol in symbols if symbol not in mark_prices]
        if require_complete and missing:
            raise ApiError(
                503,
                f"Paper account mark prices unavailable for: {', '.join(missing)}",
                ErrorCode.INTERNAL_SERVER_ERROR,
            )
        self.paper_broker.mark_to_market(mark_prices, record_equity=record_equity)

    async def get_auto_trading_status(self) -> AutoTradingStatusResponse:
        self._ensure_protective_loop()
        return self._auto_status_response()

    async def update_auto_trading_config(self, request: AutoTradingConfigRequest) -> AutoTradingStatusResponse:
        self.auto_trading_engine.update_config(request.model_dump())
        return self._auto_status_response()

    async def start_auto_trading(self) -> AutoTradingStatusResponse:
        if self.auto_trading_engine.config.decision_mode == "ai_supervised":
            start_error = self._ai_supervisor_start_error()
            if start_error:
                self.auto_trading_engine.block(start_error, "ai_supervisor_start_blocked")
                return self._auto_status_response()
        status = self.auto_trading_engine.start()
        if status.get("state") == "running":
            self._ensure_auto_loop()
        self._ensure_protective_loop()
        return self._auto_status_response()

    async def pause_auto_trading(self) -> AutoTradingStatusResponse:
        self.auto_trading_engine.pause()
        await self._stop_auto_loop()
        self._ensure_protective_loop()
        return self._auto_status_response()

    async def stop_auto_trading(self) -> AutoTradingStatusResponse:
        self.auto_trading_engine.stop()
        await self._stop_auto_loop()
        self._ensure_protective_loop()
        return self._auto_status_response()

    async def run_auto_trading_cycle(self) -> AutoTradingStatusResponse:
        """Run one automatic strategy scan and paper-order pass."""
        if self._auto_scan_lock.locked():
            self.auto_trading_engine._log(
                "WARNING",
                "scan_skipped_locked",
                "auto trading scan skipped because another scan is running",
            )
            return self._auto_status_response()

        async with self._auto_scan_lock:
            return await self._run_auto_trading_cycle_locked()

    async def _run_auto_trading_cycle_locked(self) -> AutoTradingStatusResponse:
        """Run one scan while the caller holds the scan lock."""
        config = self.auto_trading_engine.config
        place_orders = self.auto_trading_engine.state == "running" and config.enabled
        try:
            if config.decision_mode == "ai_supervised" and place_orders:
                await self._process_ai_protective_exits()
            await self._refresh_paper_marks(record_equity=True, require_complete=True)
            run_request = CryptoStrategyRunRequest(
                symbols=config.symbols,
                period=config.period,
                timeframes=config.timeframes,
                limit=240,
                conflict_threshold=0.15,
                strategies=config.strategies,
                max_positions=config.max_positions,
            )
            strategy_result = await self.run_strategies(run_request)
            account = self.paper_broker.get_account_info()
            positions = self.paper_broker.get_positions()
            if config.decision_mode == "ai_supervised":
                return await self._run_ai_supervised_cycle(
                    strategy_result.model_dump(),
                    account,
                    positions,
                    place_orders=place_orders,
                )
            decisions = self.auto_trading_engine.build_order_decisions(
                strategy_result.model_dump(),
                account,
                positions,
                place_orders=place_orders,
            )
            for decision in decisions:
                if decision.get("status") != "ready":
                    continue
                order = self.paper_broker.place_order(
                    symbol=decision["symbol"],
                    action=decision["action"],
                    quantity=float(decision["quantity"]),
                    price=float(decision["price"]),
                    strategy=f"auto:{decision['strategy_id']}",
                    order_type="LIMIT",
                )
                self.auto_trading_engine.record_order_result(decision, order.to_response())
            self.auto_trading_engine.last_error_type = ""
            return self._auto_status_response()
        except ApiError as exc:
            error_code = ""
            if isinstance(exc.detail, dict):
                error_code = str(exc.detail.get("error_code") or "")
            self.auto_trading_engine.record_error(
                str(exc.detail.get("message") if isinstance(exc.detail, dict) else exc),
                {"type": exc.__class__.__name__, "error_code": error_code},
            )
            return self._auto_status_response()
        except Exception as exc:
            self.auto_trading_engine.record_error(str(exc), {"type": exc.__class__.__name__})
            return self._auto_status_response()

    async def _run_ai_supervised_cycle(
        self,
        strategy_payload: dict[str, Any],
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        *,
        place_orders: bool,
    ) -> AutoTradingStatusResponse:
        config = self.auto_trading_engine.config
        candidates = self.auto_trading_engine._candidates(strategy_payload)
        ai_candidates: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        signal_by_strategy_id: dict[str, str] = {}

        for candidate in candidates:
            symbol = normalize_crypto_symbol(candidate.get("symbol") or "")
            if not symbol:
                continue
            candle_time = await self._latest_ai_candle_time(symbol, config.period)
            if config.ai_on_new_candle_only and not self.ai_supervisor.should_evaluate(symbol, candle_time):
                skipped.append(self._ai_skipped_decision(symbol, candidate, "already evaluated this closed candle"))
                continue

            self.ai_supervisor.record_attempt(symbol, candle_time)

            try:
                response = await self.analyze_ai_signal(
                    AiSignalAnalyzeRequest(
                        symbol=symbol,
                        period=config.period,
                        limit=120,
                        model=config.ai_model,
                    ),
                    strategy_candidate=candidate,
                    execution_mode="auto_paper",
                    fallback_model=config.ai_fallback_model,
                )
            except Exception as exc:
                reason = str(exc)
                should_block = self.ai_supervisor.record_provider_failure(reason)
                skipped.append(self._ai_skipped_decision(symbol, candidate, f"AI provider unavailable: {reason}"))
                self.auto_trading_engine._log(
                    "ERROR",
                    "ai_supervisor_provider_failed",
                    reason,
                    {"symbol": symbol, "failures": self.ai_supervisor.provider_failure_count},
                )
                if should_block:
                    self.auto_trading_engine.block(reason, "ai_supervisor_provider_blocked")
                    place_orders = False
                continue

            signal = response.signal
            action = str(signal.action or "HOLD").upper()
            self.ai_supervisor.record_signal(symbol, candle_time, signal.signal_id, action)
            if float(signal.confidence or 0) < config.ai_confidence_threshold:
                reason = f"AI confidence below threshold {config.ai_confidence_threshold:.2f}"
                self.ai_store.update_approval(
                    signal.signal_id,
                    approval_status="rejected",
                    approval_reason=reason,
                    approved_notional_usdt=0,
                )
                skipped.append(
                    self._ai_skipped_decision(
                        symbol,
                        candidate,
                        reason,
                        action=action,
                        confidence=float(signal.confidence or 0),
                        signal_id=signal.signal_id,
                    )
                )
                continue
            if signal.approval_status != "approved" or action not in {"BUY", "SELL"}:
                skipped.append(
                    self._ai_skipped_decision(
                        symbol,
                        candidate,
                        signal.approval_reason or f"AI final action {action}",
                        action=action,
                        confidence=float(signal.confidence or 0),
                        signal_id=signal.signal_id,
                    )
                )
                continue

            price = float(candidate.get("price") or (response.context_summary.get("quote") or {}).get("price") or 0)
            equity = float(account.get("equity") or account.get("cash") or 0)
            approved_notional = min(float(signal.approved_notional_usdt or 0), config.max_order_notional)
            strategy_id = f"ai:{signal.signal_id}"
            signal_by_strategy_id[strategy_id] = signal.signal_id
            ai_candidates.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "price": price,
                    "confidence": float(signal.confidence or 0),
                    "strategy_id": strategy_id,
                    "reason": str(signal.response.get("reason") or signal.approval_reason or "AI final decision"),
                    "adjusted_position_ratio": approved_notional / equity if equity > 0 else 0,
                }
            )

        ai_strategy_payload = {
            "signals": ai_candidates,
            "winners": ai_candidates,
            "summary": [
                {"symbol": item["symbol"], "price": item["price"]}
                for item in ai_candidates
            ],
        }
        decisions = self.auto_trading_engine.build_order_decisions(
            ai_strategy_payload,
            account,
            positions,
            place_orders=bool(place_orders and self.auto_trading_engine.state == "running"),
        )
        self.auto_trading_engine.last_decisions = (skipped + decisions)[-50:]
        for skipped_decision in skipped:
            strategy_id = str(skipped_decision.get("strategy_id") or "")
            signal_id = strategy_id.removeprefix("ai:") if strategy_id.startswith("ai:") else ""
            self._audit_ai_decision(skipped_decision, signal_id=signal_id, order=None)

        for decision in decisions:
            signal_id = signal_by_strategy_id.get(str(decision.get("strategy_id") or ""), "")
            if decision.get("status") != "ready":
                if signal_id:
                    self.ai_store.update_approval(
                        signal_id,
                        approval_status="rejected",
                        approval_reason=str(decision.get("message") or "local risk gate rejected AI decision"),
                        approved_notional_usdt=0,
                    )
                self._audit_ai_decision(decision, signal_id=signal_id, order=None)
                continue

            price = float(decision["price"])
            order = self.paper_broker.place_order(
                symbol=decision["symbol"],
                action=decision["action"],
                quantity=float(decision["quantity"]),
                price=price,
                strategy=f"ai-supervised:{signal_id[:20] or 'signal'}",
                order_type="LIMIT",
                stop_loss_price=price * (1 - config.stop_loss_pct) if decision["action"] == "BUY" else None,
                take_profit_price=price * (1 + config.take_profit_pct) if decision["action"] == "BUY" else None,
            )
            self.auto_trading_engine.record_order_result(decision, order.to_response())
            if decision["action"] == "BUY" and order.status in {"filled", "partial_filled"}:
                self._ensure_protective_loop()
            if signal_id:
                status = "ordered" if order.status in {"filled", "partial_filled", "pending"} else "rejected"
                self.ai_store.update_approval(
                    signal_id,
                    approval_status=status,
                    approval_reason=order.message,
                    approved_notional_usdt=round(float(order.filled_quantity or 0) * float(order.filled_price or price), 8),
                    linked_order_id=order.order_id,
                )
            self._audit_ai_decision(decision, signal_id=signal_id, order=order.to_response())

        self.auto_trading_engine.last_error_type = ""
        return self._auto_status_response()

    async def _latest_ai_candle_time(self, symbol: str, period: str) -> str:
        response = await self.get_klines(symbol=symbol, period=period, limit=2)
        if not response.items:
            raise RuntimeError(f"closed K-line unavailable for {symbol}")
        now = datetime.now(timezone.utc)
        closed = []
        for item in response.items:
            try:
                end_time = datetime.fromisoformat(str(item.end_time).replace("Z", "+00:00"))
            except ValueError:
                continue
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            if end_time <= now:
                closed.append((end_time, str(item.end_time)))
        if not closed:
            raise RuntimeError(f"closed K-line unavailable for {symbol}")
        return max(closed, key=lambda row: row[0])[1]

    async def _process_ai_protective_exits(self) -> None:
        protected_symbols = [
            symbol
            for symbol, position in self.paper_broker.positions.items()
            if bool(position.get("protection_enabled", False)) and float(position.get("quantity", 0) or 0) > 0
        ]
        if not protected_symbols:
            return
        quotes = await self.get_quotes(protected_symbols)
        if str(getattr(quotes, "source", "")).lower().startswith("cache"):
            raise RuntimeError("Fresh market quotes are unavailable; protective paper exits were deferred")
        mark_prices = {item.symbol: float(item.price or 0) for item in quotes.items}
        for order in self.paper_broker.process_protective_exits(mark_prices):
            decision = {
                "symbol": order.get("symbol"),
                "action": "SELL",
                "strategy_id": order.get("strategy"),
                "status": "ready",
                "message": order.get("message"),
            }
            self.auto_trading_engine.record_order_result(decision, order)
            self.auto_trading_engine._log(
                "INFO",
                "ai_protective_exit",
                str(order.get("message") or "protected paper position closed"),
                {"order_id": order.get("order_id"), "symbol": order.get("symbol"), "strategy": order.get("strategy")},
            )

    def _has_protected_positions(self) -> bool:
        return any(
            bool(position.get("protection_enabled", False)) and float(position.get("quantity", 0) or 0) > 0
            for position in self.paper_broker.positions.values()
        )

    def _ensure_protective_loop(self) -> None:
        if not self._has_protected_positions():
            return
        if self._protective_loop_task is not None and not self._protective_loop_task.done():
            return
        self._protective_loop_task = asyncio.create_task(self._protective_risk_loop())

    async def _stop_protective_loop(self) -> None:
        task = self._protective_loop_task
        self._protective_loop_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _protective_risk_loop(self) -> None:
        current_task = asyncio.current_task()
        self.auto_trading_engine._log("INFO", "protective_loop_started", "paper position protection loop started")
        try:
            while self._has_protected_positions():
                try:
                    async with self._auto_scan_lock:
                        await self._process_ai_protective_exits()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.auto_trading_engine._log(
                        "WARNING",
                        "protective_exit_failed",
                        str(exc),
                        {"type": exc.__class__.__name__},
                    )
                if not self._has_protected_positions():
                    break
                await asyncio.sleep(max(0.1, float(self._protective_interval_seconds or 5)))
        finally:
            if self._protective_loop_task is current_task:
                self._protective_loop_task = None
            self.auto_trading_engine._log("INFO", "protective_loop_stopped", "paper position protection loop stopped")

    def _ai_skipped_decision(
        self,
        symbol: str,
        candidate: dict[str, Any],
        message: str,
        *,
        action: str = "HOLD",
        confidence: float = 0.0,
        signal_id: str = "",
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": action,
            "price": float(candidate.get("price") or 0),
            "quantity": 0.0,
            "notional": 0.0,
            "strategy_id": f"ai:{signal_id}" if signal_id else str(candidate.get("strategy_id") or "ai-supervisor"),
            "confidence": float(confidence or 0),
            "reason": str(candidate.get("reason") or "strategy candidate"),
            "status": "skipped",
            "message": str(message or "AI final decision skipped"),
            "place_orders": False,
            "steps": [
                {
                    "name": "ai_final_decision",
                    "status": "skip",
                    "reason": str(message or "AI final decision skipped"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }

    def _audit_ai_decision(self, decision: dict[str, Any], *, signal_id: str, order: dict[str, Any] | None) -> None:
        trail = self.audit_logger.create_trail(
            str(decision.get("symbol") or ""),
            self.auto_trading_engine.config.period,
            f"ai-supervised:{signal_id[:20] or 'signal'}",
        )
        self.audit_logger.log_step(
            trail,
            AuditStage.SIGNAL_GENERATION,
            AuditVerdict.PASS,
            inputs={"signal_id": signal_id, "confidence": decision.get("confidence")},
            outputs={"action": decision.get("action")},
            reason=str(decision.get("reason") or "AI final decision"),
        )
        approved = decision.get("status") == "ready" and order is not None
        self.audit_logger.log_step(
            trail,
            AuditStage.POSITION_SIZING,
            AuditVerdict.PASS if approved else AuditVerdict.FAIL,
            outputs={"quantity": decision.get("quantity"), "notional": decision.get("notional")},
            reason=str(decision.get("message") or "local risk gate"),
        )
        if order is not None:
            self.audit_logger.log_step(
                trail,
                AuditStage.ORDER_SIMULATION,
                AuditVerdict.PASS if str(order.get("status")) in {"filled", "partial_filled", "pending"} else AuditVerdict.FAIL,
                outputs={"order_id": order.get("order_id"), "status": order.get("status")},
                reason=str(order.get("message") or "PaperBroker result"),
            )
        self.audit_logger.finalize(
            trail,
            str(decision.get("action") or "HOLD") if approved else "HOLD",
            str((order or {}).get("message") or decision.get("message") or "AI decision blocked"),
        )

    def _ai_supervisor_start_error(self) -> str:
        if not self.ai_config.enabled:
            return "AI supervisor is disabled in config"
        if self.ai_config.provider not in {"deepseek", "openai"}:
            return f"unsupported AI provider: {self.ai_config.provider}"
        if not os.environ.get(self.ai_config.api_key_env, "").strip():
            return f"missing AI API key env: {self.ai_config.api_key_env}"
        return ""

    def _sync_ai_supervisor_status(self) -> None:
        config = self.auto_trading_engine.config
        self.auto_trading_engine.ai_supervisor_status = self.ai_supervisor.status(
            model=config.ai_model,
            fallback_model=config.ai_fallback_model,
            enabled=config.decision_mode == "ai_supervised" and self.auto_trading_engine.state == "running",
        )

    def _auto_status_response(self) -> AutoTradingStatusResponse:
        self._sync_ai_supervisor_status()
        return AutoTradingStatusResponse(**self.auto_trading_engine.status())

    def start_background_tasks(self) -> None:
        """Restore safety monitors that must outlive the strategy loop."""
        self._ensure_protective_loop()

    async def shutdown_background_tasks(self) -> None:
        """Cancel service-owned tasks during API shutdown."""
        await self._stop_auto_loop()
        await self._stop_protective_loop()

    def _ensure_auto_loop(self) -> None:
        if self._auto_loop_task is not None and not self._auto_loop_task.done():
            return
        self.auto_trading_engine.mark_loop(running=True, next_run_at=datetime.now(timezone.utc).isoformat())
        self._auto_loop_task = asyncio.create_task(self._auto_trading_loop())

    async def _stop_auto_loop(self) -> None:
        task = self._auto_loop_task
        self._auto_loop_task = None
        self.auto_trading_engine.mark_loop(running=False)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _auto_trading_loop(self) -> None:
        self.auto_trading_engine.mark_loop(running=True, next_run_at=datetime.now(timezone.utc).isoformat())
        try:
            while self.auto_trading_engine.state == "running" and self.auto_trading_engine.config.enabled:
                try:
                    async with self._auto_scan_lock:
                        await self._run_auto_trading_cycle_locked()
                    self._auto_loop_consecutive_errors = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._auto_loop_consecutive_errors += 1
                    self.auto_trading_engine.record_error(
                        str(exc),
                        {
                            "type": exc.__class__.__name__,
                            "source": "auto_loop",
                            "consecutive_errors": self._auto_loop_consecutive_errors,
                        },
                    )

                if self.auto_trading_engine.state != "running" or not self.auto_trading_engine.config.enabled:
                    break

                interval = max(5, min(int(self.auto_trading_engine.config.scan_interval_seconds or 30), 3600))
                next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
                self.auto_trading_engine.mark_loop(running=True, next_run_at=next_run.isoformat())
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.auto_trading_engine.record_error(str(exc), {"type": exc.__class__.__name__, "source": "auto_loop"})
        finally:
            if self.auto_trading_engine.state != "running" or not self.auto_trading_engine.config.enabled:
                self.auto_trading_engine.mark_loop(running=False)

    async def get_auto_trading_logs(self, limit: int = 100) -> AutoTradingLogsResponse:
        logs = self.auto_trading_engine.get_logs(limit)
        return AutoTradingLogsResponse(items=logs, count=len(logs))

    async def place_shadow_order(self, request: CryptoShadowOrderRequest) -> CryptoShadowTradeResponse:
        record = self.shadow_engine.execute_shadow_trade(
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            strategy_id=request.strategy_id,
            sl_price=request.stop_loss_price,
            tp_price=request.take_profit_price,
        )
        return CryptoShadowTradeResponse(**record)

    async def get_shadow_positions(self) -> CryptoShadowPositionsResponse:
        items = [CryptoShadowPositionResponse(**item) for item in self.shadow_engine.get_positions()]
        return CryptoShadowPositionsResponse(items=items, count=len(items))

    async def get_shadow_logs(self, limit: int = 100) -> CryptoShadowLogsResponse:
        rows = self.shadow_engine.trade_log[-max(1, min(int(limit or 100), 500)) :]
        items = [CryptoShadowTradeResponse(**item) for item in rows]
        return CryptoShadowLogsResponse(items=items, count=len(items))

    async def build_portfolio_returns(self, request: PortfolioReturnsRequest) -> PortfolioReturnsResponse:
        account = self.paper_broker.get_account_info()
        capital_base = float(request.capital_base or 0.0) or float(account.get("equity") or account.get("initial_cash") or 0.0)
        trades = self._portfolio_paper_rows()
        shadow_rows = self._portfolio_shadow_rows()
        analytics = build_portfolio_return_analytics(
            mode=request.mode,
            range=request.range,
            trades=trades,
            shadow_orders=shadow_rows,
            capital_base=capital_base,
            limit=request.limit,
        )
        return PortfolioReturnsResponse(**analytics.to_dict())

    async def analyze_ai_signal(
        self,
        request: AiSignalAnalyzeRequest,
        *,
        strategy_candidate: dict[str, Any] | None = None,
        execution_mode: str = "advisory",
        fallback_model: str | None = None,
    ) -> AiSignalAnalyzeResponse:
        """Run one structured AI analysis and persist the signal."""
        symbol = normalize_crypto_symbol(request.symbol, self.crypto_config.get("default_quote_currency", "USDT"))
        limit = min(int(request.limit or 120), self.ai_config.max_context_candles)
        try:
            quote_response = await self.get_quotes([symbol])
            kline_response = await self.get_klines(symbol=symbol, period=request.period, limit=limit)
            account = self.paper_broker.get_account_info()
            positions = self.paper_broker.get_positions()
            recent_orders = self.paper_broker.get_orders(limit=20, offset=0)["items"]
            macro = {}
            try:
                macro = (await self.get_macro_overview()).model_dump()
            except Exception:
                macro = {}
            quote = quote_response.items[0].model_dump() if quote_response.items else {"symbol": symbol, "price": 0}
            context = AiSignalContextBuilder.build(
                symbol=symbol,
                period=request.period,
                quote=quote,
                klines=[item.model_dump() for item in kline_response.items],
                account=account,
                positions=positions,
                recent_orders=recent_orders,
                risk_config=self.config.get("risk", {}) or {},
                ai_config=self.ai_config,
                macro=macro,
            )
            if strategy_candidate:
                context["strategy_candidate"] = {
                    "symbol": symbol,
                    "action": str(strategy_candidate.get("action") or "HOLD").upper(),
                    "confidence": float(strategy_candidate.get("confidence") or strategy_candidate.get("score") or 0),
                    "strategy_id": str(strategy_candidate.get("strategy_id") or "strategy"),
                    "reason": str(strategy_candidate.get("reason") or "strategy candidate"),
                }
            context["execution_mode"] = execution_mode
            if execution_mode == "auto_paper":
                context["ai_limits"] = {
                    **(context.get("ai_limits") or {}),
                    "manual_confirm_required": False,
                    "auto_paper_order_enabled": True,
                    "real_trading_allowed": False,
                }
            if request.model or execution_mode != "advisory" or fallback_model:
                advice = self.ai_advisor.analyze(
                    context,
                    selected_model=request.model,
                    fallback_model=fallback_model,
                    execution_mode=execution_mode,
                )
            else:
                advice = self.ai_advisor.analyze(context)
        except ApiError:
            raise
        except ValueError as exc:
            failed = self.ai_store.save_signal(
                symbol=symbol,
                period=request.period,
                model=self.ai_config.model,
                request_summary={"symbol": symbol, "period": request.period, "error": "invalid_model_output"},
                response={
                    "symbol": symbol,
                    "action": "HOLD",
                    "confidence": 0.0,
                    "suggested_notional_usdt": 0.0,
                    "max_loss_usdt": 0.0,
                    "time_horizon": "",
                    "reason": f"Invalid AI response: {exc}",
                    "risk_notes": ["AI output did not pass local schema validation"],
                    "invalid_if": ["Model output is invalid"],
                },
                approval_status="failed",
                approval_reason=str(exc),
            )
            return AiSignalAnalyzeResponse(signal=self._ai_record_response(failed), context_summary=failed["request_summary"])
        except Exception as exc:
            raise ApiError(
                503,
                f"AI provider unavailable: {exc}",
                ErrorCode.AI_PROVIDER_UNAVAILABLE,
            ) from exc

        approval = self._assess_ai_advice(advice, account, positions, execution_mode=execution_mode)
        context_summary = AiSignalContextBuilder.summarize(context)
        record = self.ai_store.save_signal(
            symbol=symbol,
            period=request.period,
            model=str(advice.get("model") or self.ai_config.model),
            request_summary=context_summary,
            response=advice,
            approval_status=approval["approval_status"],
            approval_reason=approval["approval_reason"],
            approved_notional_usdt=approval["approved_notional_usdt"],
        )
        return AiSignalAnalyzeResponse(signal=self._ai_record_response(record), context_summary=context_summary)

    async def list_ai_signals(
        self,
        limit: int = 100,
        offset: int = 0,
        symbol: str | None = None,
    ) -> AiSignalListResponse:
        page = self.ai_store.list_signals(limit=limit, offset=offset, symbol=symbol)
        return AiSignalListResponse(
            items=[self._ai_record_response(item) for item in page["items"]],
            count=page["count"],
            total=page["total"],
            limit=page["limit"],
            offset=page["offset"],
        )

    async def get_ai_signal(self, signal_id: str) -> AiSignalRecordResponse:
        record = self.ai_store.get_signal(signal_id)
        if not record:
            raise ApiError(404, "AI signal not found", ErrorCode.AI_SIGNAL_NOT_FOUND)
        return self._ai_record_response(record)

    async def create_ai_signal_paper_order(self, signal_id: str) -> AiSignalPaperOrderResponse:
        record = self.ai_store.get_signal(signal_id)
        if not record:
            raise ApiError(404, "AI signal not found", ErrorCode.AI_SIGNAL_NOT_FOUND)

        advice = validate_ai_advice(record.get("response", {}), expected_symbol=record.get("symbol", ""))
        account = self.paper_broker.get_account_info()
        positions = self.paper_broker.get_positions()
        approval = self._assess_ai_advice(advice, account, positions)
        if approval["approval_status"] != "approved":
            updated = self.ai_store.update_approval(
                signal_id,
                approval_status="rejected",
                approval_reason=approval["approval_reason"],
                approved_notional_usdt=approval["approved_notional_usdt"],
            ) or record
            return AiSignalPaperOrderResponse(
                success=False,
                message=approval["approval_reason"],
                signal=self._ai_record_response(updated),
                order=None,
            )

        try:
            quote_response = await self.get_quotes([advice["symbol"]])
            price = float(quote_response.items[0].price if quote_response.items else 0)
        except Exception:
            price = float((record.get("request_summary", {}).get("quote") or {}).get("price", 0) or 0)
        if price <= 0:
            updated = self.ai_store.update_approval(
                signal_id,
                approval_status="rejected",
                approval_reason="missing executable price",
                approved_notional_usdt=0,
            ) or record
            return AiSignalPaperOrderResponse(success=False, message="missing executable price", signal=self._ai_record_response(updated))

        action = advice["action"]
        notional = float(approval["approved_notional_usdt"] or 0)
        if action == "BUY":
            quantity = round(notional / price, 8)
        else:
            held = self._position_quantity(advice["symbol"], positions)
            quantity = round(min(held, notional / price), 8)
        if quantity <= 0:
            updated = self.ai_store.update_approval(
                signal_id,
                approval_status="rejected",
                approval_reason="AI signal produced zero executable quantity",
                approved_notional_usdt=notional,
            ) or record
            return AiSignalPaperOrderResponse(success=False, message="AI signal produced zero executable quantity", signal=self._ai_record_response(updated))

        order = self.paper_broker.place_order(
            symbol=advice["symbol"],
            action=action,
            quantity=quantity,
            price=price,
            strategy=f"ai:{signal_id[:24]}",
            order_type="LIMIT",
        )
        order_response = CryptoPaperOrderResponse(**order.to_response())
        status = "ordered" if order.status in {"filled", "partial_filled", "pending"} else "rejected"
        updated = self.ai_store.update_approval(
            signal_id,
            approval_status=status,
            approval_reason=order.message,
            approved_notional_usdt=round(quantity * price, 8),
            linked_order_id=order.order_id,
        ) or record
        return AiSignalPaperOrderResponse(
            success=status == "ordered",
            message=order.message,
            signal=self._ai_record_response(updated),
            order=order_response,
        )

    async def chat_ai_assistant(self, request: AiChatRequest) -> AiChatResponse:
        """Send one advisory-only AI chat message and persist the exchange."""
        session_id = str(request.session_id or "").strip() or None
        if session_id and not self.ai_chat_store.get_session_detail(session_id):
            raise ApiError(404, "AI chat session not found", ErrorCode.RESOURCE_NOT_FOUND)

        symbol = normalize_crypto_symbol(request.symbol, self.crypto_config.get("default_quote_currency", "USDT"))
        context_summary = await self._build_ai_chat_context_summary(
            symbol=symbol,
            period=request.period,
            limit=request.limit,
            include_context=request.include_context,
            current_route=request.current_route,
            current_module=request.current_module,
            current_view_title=request.current_view_title,
            visible_context=request.visible_context,
            guide_mode=request.guide_mode,
            user_goal=request.user_goal or request.message,
        )
        recent_messages = self.ai_chat_store.list_messages(session_id, limit=12) if session_id else []
        try:
            assistant_payload = self.ai_chat_assistant.chat(
                message=request.message,
                context_summary=context_summary,
                recent_messages=recent_messages,
                model=request.model,
            )
        except Exception as exc:
            raise ApiError(
                503,
                f"AI provider unavailable: {exc}",
                ErrorCode.AI_PROVIDER_UNAVAILABLE,
            ) from exc

        saved = self.ai_chat_store.save_exchange(
            session_id=session_id,
            title_seed=request.message,
            user_content=request.message,
            assistant_content=assistant_payload["content"],
            model=assistant_payload.get("model", self.ai_config.model),
            context_summary=context_summary,
        )
        if not saved:
            raise ApiError(404, "AI chat session not found", ErrorCode.RESOURCE_NOT_FOUND)
        return AiChatResponse(
            session=self._ai_chat_session_response(saved["session"]),
            user_message=self._ai_chat_message_response(saved["user_message"]),
            assistant_message=self._ai_chat_message_response(saved["assistant_message"]),
            context_summary=context_summary,
        )

    async def stream_ai_assistant(self, request: AiChatRequest) -> AsyncIterator[dict[str, Any]]:
        """Stream one advisory-only exchange and persist it only after completion."""
        session_id = str(request.session_id or "").strip() or None
        if session_id and not self.ai_chat_store.get_session_detail(session_id):
            yield {
                "event": "error",
                "data": {"code": ErrorCode.RESOURCE_NOT_FOUND, "message": "AI chat session not found", "retryable": False},
            }
            return

        symbol = normalize_crypto_symbol(request.symbol, self.crypto_config.get("default_quote_currency", "USDT"))
        context_summary = await self._build_ai_chat_context_summary(
            symbol=symbol,
            period=request.period,
            limit=request.limit,
            include_context=request.include_context,
            current_route=request.current_route,
            current_module=request.current_module,
            current_view_title=request.current_view_title,
            visible_context=request.visible_context,
            guide_mode=request.guide_mode,
            user_goal=request.user_goal or request.message,
        )
        recent_messages = self.ai_chat_store.list_messages(session_id, limit=12) if session_id else []
        request_id = f"AISTREAM_{uuid4().hex}"
        active_model = str(request.model or self.ai_config.model)

        try:
            provider_events = self.ai_chat_assistant.stream_chat(
                message=request.message,
                context_summary=context_summary,
                recent_messages=recent_messages,
                model=request.model,
            )
            async for provider_event in iterate_in_threadpool(provider_events):
                event_name = str(provider_event.get("event") or "")
                active_model = str(provider_event.get("model") or active_model)
                if event_name == "start":
                    yield {
                        "event": "start",
                        "data": {
                            "request_id": request_id,
                            "model": active_model,
                            "context_summary": context_summary,
                        },
                    }
                elif event_name == "delta":
                    yield {
                        "event": "delta",
                        "data": {
                            "request_id": request_id,
                            "model": active_model,
                            "content": str(provider_event.get("content") or ""),
                        },
                    }
                elif event_name == "done":
                    content = str(provider_event.get("content") or "").strip()
                    saved = self.ai_chat_store.save_exchange(
                        session_id=session_id,
                        title_seed=request.message,
                        user_content=request.message,
                        assistant_content=content,
                        model=active_model,
                        context_summary=context_summary,
                    )
                    if not saved:
                        yield {
                            "event": "error",
                            "data": {
                                "code": ErrorCode.RESOURCE_NOT_FOUND,
                                "message": "AI chat session not found",
                                "retryable": False,
                            },
                        }
                        return
                    response = AiChatResponse(
                        session=self._ai_chat_session_response(saved["session"]),
                        user_message=self._ai_chat_message_response(saved["user_message"]),
                        assistant_message=self._ai_chat_message_response(saved["assistant_message"]),
                        context_summary=context_summary,
                    )
                    yield {"event": "done", "data": response.model_dump(mode="json")}
                    return
        except Exception:
            yield {
                "event": "error",
                "data": {
                    "code": ErrorCode.AI_PROVIDER_UNAVAILABLE,
                    "message": "AI 服务暂时不可用，请稍后重试或切换 Flash 模型。",
                    "retryable": True,
                },
            }

    async def list_ai_chat_sessions(self, limit: int = 50, offset: int = 0) -> AiChatSessionListResponse:
        page = self.ai_chat_store.list_sessions(limit=limit, offset=offset)
        return AiChatSessionListResponse(
            items=[self._ai_chat_session_response(item) for item in page["items"]],
            count=page["count"],
            total=page["total"],
            limit=page["limit"],
            offset=page["offset"],
        )

    async def get_ai_chat_session(self, session_id: str) -> AiChatSessionDetailResponse:
        detail = self.ai_chat_store.get_session_detail(session_id)
        if not detail:
            raise ApiError(404, "AI chat session not found", ErrorCode.RESOURCE_NOT_FOUND)
        return AiChatSessionDetailResponse(
            session=self._ai_chat_session_response(detail["session"]),
            messages=[self._ai_chat_message_response(item) for item in detail["messages"]],
        )

    async def delete_ai_chat_session(self, session_id: str) -> dict[str, Any]:
        deleted = self.ai_chat_store.delete_session(session_id)
        if not deleted:
            raise ApiError(404, "AI chat session not found", ErrorCode.RESOURCE_NOT_FOUND)
        return {"success": True, "message": "AI chat session deleted"}

    async def get_testnet_status(self) -> BinanceTestnetStatusResponse:
        return BinanceTestnetStatusResponse(**self.testnet_executor.status())

    async def save_testnet_credentials(self, request: BinanceTestnetCredentialsRequest) -> BinanceTestnetActionResponse:
        return BinanceTestnetActionResponse(**self.testnet_executor.save_credentials(request.api_key, request.api_secret))

    async def clear_testnet_credentials(self) -> BinanceTestnetActionResponse:
        return BinanceTestnetActionResponse(**self.testnet_executor.clear_credentials())

    async def enable_testnet_orders(self, request: BinanceTestnetEnableRequest) -> BinanceTestnetActionResponse:
        return BinanceTestnetActionResponse(**self.testnet_executor.enable_testnet_orders(request.confirmation_phrase))

    async def place_testnet_order(self, request: BinanceTestnetOrderRequest) -> BinanceTestnetOrderResponse:
        order = self.testnet_executor.place_order(
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            price=request.price,
            order_type=request.order_type,
            dry_run=request.dry_run,
        )
        return BinanceTestnetOrderResponse(**order.to_response())

    async def get_strategy_templates(self) -> CryptoStrategyTemplatesResponse:
        items = [CryptoStrategyTemplateResponse(**item) for item in self.strategy_engine.list_templates()]
        return CryptoStrategyTemplatesResponse(items=items, count=len(items))

    async def run_strategies(self, request: CryptoStrategyRunRequest) -> CryptoStrategyRunResponse:
        timeframes = request.timeframes or [request.period]
        configs = self.strategy_engine.normalize_configs([item.model_dump() for item in request.strategies], request.symbols)
        if len(timeframes) > 1:
            result = await self.run_strategies_multi_timeframe(request)
        else:
            market_data = await self._load_strategy_market_data(request.symbols, timeframes[0], request.limit)
            regimes, regime_scores = self._detect_regimes_from_market_data(market_data)
            macro_gate = self.macro_evaluator.evaluate(self.macro_provider.fetch_snapshot())
            result = self.strategy_engine.run(
                market_data,
                configs,
                conflict_threshold=request.conflict_threshold,
                regimes=regimes,
                regime_scores=regime_scores,
                macro_gate=macro_gate,
            )
        return CryptoStrategyRunResponse(
            signals=[CryptoStrategySignalResponse(**item) for item in result["signals"]],
            winners=[ConflictResolutionDetailResponse(**item) for item in result.get("winners", [])],
            blocked=[ConflictResolutionDetailResponse(**item) for item in result.get("blocked", [])],
            audit_trails=result.get("audit_trails", []),
            summary=[CryptoStrategySummaryResponse(**item) for item in result["summary"]],
            strategy_results=[CryptoStrategyResultResponse(**item) for item in result["strategy_results"]],
        )

    async def run_strategies_multi_timeframe(self, request: CryptoStrategyRunRequest) -> dict[str, Any]:
        """Run crypto strategies across multiple timeframes with conflict resolution."""
        timeframes = request.timeframes or [request.period]
        market_data = await self._load_multi_timeframe_market_data(request.symbols, timeframes, request.limit)
        configs = self.strategy_engine.normalize_configs([item.model_dump() for item in request.strategies], request.symbols)

        primary_data = market_data.get(request.period) or next(iter(market_data.values()), {})
        regimes, regime_scores = self._detect_regimes_from_market_data(primary_data)
        macro_gate = self.macro_evaluator.evaluate(self.macro_provider.fetch_snapshot())
        return self.strategy_engine.run_multi_timeframe(
            market_data=market_data,
            configs=configs,
            conflict_threshold=request.conflict_threshold,
            regimes=regimes,
            regime_scores=regime_scores,
            macro_gate=macro_gate,
            max_positions=request.max_positions,
            audit_logger=self.audit_logger,
        )

    async def backtest_strategies(self, request: CryptoStrategyBacktestRequest) -> CryptoStrategyBacktestResponse:
        market_data = await self._load_strategy_market_data(request.symbols, request.period, request.limit)
        configs = self.strategy_engine.normalize_configs([item.model_dump() for item in request.strategies], request.symbols)
        engine = CryptoBacktestEngine(
            initial_cash=request.initial_cash,
            fee_rate=request.fee_rate,
            slippage_rate=request.slippage_rate,
            min_quantity=request.min_quantity,
            position_sizing=request.position_sizing,
            period=request.period,
        )
        results = engine.run_many(market_data, configs)
        items = [CryptoStrategyBacktestResultResponse(**item) for item in results]
        return CryptoStrategyBacktestResponse(items=items, count=len(items))

    async def walk_forward_backtest(self, request: CryptoStrategyWalkForwardRequest) -> CryptoWalkForwardResponse:
        """Run walk-forward backtest with rolling training/validation windows."""
        market_data = await self._load_strategy_market_data(request.symbols, request.period, request.limit)
        configs = self.strategy_engine.normalize_configs(
            [item.model_dump() for item in request.strategies], request.symbols
        )

        wf_config = WalkForwardConfig(
            train_ratio=request.train_ratio,
            validation_ratio=request.validation_ratio,
            min_train_candles=request.min_train_candles,
            step_size=request.step_size,
            perturbation_runs=request.perturbation_runs,
            perturbation_pct=request.perturbation_pct,
            initial_cash=request.initial_cash,
            fee_rate=request.fee_rate,
            slippage_rate=request.slippage_rate,
            min_quantity=request.min_quantity,
            period=request.period,
        )
        runner = WalkForwardRunner(config=wf_config)
        param_grids = request.param_grid if request.param_grid else None
        result = runner.run(market_data, configs, param_grids=param_grids)

        return CryptoWalkForwardResponse(
            rounds=[WalkForwardRoundResponse(**r) for r in result["rounds"]],
            by_strategy=[WalkForwardStrategySummaryResponse(**s) for s in result["by_strategy"]],
            by_symbol=[WalkForwardSymbolSummaryResponse(**s) for s in result["by_symbol"]],
            factor_audit=result["factor_audit"],
            config=WalkForwardConfigResponse(**result["config"]) if result.get("config") else None,
        )

    def record_quote_snapshots(self, rows: list[dict[str, Any]]) -> None:
        self.market_cache.upsert_quotes(rows)
        open_symbols = {
            symbol
            for symbol, position in self.paper_broker.positions.items()
            if float(position.get("quantity", 0) or 0) > 0
        }
        if open_symbols:
            mark_prices = {}
            for row in rows or []:
                if str(row.get("market_type") or "spot") != "spot":
                    continue
                symbol = normalize_crypto_symbol(row.get("symbol"), self.paper_broker.quote_currency)
                if symbol in open_symbols:
                    mark_prices[symbol] = row.get("price")
            self.paper_broker.mark_to_market(mark_prices, record_equity=False)
        market_rows: dict[str, list[dict[str, Any]]] = {}
        for row in rows or []:
            market_type = str(row.get("market_type") or "spot")
            if market_type != "spot":
                market_rows.setdefault(market_type, []).append(row)
        for market_type, group in market_rows.items():
            self.market_cache.upsert_market_quotes(group, market_type=market_type)

    def record_klines(self, rows: list[dict[str, Any]]) -> None:
        self.market_cache.upsert_klines(rows)

    def _portfolio_paper_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for trade in self.paper_broker.trade_history:
            action = str(trade.get("action") or "").upper()
            timestamp = str(trade.get("timestamp") or "")
            quantity = float(trade.get("quantity", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            row = {
                "id": str(trade.get("trade_id") or trade.get("order_id") or ""),
                "trade_id": str(trade.get("trade_id") or ""),
                "order_id": str(trade.get("order_id") or ""),
                "symbol": str(trade.get("symbol") or ""),
                "side": action,
                "status": "closed" if action == "SELL" else "settled",
                "created_at": timestamp,
                "closed_at": timestamp if action == "SELL" else None,
                "timestamp": timestamp,
                "strategy_id": str(trade.get("strategy") or ""),
                "quantity": quantity,
                "amount": quantity,
                "price": price,
                "entry_price": price if action == "BUY" else None,
                "exit_price": price if action == "SELL" else None,
                "notional": quantity * price,
                "fee": float(trade.get("fee", 0) or 0),
                "realized_pnl": float(trade.get("realized_pnl", 0) or 0),
                "reason": str(trade.get("strategy") or ""),
            }
            rows.append(row)

        for position in self.paper_broker.get_positions():
            rows.append(
                {
                    "id": f"open_{position.get('symbol', '')}",
                    "symbol": str(position.get("symbol") or ""),
                    "side": "BUY",
                    "status": "open",
                    "created_at": "",
                    "timestamp": time.time(),
                    "strategy_id": "open_position",
                    "quantity": float(position.get("quantity", 0) or 0),
                    "amount": float(position.get("quantity", 0) or 0),
                    "avg_price": float(position.get("avg_price", 0) or 0),
                    "entry_price": float(position.get("avg_price", 0) or 0),
                    "current_price": float(position.get("current_price", 0) or 0),
                    "mark_price": float(position.get("current_price", 0) or 0),
                    "market_value": float(position.get("market_value", 0) or 0),
                    "notional": float(position.get("cost_basis", 0) or 0),
                    "unrealized_pnl": float(position.get("unrealized_pnl", 0) or 0),
                }
            )
        return rows

    def _portfolio_shadow_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        mark_prices = self._fetch_mark_prices([item.get("symbol", "") for item in self.shadow_engine.get_positions()])
        for position in self.shadow_engine.get_positions():
            symbol = str(position.get("symbol") or "")
            quantity = float(position.get("quantity", 0) or 0)
            avg_price = float(position.get("avg_price", 0) or 0)
            mark_price = float(mark_prices.get(symbol, avg_price) or avg_price)
            rows.append(
                {
                    "id": f"shadow_{symbol}",
                    "symbol": symbol,
                    "side": "BUY",
                    "status": "open",
                    "created_at": position.get("created_at") or "",
                    "timestamp": position.get("created_at") or time.time(),
                    "strategy_id": position.get("signal_source") or "shadow",
                    "quantity": quantity,
                    "amount": quantity,
                    "entry_price": avg_price,
                    "avg_price": avg_price,
                    "mark_price": mark_price,
                    "notional": quantity * avg_price,
                    "unrealized_pnl": (mark_price - avg_price) * quantity,
                    "slippage_bps": float(position.get("estimated_slippage_pct", 0) or 0) * 100,
                    "stop_loss_price": position.get("stop_loss_price"),
                    "take_profit_price": position.get("take_profit_price"),
                    "is_estimated": True,
                }
            )
        for log in self.shadow_engine.trade_log:
            if str(log.get("action") or "").upper() == "SELL":
                rows.append(
                    {
                        **log,
                        "id": f"shadow_log_{log.get('timestamp', '')}_{log.get('symbol', '')}",
                        "status": "closed",
                        "closed_at": log.get("timestamp"),
                        "entry_price": log.get("price"),
                        "exit_price": log.get("price"),
                        "is_estimated": True,
                    }
                )
        return rows

    def _fetch_mark_prices(self, symbols: list[str]) -> dict[str, float]:
        normalized = self._normalize_symbols([symbol for symbol in symbols if symbol])
        if not normalized:
            return {}
        try:
            return {row["symbol"]: float(row.get("price", 0) or 0) for row in self.provider.fetch_quotes(normalized)}
        except Exception:
            cached = self.market_cache.get_quotes(normalized)
            return {row["symbol"]: float(row.get("price", 0) or 0) for row in cached}

    def _assess_ai_advice(
        self,
        advice: dict[str, Any],
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        execution_mode: str = "advisory",
    ) -> dict[str, Any]:
        action = str(advice.get("action") or "HOLD").upper()
        confidence = float(advice.get("confidence", 0) or 0)
        symbol = normalize_crypto_symbol(advice.get("symbol") or "")
        risk_config = self.config.get("risk", {}) or {}
        trading_config = self.config.get("trading", {}) or {}
        crypto_config = self.config.get("crypto", {}) or {}
        paper_config = crypto_config.get("paper", {}) or {}

        blocked_flags = [
            bool(account.get("real_trading_enabled", False)),
            bool(risk_config.get("real_trading_enabled", False)),
            bool(trading_config.get("real_trading_enabled", False)),
            bool(paper_config.get("real_trading_enabled", False)),
            bool((crypto_config.get("testnet", {}) or {}).get("real_trading_enabled", False)),
            bool((crypto_config.get("mainnet", {}) or {}).get("real_trading_enabled", False)),
        ]
        if any(blocked_flags):
            return self._ai_approval("blocked", "real trading is disabled for AI signals", 0)
        if action == "HOLD":
            return self._ai_approval("blocked", "HOLD signal cannot generate an order", 0)
        if action not in {"BUY", "SELL"}:
            return self._ai_approval("blocked", "unsupported AI action", 0)
        if confidence < self.ai_config.min_confidence_for_order:
            return self._ai_approval(
                "blocked",
                f"confidence below threshold {self.ai_config.min_confidence_for_order:.2f}",
                0,
            )
        if risk_config.get("allow_leverage", False):
            return self._ai_approval("blocked", "AI orders require leverage disabled", 0)
        if action == "SELL" and risk_config.get("allow_short_selling", False):
            return self._ai_approval("blocked", "AI orders require short selling disabled", 0)

        suggested = float(advice.get("suggested_notional_usdt", 0) or 0)
        max_order = min(
            suggested,
            float(self.ai_config.max_order_notional or 0),
            float(risk_config.get("max_order_notional", self.ai_config.max_order_notional) or self.ai_config.max_order_notional),
            float(paper_config.get("max_order_notional", self.ai_config.max_order_notional) or self.ai_config.max_order_notional),
        )
        if max_order <= 0:
            return self._ai_approval("blocked", "AI suggested notional is zero", 0)

        if action == "BUY":
            available_cash = float(account.get("available_cash") or account.get("cash") or 0)
            approved = min(max_order, available_cash)
            if approved <= 0:
                return self._ai_approval("blocked", "insufficient USDT cash", 0)
            mode_label = "AI supervised PaperBroker" if execution_mode == "auto_paper" else "manual paper"
            return self._ai_approval("approved", f"approved for {mode_label} BUY up to {approved:.2f} USDT", approved)

        quantity = self._position_quantity(symbol, positions)
        if quantity <= 0:
            return self._ai_approval("blocked", "no position to sell; short selling disabled", 0)
        mode_label = "AI supervised PaperBroker" if execution_mode == "auto_paper" else "manual paper"
        return self._ai_approval("approved", f"approved for {mode_label} SELL up to {max_order:.2f} USDT", max_order)

    def _ai_approval(self, status: str, reason: str, notional: float) -> dict[str, Any]:
        return {
            "approval_status": status,
            "approval_reason": reason,
            "approved_notional_usdt": round(float(notional or 0), 8),
        }

    def _position_quantity(self, symbol: str, positions: list[dict[str, Any]]) -> float:
        normalized = normalize_crypto_symbol(symbol)
        for position in positions or []:
            if normalize_crypto_symbol(position.get("symbol")) == normalized:
                return float(position.get("available", position.get("quantity", 0)) or 0)
        return 0.0

    async def _build_ai_chat_context_summary(
        self,
        *,
        symbol: str,
        period: str,
        limit: int,
        include_context: bool,
        current_route: str | None = None,
        current_module: str | None = None,
        current_view_title: str | None = None,
        visible_context: dict[str, Any] | None = None,
        guide_mode: bool = False,
        user_goal: str | None = None,
    ) -> dict[str, Any]:
        project_context = ProjectAssistantContextBuilder.build_base(
            symbol=symbol,
            period=period,
            include_market_context=include_context,
            ai_config=self.ai_config,
            current_route=current_route,
            current_module=current_module,
            current_view_title=current_view_title,
            visible_context=visible_context,
            guide_mode=guide_mode,
            user_goal=user_goal,
        )
        if not include_context:
            return project_context

        safe_limit = min(int(limit or 120), self.ai_config.max_context_candles)
        quote_response = await self.get_quotes([symbol])
        kline_response = await self.get_klines(symbol=symbol, period=period, limit=safe_limit)
        account = self.paper_broker.get_account_info()
        positions = self.paper_broker.get_positions()
        recent_orders = self.paper_broker.get_orders(limit=20, offset=0)["items"]
        macro = {}
        try:
            macro = (await self.get_macro_overview()).model_dump()
        except Exception:
            macro = {}
        quote = quote_response.items[0].model_dump() if quote_response.items else {"symbol": symbol, "price": 0}
        context = AiSignalContextBuilder.build(
            symbol=symbol,
            period=period,
            quote=quote,
            klines=[item.model_dump() for item in kline_response.items],
            account=account,
            positions=positions,
            recent_orders=recent_orders,
            risk_config=self.config.get("risk", {}) or {},
            ai_config=self.ai_config,
            macro=macro,
        )
        summary = AiSignalContextBuilder.summarize(context)
        summary.update(project_context)
        summary["runtime_summary"] = ProjectAssistantContextBuilder.runtime_summary(
            account=account,
            positions=positions,
            recent_orders=recent_orders,
            quote=quote,
            macro=macro,
        )
        workspace_state = dict(summary.get("workspace_state", {}))
        workspace_state.update(
            {
                "latest_price": quote.get("price", 0),
                "quote_source": quote.get("source", ""),
                "account_cash": account.get("cash"),
                "account_equity": account.get("equity") or account.get("total_equity"),
                "positions_count": len(positions or []),
                "recent_orders_count": len(recent_orders or []),
                "auto_trading_state": self.auto_trading_engine.state,
                "auto_loop_running": bool(self.auto_trading_engine.loop_running),
            }
        )
        summary["workspace_state"] = workspace_state
        summary["risk_block_summary"] = {
            **(summary.get("risk_block_summary", {}) or {}),
            "max_order_notional": self.auto_trading_engine.config.max_order_notional,
            "max_positions": self.auto_trading_engine.config.max_positions,
            "real_trading_enabled": False,
            "recent_rejections": [
                item
                for item in (recent_orders or [])[:5]
                if str(item.get("status", "")).lower() in {"rejected", "cancelled"}
            ],
        }
        summary["advisory_only"] = True
        summary["paper_order_allowed_by_ai"] = False
        summary["testnet_order_allowed_by_ai"] = False
        summary["real_order_allowed_by_ai"] = False
        return summary

    def _ai_record_response(self, record: dict[str, Any]) -> AiSignalRecordResponse:
        return AiSignalRecordResponse(**record)

    def _ai_chat_session_response(self, record: dict[str, Any]) -> AiChatSessionResponse:
        return AiChatSessionResponse(**record)

    def _ai_chat_message_response(self, record: dict[str, Any]) -> AiChatMessageResponse:
        return AiChatMessageResponse(**record)

    async def get_connection_health(self) -> ConnectionHealthResponse:
        return ConnectionHealthResponse(**self.provider.get_connection_health())

    async def _load_strategy_market_data(self, symbols: list[str], period: str, limit: int) -> dict[str, list[dict[str, Any]]]:
        normalized_symbols = self._normalize_symbols(symbols)
        if not normalized_symbols:
            raise ApiError(400, "No valid symbols were provided for strategy market data.", ErrorCode.STRATEGY_CONFIG_INVALID)

        async def load_one(symbol: str) -> tuple[str, list[dict[str, Any]], str | None]:
            try:
                response = await self.get_klines(symbol=symbol, period=period, limit=limit)
                rows = [item.model_dump() for item in response.items]
                if not rows:
                    return symbol, [], "empty kline response"
                return symbol, rows, None
            except Exception as exc:  # noqa: BLE001 - keep other symbols usable when one market request fails.
                return symbol, [], str(exc)

        results = await asyncio.gather(*(load_one(symbol) for symbol in normalized_symbols))
        market_data: dict[str, list[dict[str, Any]]] = {}
        failures: dict[str, str] = {}
        for symbol, rows, error in results:
            if rows:
                market_data[symbol] = rows
            elif error:
                failures[symbol] = error
        if not market_data:
            raise ApiError(
                503,
                "Strategy market data is unavailable for all requested symbols.",
                ErrorCode.STRATEGY_CONFIG_INVALID,
                details={"symbols": normalized_symbols, "failures": failures},
            )
        return market_data

    async def _load_multi_timeframe_market_data(
        self,
        symbols: list[str],
        timeframes: list[str],
        limit: int,
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        import asyncio

        async def load_one(timeframe: str) -> tuple[str, dict[str, list[dict[str, Any]]]]:
            return timeframe, await self._load_strategy_market_data(symbols, timeframe, limit)

        tasks = [load_one(timeframe) for timeframe in timeframes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        market_data: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for result in results:
            if isinstance(result, Exception):
                continue
            timeframe, data = result
            market_data[timeframe] = data
        return market_data

    def _detect_regimes_from_market_data(
        self,
        market_data: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, str], dict[str, float]]:
        regimes: dict[str, str] = {}
        regime_scores: dict[str, float] = {}
        detector = RegimeDetector(config=self.regime_detector_config)
        for symbol, candles in market_data.items():
            closes = [float(row.get("close", 0) or 0) for row in candles]
            highs = [float(row.get("high", 0) or 0) for row in candles]
            lows = [float(row.get("low", 0) or 0) for row in candles]
            volumes = [float(row.get("volume", 0) or 0) for row in candles]
            result = detector.detect(closes=closes, highs=highs, lows=lows, volumes=volumes, symbol=symbol)
            regimes[symbol] = result.regime.value
            regime_scores[symbol] = result.score
        return regimes, regime_scores

    def _normalize_symbols(self, symbols: list[str]) -> list[str]:
        normalized: list[str] = []
        quote_currency = self.crypto_config.get("default_quote_currency", "USDT")
        for symbol in symbols:
            item = normalize_crypto_symbol(symbol, quote_currency)
            if item and item not in normalized:
                normalized.append(item)
        return normalized

    def _normalize_quote_filter(self, quote: str | None) -> str | None:
        value = str(quote or "").strip().upper()
        if not value or value == "ALL":
            return None
        if "/" in value:
            value = value.split("/")[-1]
        return value

    def _normalize_market_type(self, market_type: str | None) -> str:
        try:
            return normalize_market_type(market_type)
        except ValueError as exc:
            raise ApiError(400, str(exc), ErrorCode.BAD_REQUEST) from exc
