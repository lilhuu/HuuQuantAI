"""Official Binance public market-data provider.

This module uses Binance public REST endpoints directly for markets that CCXT
does not model uniformly enough for this app's market center.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


SUPPORTED_MARKET_TYPES = {"spot", "um_futures", "cm_futures", "options"}
KNOWN_QUOTE_ASSETS = (
    "FDUSD",
    "USDT",
    "USDC",
    "TUSD",
    "BUSD",
    "USDP",
    "DAI",
    "BTC",
    "ETH",
    "BNB",
    "USD",
    "TRY",
    "EUR",
    "BRL",
    "AUD",
    "GBP",
)


MARKET_CONFIG: dict[str, dict[str, str]] = {
    "spot": {
        "base_url": "https://api.binance.com",
        "exchange_info": "/api/v3/exchangeInfo",
        "ticker_24h": "/api/v3/ticker/24hr",
        "klines": "/api/v3/klines",
        "depth": "/api/v3/depth",
    },
    "um_futures": {
        "base_url": "https://fapi.binance.com",
        "exchange_info": "/fapi/v1/exchangeInfo",
        "ticker_24h": "/fapi/v1/ticker/24hr",
        "klines": "/fapi/v1/klines",
        "depth": "/fapi/v1/depth",
        "mark_price": "/fapi/v1/premiumIndex",
        "open_interest": "/fapi/v1/openInterest",
        "funding_rate": "/fapi/v1/fundingRate",
    },
    "cm_futures": {
        "base_url": "https://dapi.binance.com",
        "exchange_info": "/dapi/v1/exchangeInfo",
        "ticker_24h": "/dapi/v1/ticker/24hr",
        "klines": "/dapi/v1/klines",
        "depth": "/dapi/v1/depth",
        "mark_price": "/dapi/v1/premiumIndex",
        "open_interest": "/dapi/v1/openInterest",
        "funding_rate": "/dapi/v1/fundingRate",
    },
    "options": {
        "base_url": "https://eapi.binance.com",
        "exchange_info": "/eapi/v1/exchangeInfo",
        "ticker_24h": "/eapi/v1/ticker",
        "klines": "/eapi/v1/klines",
        "depth": "/eapi/v1/depth",
        "mark_price": "/eapi/v1/mark",
        "open_interest": "/eapi/v1/openInterest",
    },
}


class BinancePublicMarketProvider:
    """Direct Binance public REST adapter for Spot, futures and options."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.timeout = float(self.config.get("timeout", 10) or 10)
        self.user_agent = str(self.config.get("user_agent") or "HUU-Auto-Trader/1.0")

    def load_markets(self, market_type: str = "spot") -> list[dict[str, Any]]:
        market_type = normalize_market_type(market_type)
        payload = self._request(market_type, MARKET_CONFIG[market_type]["exchange_info"])
        symbols = payload.get("symbols") if isinstance(payload, dict) else payload
        items = [self._normalize_instrument(market_type, row) for row in symbols or []]
        return sorted([item for item in items if item.get("symbol")], key=lambda item: item["symbol"])

    def fetch_all_tickers(self, market_type: str = "spot", quote: str | None = None) -> list[dict[str, Any]]:
        market_type = normalize_market_type(market_type)
        payload = self._request(market_type, MARKET_CONFIG[market_type]["ticker_24h"])
        rows = payload if isinstance(payload, list) else [payload]
        quote_filter = normalize_quote_filter(quote)
        items = [self._normalize_ticker(market_type, row) for row in rows or []]
        if quote_filter:
            items = [item for item in items if str(item.get("quote") or "").upper() == quote_filter]
        return sorted([item for item in items if item.get("symbol")], key=lambda item: item["symbol"])

    def fetch_quotes(self, market_type: str, symbols: list[str]) -> list[dict[str, Any]]:
        wanted = {normalize_instrument_symbol(symbol, market_type) for symbol in symbols}
        return [item for item in self.fetch_all_tickers(market_type) if item["symbol"] in wanted]

    def fetch_klines(self, market_type: str, symbol: str, period: str = "1h", limit: int = 200) -> list[dict[str, Any]]:
        market_type = normalize_market_type(market_type)
        market_symbol = to_binance_symbol(symbol, market_type)
        safe_limit = max(1, min(int(limit or 200), 1000))
        payload = self._request(
            market_type,
            MARKET_CONFIG[market_type]["klines"],
            {"symbol": market_symbol, "interval": str(period or "1h"), "limit": safe_limit},
        )
        items: list[dict[str, Any]] = []
        for row in payload or []:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            open_time, open_price, high, low, close, volume = row[:6]
            close_time = row[6] if len(row) > 6 else open_time
            amount = row[7] if len(row) > 7 else _float(close) * _float(volume)
            count = row[8] if len(row) > 8 else 0
            items.append(
                {
                    "symbol": normalize_instrument_symbol(symbol, market_type),
                    "period": str(period or "1h"),
                    "start_time": _iso_from_ms(open_time),
                    "end_time": _iso_from_ms(close_time),
                    "open": _float(open_price),
                    "high": _float(high),
                    "low": _float(low),
                    "close": _float(close),
                    "volume": _float(volume),
                    "amount": _float(amount),
                    "count": int(_float(count)),
                    "source": f"binance_{market_type}",
                }
            )
        return items

    def fetch_order_book(self, market_type: str, symbol: str, limit: int = 20) -> dict[str, Any]:
        market_type = normalize_market_type(market_type)
        safe_limit = max(1, min(int(limit or 20), 1000))
        payload = self._request(
            market_type,
            MARKET_CONFIG[market_type]["depth"],
            {"symbol": to_binance_symbol(symbol, market_type), "limit": safe_limit},
        )
        return {
            "symbol": normalize_instrument_symbol(symbol, market_type),
            "bids": _normalize_levels(payload.get("bids") if isinstance(payload, dict) else []),
            "asks": _normalize_levels(payload.get("asks") if isinstance(payload, dict) else []),
            "timestamp": _iso_from_ms(payload.get("E") or payload.get("lastUpdateId")) if isinstance(payload, dict) else _now(),
            "source": f"binance_{market_type}",
        }

    def fetch_derivative_metrics(self, market_type: str, symbol: str) -> dict[str, Any]:
        market_type = normalize_market_type(market_type)
        if market_type == "spot":
            return {
                "market_type": "spot",
                "symbol": normalize_instrument_symbol(symbol, market_type),
                "source": "binance_spot",
                "timestamp": _now(),
            }
        normalized_symbol = normalize_instrument_symbol(symbol, market_type)
        market_symbol = to_binance_symbol(symbol, market_type)
        config = MARKET_CONFIG[market_type]
        metrics: dict[str, Any] = {
            "market_type": market_type,
            "symbol": normalized_symbol,
            "mark_price": 0.0,
            "index_price": 0.0,
            "funding_rate": 0.0,
            "next_funding_time": None,
            "open_interest": 0.0,
            "timestamp": _now(),
            "source": f"binance_{market_type}",
        }
        mark_path = config.get("mark_price")
        if mark_path:
            mark_payload = self._request(market_type, mark_path, {"symbol": market_symbol})
            mark_item = mark_payload[0] if isinstance(mark_payload, list) and mark_payload else mark_payload
            if isinstance(mark_item, dict):
                metrics["mark_price"] = _float(mark_item.get("markPrice"))
                metrics["index_price"] = _float(mark_item.get("indexPrice"))
                metrics["funding_rate"] = _float(mark_item.get("lastFundingRate"))
                metrics["next_funding_time"] = _iso_from_ms(mark_item.get("nextFundingTime")) if mark_item.get("nextFundingTime") else None
                metrics["timestamp"] = _iso_from_ms(mark_item.get("time") or mark_item.get("E"))
        open_interest_path = config.get("open_interest")
        if open_interest_path:
            try:
                oi_payload = self._request(market_type, open_interest_path, {"symbol": market_symbol})
                oi_item = oi_payload[0] if isinstance(oi_payload, list) and oi_payload else oi_payload
                if isinstance(oi_item, dict):
                    metrics["open_interest"] = _float(oi_item.get("openInterest") or oi_item.get("sumOpenInterest"))
            except Exception:
                pass
        funding_path = config.get("funding_rate")
        if funding_path and not metrics["funding_rate"]:
            try:
                funding_payload = self._request(market_type, funding_path, {"symbol": market_symbol, "limit": 1})
                funding_item = funding_payload[0] if isinstance(funding_payload, list) and funding_payload else funding_payload
                if isinstance(funding_item, dict):
                    metrics["funding_rate"] = _float(funding_item.get("fundingRate"))
            except Exception:
                pass
        return metrics

    def _request(self, market_type: str, path: str, params: dict[str, Any] | None = None) -> Any:
        market_type = normalize_market_type(market_type)
        base_url = MARKET_CONFIG[market_type]["base_url"]
        query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")})
        url = f"{base_url}{path}{'?' + query if query else ''}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _normalize_instrument(self, market_type: str, item: dict[str, Any]) -> dict[str, Any]:
        if market_type == "options":
            symbol = str(item.get("symbol") or item.get("id") or "").upper()
            underlying = str(item.get("underlying") or item.get("underlyingAsset") or symbol.split("-", 1)[0]).upper()
            quote = str(item.get("quoteAsset") or item.get("quote") or "USDT").upper()
            option_type = str(item.get("side") or item.get("type") or item.get("optionType") or "").upper()
            status = "active" if str(item.get("status") or "TRADING").upper() == "TRADING" else "inactive"
            return {
                "market_type": market_type,
                "symbol": symbol,
                "base": underlying,
                "quote": quote,
                "status": status,
                "contract_type": option_type,
                "delivery_date": _iso_from_ms(item.get("expiryDate") or item.get("deliveryDate")) if (item.get("expiryDate") or item.get("deliveryDate")) else "",
                "underlying": underlying,
                "source": "binance_options",
                "updated_at": _now(),
            }
        base = str(item.get("baseAsset") or item.get("base") or "").upper()
        quote = str(item.get("quoteAsset") or item.get("quote") or item.get("marginAsset") or "").upper()
        symbol = normalize_instrument_symbol(item.get("symbol") or item.get("pair"), market_type, base=base, quote=quote)
        status = "active" if str(item.get("status") or "").upper() == "TRADING" else "inactive"
        return {
            "market_type": market_type,
            "symbol": symbol,
            "base": base or symbol.split("/", 1)[0],
            "quote": quote or _quote_from_symbol(symbol),
            "status": status,
            "contract_type": str(item.get("contractType") or "").upper(),
            "delivery_date": _iso_from_ms(item.get("deliveryDate")) if item.get("deliveryDate") else "",
            "underlying": str(item.get("underlyingType") or item.get("pair") or "").upper(),
            "source": f"binance_{market_type}",
            "updated_at": _now(),
        }

    def _normalize_ticker(self, market_type: str, item: dict[str, Any]) -> dict[str, Any]:
        symbol = normalize_instrument_symbol(item.get("symbol") or item.get("pair"), market_type)
        price = _float(item.get("lastPrice") or item.get("last") or item.get("price"))
        open_price = _float(item.get("openPrice") or item.get("open"))
        change_amount = _float(item.get("priceChange"))
        change_pct = _float(item.get("priceChangePercent"))
        change = change_pct / 100 if change_pct else ((change_amount / open_price) if open_price else 0.0)
        base, quote = _split_symbol(symbol)
        return {
            "market_type": market_type,
            "symbol": symbol,
            "base": base,
            "quote": quote,
            "price": price,
            "open": open_price,
            "high": _float(item.get("highPrice") or item.get("high")),
            "low": _float(item.get("lowPrice") or item.get("low")),
            "volume": _float(item.get("volume") or item.get("baseVolume")),
            "amount": _float(item.get("quoteVolume") or item.get("amount")),
            "change": change,
            "change_amount": change_amount,
            "bid": _float(item.get("bidPrice")),
            "ask": _float(item.get("askPrice")),
            "timestamp": _iso_from_ms(item.get("closeTime") or item.get("time")),
            "source": f"binance_{market_type}",
        }


