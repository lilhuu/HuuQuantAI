"""Binance Spot WebSocket helpers for the local crypto market proxy."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from core.binance_public_market_provider import normalize_instrument_symbol, normalize_market_type
from core.crypto_market_data_provider import SUPPORTED_TIMEFRAMES, normalize_crypto_symbol


BINANCE_WS_BASES = {
    "spot": "wss://stream.binance.com:9443/stream",
    "um_futures": "wss://fstream.binance.com/stream",
    "cm_futures": "wss://dstream.binance.com/stream",
    "options": "wss://nbstream.binance.com/eoptions/stream",
}
MINI_TICKER_SYMBOL_THRESHOLD = 50
MINI_TICKER_THROTTLE_SECONDS = 2.0
BINANCE_QUOTE_ASSETS = (
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
    "TRY",
    "EUR",
    "BRL",
    "AUD",
    "GBP",
    "RUB",
    "UAH",
    "ZAR",
    "BIDR",
)


def _websocket_can_send(websocket: WebSocket) -> bool:
    application_state = getattr(websocket, "application_state", None)
    client_state = getattr(websocket, "client_state", None)
    if application_state is not None and application_state is not WebSocketState.CONNECTED:
        return False
    return client_state is not WebSocketState.DISCONNECTED


async def _send_json_if_connected(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    if not _websocket_can_send(websocket):
        return False
    try:
        await websocket.send_json(payload)
    except WebSocketDisconnect:
        return False
    except RuntimeError as exc:
        if not _websocket_can_send(websocket) or "close message" in str(exc).lower():
            return False
        raise
    return True


def build_binance_stream_url(
    symbols: Iterable[str],
    period: str = "1h",
    depth_limit: int = 20,
    selected_symbol: Optional[str] = None,
    all_market: bool = False,
    market_type: str = "spot",
) -> tuple[str, bool]:
    """Build a Binance combined stream URL and whether miniTicker mode is active.

    Returns (url, use_mini_ticker).
    When symbols exceed MINI_TICKER_SYMBOL_THRESHOLD, uses !miniTicker@arr
    instead of individual @ticker streams.
    """
    normalized_market_type = normalize_market_type(market_type)
    normalized_symbols = _unique_symbols(symbols, normalized_market_type)
    primary = normalize_instrument_symbol(selected_symbol, normalized_market_type) if selected_symbol else ""
    if not primary or primary not in normalized_symbols:
        primary = normalized_symbols[0] if normalized_symbols else "BTC/USDT"

    normalized_period = SUPPORTED_TIMEFRAMES.get(str(period or "1h"), "1h")
    normalized_depth = 5 if depth_limit <= 5 else 10 if depth_limit <= 10 else 20
    use_mini_ticker = all_market or len(normalized_symbols) >= MINI_TICKER_SYMBOL_THRESHOLD

    streams = []
    if use_mini_ticker:
        streams.append("!miniTicker@arr")
    else:
        for symbol in normalized_symbols or [primary]:
            stream_symbol = _binance_symbol(symbol)
            streams.append(f"{stream_symbol}@ticker")
    primary_stream_symbol = _binance_symbol(primary)
    streams.append(f"{primary_stream_symbol}@kline_{normalized_period}")
    streams.append(f"{primary_stream_symbol}@depth{normalized_depth}@1000ms")
    return f"{BINANCE_WS_BASES[normalized_market_type]}?streams={'/'.join(streams)}", use_mini_ticker


def normalize_binance_stream_message(raw_payload: str | dict[str, Any], market_type: str = "spot") -> Optional[dict[str, Any]]:
    """Convert Binance combined-stream messages to the app's stable message shapes."""
    if isinstance(raw_payload, str):
        payload = json.loads(raw_payload)
    else:
        payload = raw_payload
    stream = str(payload.get("stream") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None

    event_type = str(data.get("e") or "")
    if event_type == "serverShutdown":
        return {
            "type": "crypto_status",
            "state": "reconnecting",
            "message": "Binance 服务器即将维护，正在准备重连",
            "timestamp": _iso_from_ms(data.get("E")),
        }
    if event_type == "24hrTicker":
        return {"type": "crypto_ticker", "item": normalize_binance_ticker(data, market_type=market_type)}
    if event_type == "kline" and isinstance(data.get("k"), dict):
        return {"type": "crypto_kline", "item": normalize_binance_kline(data["k"], market_type=market_type)}
    if "bids" in data or "asks" in data:
        return {"type": "crypto_depth", "item": normalize_binance_depth(data, stream, market_type=market_type)}
    if "b" in data and "a" in data and "@depth" in stream:
        return {"type": "crypto_depth", "item": normalize_binance_depth(data, stream, market_type=market_type)}
    return None


def normalize_mini_ticker_message(raw_payload: str | dict[str, Any], market_type: str = "spot") -> Optional[dict[str, Any]]:
    """Parse a !miniTicker@arr message, returning None if it is not a miniTicker payload."""
    if isinstance(raw_payload, str):
        payload = json.loads(raw_payload)
    else:
        payload = raw_payload
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        items = [_normalize_mini_ticker_item(item, market_type=market_type) for item in data]
        return {"type": "crypto_ticker_batch", "items": [item for item in items if item]}
    return None


def _normalize_mini_ticker_item(item: dict[str, Any], market_type: str = "spot") -> Optional[dict[str, Any]]:
    """Convert a single miniTicker array element to our standard ticker shape."""
    symbol = _symbol_from_binance(item.get("s"), market_type=market_type)
    if not symbol:
        return None
    price = _float(item.get("c"))
    open_price = _float(item.get("o"))
    change_amount = price - open_price if open_price > 0 else 0.0
    return {
        "symbol": symbol,
        "market_type": normalize_market_type(market_type),
        "price": price,
        "open": open_price,
        "high": _float(item.get("h")),
        "low": _float(item.get("l")),
        "volume": _float(item.get("v")),
        "amount": _float(item.get("q")),
        "change": (change_amount / open_price) if open_price > 0 else 0.0,
        "change_amount": change_amount,
        "bid": 0.0,
        "ask": 0.0,
        "timestamp": _iso_from_ms(item.get("E")),
        "source": "binance_ws_mini",
    }


def normalize_binance_ticker(data: dict[str, Any], market_type: str = "spot") -> dict[str, Any]:
    symbol = _symbol_from_binance(data.get("s"), market_type=market_type)
    price = _float(data.get("c"))
    open_price = _float(data.get("o"))
    change_amount = _float(data.get("p"))
    percentage = _float(data.get("P"))
    return {
        "symbol": symbol,
        "market_type": normalize_market_type(market_type),
        "price": price,
        "open": open_price,
        "high": _float(data.get("h")),
        "low": _float(data.get("l")),
        "volume": _float(data.get("v")),
        "amount": _float(data.get("q")),
        "change": percentage / 100 if percentage else ((change_amount / open_price) if open_price else 0.0),
        "change_amount": change_amount,
        "bid": _float(data.get("b")),
        "ask": _float(data.get("a")),
        "timestamp": _iso_from_ms(data.get("E")),
        "source": "binance_ws",
    }


def normalize_binance_kline(data: dict[str, Any], market_type: str = "spot") -> dict[str, Any]:
    symbol = _symbol_from_binance(data.get("s"), market_type=market_type)
    period = str(data.get("i") or "1m")
    close = _float(data.get("c"))
    volume = _float(data.get("v"))
    return {
        "symbol": symbol,
        "period": period,
        "start_time": _iso_from_ms(data.get("t")),
        "end_time": _iso_from_ms(data.get("T")),
        "open": _float(data.get("o")),
        "high": _float(data.get("h")),
        "low": _float(data.get("l")),
        "close": close,
        "volume": volume,
        "amount": _float(data.get("q")) or close * volume,
        "count": int(data.get("n") or 0),
        "source": "binance_ws",
    }


def normalize_binance_depth(data: dict[str, Any], stream: str = "", market_type: str = "spot") -> dict[str, Any]:
    symbol = _symbol_from_binance(data.get("s") or stream.split("@", 1)[0], market_type=market_type)
    bids = data.get("bids") if "bids" in data else data.get("b")
    asks = data.get("asks") if "asks" in data else data.get("a")
    return {
        "symbol": symbol,
        "bids": _normalize_levels(bids),
        "asks": _normalize_levels(asks),
        "timestamp": _iso_from_ms(data.get("E")),
        "source": "binance_ws",
    }


async def send_initial_market_snapshots(
    websocket: WebSocket,
    service: Any,
    symbols: list[str],
    period: str,
    selected_symbol: str,
    depth_limit: int,
    all_market: bool = False,
    market_type: str = "spot",
) -> None:
    """Send REST snapshots before the Binance stream starts producing live ticks."""
    try:
        quotes = await service.get_quotes(None, quote="ALL", limit=0, offset=0, market_type=market_type) if all_market else await service.get_quotes(symbols, market_type=market_type)
        for item in quotes.items:
            if not await _send_json_if_connected(
                websocket,
                {"type": "crypto_ticker", "item": item.model_dump()},
            ):
                return
    except Exception as exc:
        if not await _send_json_if_connected(websocket, _error_message(f"REST 行情快照不可用: {exc}")):
            return

    try:
        klines = await service.get_klines(selected_symbol, period=period, limit=200, market_type=market_type)
        for item in klines.items:
            if not await _send_json_if_connected(
                websocket,
                {"type": "crypto_kline", "item": item.model_dump()},
            ):
                return
    except Exception as exc:
        if not await _send_json_if_connected(websocket, _error_message(f"REST K 线快照不可用: {exc}")):
            return

    try:
        depth = await service.get_orderbook(selected_symbol, limit=depth_limit, market_type=market_type)
        await _send_json_if_connected(websocket, {"type": "crypto_depth", "item": depth.model_dump()})
    except Exception as exc:
        await _send_json_if_connected(websocket, _error_message(f"REST 盘口快照不可用: {exc}"))


async def stream_binance_market(
    websocket: WebSocket,
    service: Any,
    symbols: list[str],
    period: str = "1h",
    depth_limit: int = 20,
    selected_symbol: str | None = None,
    proxy: str | None = None,
    all_market: bool = False,
    market_type: str = "spot",
) -> None:
    """Proxy Binance Spot market streams to the connected frontend websocket."""
    try:
        import websockets
    except ImportError as exc:
        await _send_json_if_connected(websocket, _error_message(f"websockets 依赖未安装: {exc}"))
        return

    normalized_market_type = normalize_market_type(market_type)
    normalized_symbols = _unique_symbols(symbols, normalized_market_type) or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    selected = normalize_instrument_symbol(selected_symbol, normalized_market_type) or normalized_symbols[0]
    use_mini_ticker = all_market or len(normalized_symbols) >= MINI_TICKER_SYMBOL_THRESHOLD
    reconnect_attempt = 0
    last_mini_ticker_send = 0.0
    while True:
        reconnect_attempt += 1
        url, _ = build_binance_stream_url(
            normalized_symbols, period=period, depth_limit=depth_limit, selected_symbol=selected, all_market=all_market
            , market_type=normalized_market_type
        )
        if not await _send_json_if_connected(
            websocket,
            {
                "type": "crypto_status",
                "state": "connecting" if reconnect_attempt == 1 else "reconnecting",
                "message": "正在连接 Binance 实时行情",
                "timestamp": _now(),
            },
        ):
            return
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5, proxy=proxy or True) as upstream:
                reconnect_attempt = 0
                if not await _send_json_if_connected(
                    websocket,
                    {
                        "type": "crypto_status",
                        "state": "connected",
                        "message": "Binance 实时行情已连接",
                        "timestamp": _now(),
                    },
                ):
                    return
                async for raw in upstream:
                    if use_mini_ticker:
                        batch = normalize_mini_ticker_message(raw, market_type=normalized_market_type)
                        if batch and batch.get("type") == "crypto_ticker_batch":
                            now = time.monotonic()
                            if now - last_mini_ticker_send >= MINI_TICKER_THROTTLE_SECONDS:
                                last_mini_ticker_send = now
                                for item in batch["items"]:
                                    if not await _send_json_if_connected(
                                        websocket,
                                        {"type": "crypto_ticker", "item": item},
                                    ):
                                        return
                                try:
                                    service.record_quote_snapshots(batch["items"])
                                except Exception:
                                    pass
                            continue
                    message = normalize_binance_stream_message(raw, market_type=normalized_market_type)
                    if not message:
                        continue
                    if message["type"] == "crypto_ticker":
                        service.record_quote_snapshots([message["item"]])
                    elif message["type"] == "crypto_kline":
                        service.record_klines([message["item"]])
                    if not await _send_json_if_connected(websocket, message):
                        return
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not await _send_json_if_connected(
                websocket,
                _error_message(f"Binance 实时行情不可用: {exc}"),
            ):
                return
            delay = min(30, 2 ** min(reconnect_attempt, 5))
            if not await _send_json_if_connected(
                websocket,
                {
                    "type": "crypto_status",
                    "state": "reconnecting",
                    "message": f"{delay} 秒后重连 Binance 实时行情",
                    "timestamp": _now(),
                },
            ):
                return
            await asyncio.sleep(delay)


def _unique_symbols(symbols: Iterable[str], market_type: str = "spot") -> list[str]:
    normalized: list[str] = []
    for symbol in symbols:
        item = normalize_instrument_symbol(symbol, market_type)
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _binance_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("/", "").lower()


def _symbol_from_binance(value: Any, quote: str = "USDT", market_type: str = "spot") -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    normalized_market_type = normalize_market_type(market_type)
    if normalized_market_type == "options" or "_" in text:
        return text
    if "/" not in text:
        for quote_asset in BINANCE_QUOTE_ASSETS:
            if text.endswith(quote_asset) and len(text) > len(quote_asset):
                return f"{text[:-len(quote_asset)]}/{quote_asset}"
    return normalize_crypto_symbol(text, quote_currency=quote)


def _normalize_levels(levels: Any) -> list[list[float]]:
    items = []
    for level in levels or []:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        items.append([_float(level[0]), _float(level[1])])
    return items


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


def _error_message(message: str) -> dict[str, Any]:
    return {
        "type": "crypto_error",
        "message": message,
        "recoverable": True,
        "timestamp": _now(),
    }
