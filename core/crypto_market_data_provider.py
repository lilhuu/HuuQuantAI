"""Public cryptocurrency market data via CCXT."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from core.exchange_resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    RetryConfig,
    retry_call,
)


SUPPORTED_TIMEFRAMES = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def normalize_crypto_symbol(value: Any, quote_currency: str = "USDT") -> str:
    """Normalize common crypto symbol spellings to BASE/QUOTE."""
    text = str(value or "").strip().upper().replace("-", "/").replace("_", "/")
    if not text:
        return ""
    if "/" in text:
        base, quote = [part.strip() for part in text.split("/", 1)]
        return f"{base}/{quote}" if base and quote else ""

    quote = str(quote_currency or "USDT").strip().upper()
    if text.endswith(quote) and len(text) > len(quote):
        return f"{text[:-len(quote)]}/{quote}"
    return f"{text}/{quote}"


class CryptoMarketDataProvider:
    """Small CCXT wrapper for public quote and OHLCV reads."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.exchange_id = str(self.config.get("exchange", "binance")).strip().lower() or "binance"
        self.timeout = int(self.config.get("timeout", 10000) or 10000)
        self.default_quote_currency = str(self.config.get("default_quote_currency", "USDT") or "USDT")
        self._exchange = None
        retryable = (ConnectionError, TimeoutError, OSError, RuntimeError)
        self._retry_config = RetryConfig(
            max_retries=int(self.config.get("max_retries", 2) or 2),
            base_delay_seconds=float(self.config.get("retry_base_delay_seconds", 0.25) or 0.25),
            max_delay_seconds=float(self.config.get("retry_max_delay_seconds", 3.0) or 3.0),
            jitter=bool(self.config.get("retry_jitter", True)),
            retryable_exceptions=retryable,
        )
        self._quotes_breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=10))
        self._ohlcv_breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=5, recovery_timeout_seconds=15))
        self._orderbook_breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=10))

    def fetch_quotes(self, symbols: Iterable[str]) -> List[Dict[str, Any]]:
        return retry_call(
            self._raw_fetch_quotes,
            list(symbols),
            config=self._retry_config,
            circuit_breaker=self._quotes_breaker,
        )

    def _raw_fetch_quotes(self, symbols: Iterable[str]) -> List[Dict[str, Any]]:
        exchange = self._get_exchange()
        items: List[Dict[str, Any]] = []
        for raw_symbol in symbols:
            symbol = normalize_crypto_symbol(raw_symbol, self.default_quote_currency)
            if not symbol:
                continue
            ticker = exchange.fetch_ticker(symbol)
            items.append(self._normalize_ticker(symbol, ticker))
        return items

    def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Fetch current order book (bid/ask depth) for a symbol."""
        normalized_symbol = normalize_crypto_symbol(symbol, self.default_quote_currency)
        return retry_call(
            self._raw_fetch_order_book,
            normalized_symbol,
            limit,
            config=self._retry_config,
            circuit_breaker=self._orderbook_breaker,
            fallback=lambda: {
                "symbol": normalized_symbol,
                "bids": [],
                "asks": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "unavailable",
            },
        )

    def _raw_fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Fetch current order book without retry wrappers."""
        normalized_symbol = normalize_crypto_symbol(symbol, self.default_quote_currency)
        if not normalized_symbol:
            raise ValueError("symbol is required")

        safe_limit = max(1, min(int(limit or 20), 100))
        book = self._get_exchange().fetch_order_book(normalized_symbol, limit=safe_limit)
        return self._normalize_order_book(normalized_symbol, book)

    def fetch_funding_rate(self, symbol: str) -> Dict[str, Any] | None:
        """Fetch current perpetual funding rate when the exchange supports it."""
        exchange = self._get_exchange()
        market_symbol = self._derivative_symbol(symbol)
        if not market_symbol or not hasattr(exchange, "fetch_funding_rate"):
            return None
        try:
            rate = exchange.fetch_funding_rate(market_symbol)
        except Exception:
            return None
        return {
            "symbol": normalize_crypto_symbol(symbol, self.default_quote_currency),
            "market_symbol": market_symbol,
            "funding_rate": self._first_number(rate, "fundingRate", "funding_rate", "rate"),
            "timestamp": rate.get("datetime") or self._iso_from_ms(rate.get("timestamp")),
            "source": self.exchange_id,
        }

    def fetch_open_interest(self, symbol: str) -> Dict[str, Any] | None:
        """Fetch current perpetual open interest when the exchange supports it."""
        exchange = self._get_exchange()
        market_symbol = self._derivative_symbol(symbol)
        if not market_symbol or not hasattr(exchange, "fetch_open_interest"):
            return None
        try:
            item = exchange.fetch_open_interest(market_symbol)
        except Exception:
            return None
        return {
            "symbol": normalize_crypto_symbol(symbol, self.default_quote_currency),
            "market_symbol": market_symbol,
            "open_interest": self._first_number(item, "openInterestAmount", "openInterestValue", "openInterest"),
            "timestamp": item.get("datetime") or self._iso_from_ms(item.get("timestamp")),
            "source": self.exchange_id,
        }

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[Dict[str, Any]]:
        return retry_call(
            self._raw_fetch_ohlcv,
            symbol,
            timeframe,
            limit,
            config=self._retry_config,
            circuit_breaker=self._ohlcv_breaker,
        )

    def _raw_fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[Dict[str, Any]]:
        """Fetch OHLCV without retry wrappers."""
        normalized_symbol = normalize_crypto_symbol(symbol, self.default_quote_currency)
        if not normalized_symbol:
            raise ValueError("symbol is required")

        normalized_timeframe = SUPPORTED_TIMEFRAMES.get(str(timeframe or "1h"))
        if not normalized_timeframe:
            raise ValueError(f"unsupported crypto timeframe: {timeframe}")

        safe_limit = max(1, min(int(limit or 200), 1000))
        rows = self._get_exchange().fetch_ohlcv(normalized_symbol, timeframe=normalized_timeframe, limit=safe_limit)
        items: List[Dict[str, Any]] = []
        for row in rows or []:
            timestamp_ms, open_price, high, low, close, volume = list(row)[:6]
            start = self._iso_from_ms(timestamp_ms)
            amount = float(close or 0) * float(volume or 0)
            items.append(
                {
                    "symbol": normalized_symbol,
                    "period": normalized_timeframe,
                    "start_time": start,
                    "end_time": start,
                    "open": float(open_price or 0),
                    "high": float(high or 0),
                    "low": float(low or 0),
                    "close": float(close or 0),
                    "volume": float(volume or 0),
                    "amount": amount,
                    "count": 1,
                }
            )
        return items

    def get_connection_health(self) -> dict[str, Any]:
        """Return retry/circuit-breaker state for the public exchange endpoints."""
        return {
            "quotes": self._quotes_breaker.health(),
            "ohlcv": self._ohlcv_breaker.health(),
            "orderbook": self._orderbook_breaker.health(),
        }

    def reset_all_breakers(self) -> None:
        self._quotes_breaker.reset()
        self._ohlcv_breaker.reset()
        self._orderbook_breaker.reset()

    def _get_exchange(self):
        if self._exchange is not None:
            return self._exchange

        try:
            import ccxt  # type: ignore
        except ImportError as exc:
            raise RuntimeError("ccxt is not installed") from exc

        exchange_cls = getattr(ccxt, self.exchange_id, None)
        if exchange_cls is None:
            raise RuntimeError(f"unsupported crypto exchange: {self.exchange_id}")

        self._exchange = exchange_cls(
            {
                "enableRateLimit": True,
                "timeout": self.timeout,
            }
        )
        return self._exchange

    def _derivative_symbol(self, symbol: str) -> str:
        normalized_symbol = normalize_crypto_symbol(symbol, self.default_quote_currency)
        if not normalized_symbol:
            return ""
        exchange = self._get_exchange()
        candidates = [normalized_symbol, f"{normalized_symbol}:{self.default_quote_currency}"]
        try:
            markets = exchange.load_markets()
        except Exception:
            markets = getattr(exchange, "markets", {}) or {}

        for candidate in candidates:
            market = markets.get(candidate) if isinstance(markets, dict) else None
            if market and (market.get("swap") or market.get("linear") or market.get("contract")):
                return candidate
        for candidate in candidates:
            if isinstance(markets, dict) and candidate in markets:
                market = markets[candidate]
                if market.get("swap") or market.get("linear") or market.get("contract"):
                    return candidate
        return f"{normalized_symbol}:{self.default_quote_currency}"

    def _normalize_ticker(self, symbol: str, ticker: Dict[str, Any]) -> Dict[str, Any]:
        price = self._first_number(ticker, "last", "close", "bid", "ask")
        open_price = self._first_number(ticker, "open")
        change_amount = self._first_number(ticker, "change")
        percentage = self._first_number(ticker, "percentage")
        if not change_amount and open_price and price:
            change_amount = price - open_price
        change = percentage / 100 if percentage else ((change_amount / open_price) if open_price else 0.0)
        volume = self._first_number(ticker, "baseVolume", "volume")
        amount = self._first_number(ticker, "quoteVolume")
        timestamp = ticker.get("datetime") or self._iso_from_ms(ticker.get("timestamp"))
        return {
            "symbol": symbol,
            "price": price,
            "open": open_price,
            "high": self._first_number(ticker, "high"),
            "low": self._first_number(ticker, "low"),
            "volume": volume,
            "amount": amount,
            "change": change,
            "change_amount": change_amount,
            "bid": self._first_number(ticker, "bid"),
            "ask": self._first_number(ticker, "ask"),
            "timestamp": timestamp,
            "source": self.exchange_id,
        }

    def _normalize_order_book(self, symbol: str, book: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a CCXT order book dict into a stable response shape."""
        bids: List[List[float]] = []
        for entry in (book.get("bids") or [])[:100]:
            price = float(entry[0] if len(entry) > 0 else 0)
            amount = float(entry[1] if len(entry) > 1 else 0)
            bids.append([price, amount])

        asks: List[List[float]] = []
        for entry in (book.get("asks") or [])[:100]:
            price = float(entry[0] if len(entry) > 0 else 0)
            amount = float(entry[1] if len(entry) > 1 else 0)
            asks.append([price, amount])

        timestamp = book.get("datetime") or self._iso_from_ms(book.get("timestamp"))
        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "timestamp": timestamp,
            "source": self.exchange_id,
        }

    def _first_number(self, data: Dict[str, Any], *keys: str) -> float:
        for key in keys:
            try:
                value = float(data.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value:
                return value
        return 0.0

    def _iso_from_ms(self, value: Any) -> str:
        try:
            timestamp_ms = int(value or 0)
        except (TypeError, ValueError):
            timestamp_ms = 0
        if timestamp_ms <= 0:
            return datetime.now(timezone.utc).isoformat()
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