def normalize_market_type(value: str | None) -> str:
    market_type = str(value or "spot").strip().lower()
    aliases = {
        "usdm": "um_futures",
        "usdsm": "um_futures",
        "usds_m_futures": "um_futures",
        "u_futures": "um_futures",
        "coinm": "cm_futures",
        "coin_m_futures": "cm_futures",
        "option": "options",
    }
    market_type = aliases.get(market_type, market_type)
    if market_type not in SUPPORTED_MARKET_TYPES:
        raise ValueError(f"unsupported Binance market_type: {value}")
    return market_type


def normalize_quote_filter(quote: str | None) -> str | None:
    value = str(quote or "").strip().upper()
    if not value or value == "ALL":
        return None
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    return value


def normalize_instrument_symbol(value: Any, market_type: str = "spot", base: str = "", quote: str = "") -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if market_type == "options" or "-" in text:
        return text
    if "/" in text:
        return text
    if "_" in text and market_type == "cm_futures":
        return text
    if base and quote:
        return f"{base.upper()}/{quote.upper()}"
    for quote_asset in KNOWN_QUOTE_ASSETS:
        if text.endswith(quote_asset) and len(text) > len(quote_asset):
            return f"{text[:-len(quote_asset)]}/{quote_asset}"
    return text


def to_binance_symbol(value: Any, market_type: str = "spot") -> str:
    text = str(value or "").strip().upper()
    if market_type == "options":
        return text
    if market_type == "cm_futures" and "_" in text:
        return text
    return text.replace("/", "")


def _split_symbol(symbol: str) -> tuple[str, str]:
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        return base, quote
    if "-" in symbol:
        parts = symbol.split("-")
        return parts[0], "USDT"
    return symbol, _quote_from_symbol(symbol)


def _quote_from_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol.rsplit("/", 1)[-1]
    for quote in KNOWN_QUOTE_ASSETS:
        if symbol.endswith(quote):
            return quote
    return ""


def _normalize_levels(levels: Any) -> list[list[float]]:
    normalized = []
    for row in levels or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            normalized.append([_float(row[0]), _float(row[1])])
    return normalized


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso_from_ms(value: Any) -> str:
    try:
        timestamp_ms = int(value or 0)
    except (TypeError, ValueError):
        timestamp_ms = 0
    if timestamp_ms <= 0:
        return _now()
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
