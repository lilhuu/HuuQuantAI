"""Binance Spot WebSocket helpers for the local crypto market proxy."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import WebSocket

from core.crypto_market_data_provider import SUPPORTED_TIMEFRAMES, normalize_crypto_symbol


BINANCE_SPOT_WS_BASE = "wss://stream.binance.com:9443/stream"


def build_binance_stream_url(
    symbols: Iterable[str],
    period: str = "1h",
    depth_limit: int = 20,
    selected_symbol: Optional[str] = None,
) -> str:
    """Build a Binance combined stream URL for ticker, one kline, and one depth stream."""
    normalized_symbols = _unique_symbols(symbols)
    primary = normalize_crypto_symbol(selected_symbol) if selected_symbol else ""
    if not primary or primary not in normalized_symbols:
        primary = normalized_symbols[0] if normalized_symbols else "BTC/USDT"

    normalized_period = SUPPORTED_TIMEFRAMES.get(str(period or "1h"), "1h")
    normalized_depth = 5 if depth_limit <= 5 else 10 if depth_limit <= 10 else 20
    streams = []
    for symbol in normalized_symbols or [primary]:
        stream_symbol = _binance_symbol(symbol)
        streams.append(f"{stream_symbol}@ticker")
    primary_stream_symbol = _binance_symbol(primary)
    streams.append(f"{primary_stream_symbol}@kline_{normalized_period}")
    streams.append(f"{primary_stream_symbol}@depth{normalized_depth}@1000ms")
    return f"{BINANCE_SPOT_WS_BASE}?streams={'/'.join(streams)}"


def normalize_binance_stream_message(raw_payload: str | dict[str, Any]) -> Optional[dict[str, Any]]:
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
        return {"type": "crypto_ticker", "item": normalize_binance_ticker(data)}
    if event_type == "kline" and isinstance(data.get("k"), dict):
        return {"type": "crypto_kline", "item": normalize_binance_kline(data["k"])}
    if "bids" in data or "asks" in data:
        return {"type": "crypto_depth", "item": normalize_binance_depth(data, stream)}
    if "b" in data and "a" in data and "@depth" in stream:
        return {"type": "crypto_depth", "item": normalize_binance_depth(data, stream)}
    return None


def normalize_binance_ticker(data: dict[str, Any]) -> dict[str, Any]:
    symbol = _symbol_from_binance(data.get("s"))
    price = _float(data.get("c"))
    open_price = _float(data.get("o"))
    change_amount = _float(data.get("p"))
    percentage = _float(data.get("P"))
    return {
        "symbol": symbol,
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


def normalize_binance_kline(data: dict[str, Any]) -> dict[str, Any]:
    symbol = _symbol_from_binance(data.get("s"))
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


def normalize_binance_depth(data: dict[str, Any], stream: str = "") -> dict[str, Any]:
    symbol = _symbol_from_binance(data.get("s") or stream.split("@", 1)[0])
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
) -> None:
    """Send REST snapshots before the Binance stream starts producing live ticks."""
    try:
        quotes = await service.get_quotes(symbols)
        for item in quotes.items:
            await websocket.send_json({"type": "crypto_ticker", "item": item.model_dump()})
    except Exception as exc:
        await websocket.send_json(_error_message(f"REST 行情快照不可用: {exc}"))

    try:
        klines = await service.get_klines(selected_symbol, period=period, limit=200)
        for item in klines.items:
            await websocket.send_json({"type": "crypto_kline", "item": item.model_dump()})
    except Exception as exc:
        await websocket.send_json(_error_message(f"REST K 线快照不可用: {exc}"))

    try:
        depth = await service.get_orderbook(selected_symbol, limit=depth_limit)
        await websocket.send_json({"type": "crypto_depth", "item": depth.model_dump()})
    except Exception as exc:
        await websocket.send_json(_error_message(f"REST 盘口快照不可用: {exc}"))


async def stream_binance_market(
    websocket: WebSocket,
    service: Any,
    symbols: list[str],
    period: str = "1h",
    depth_limit: int = 20,
    selected_symbol: str | None = None,
) -> None:
    """Proxy Binance Spot market streams to the connected frontend websocket."""
    try:
        import websockets
    except ImportError as exc:
        await websocket.send_json(_error_message(f"websockets 依赖未安装: {exc}"))
        return

    normalized_symbols = _unique_symbols(symbols) or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    selected = normalize_crypto_symbol(selected_symbol) or normalized_symbols[0]
    reconnect_attempt = 0
    while True:
        reconnect_attempt += 1
        url = build_binance_stream_url(normalized_symbols, period=period, depth_limit=depth_limit, selected_symbol=selected)
        await websocket.send_json(
            {
                "type": "crypto_status",
                "state": "connecting" if reconnect_attempt == 1 else "reconnecting",
                "message": "正在连接 Binance 实时行情",
                "timestamp": _now(),
            }
        )
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as upstream:
                reconnect_attempt = 0
                await websocket.send_json(
                    {
                        "type": "crypto_status",
                        "state": "connected",
                        "message": "Binance 实时行情已连接",
                        "timestamp": _now(),
                    }
                )
                async for raw in upstream:
                    message = normalize_binance_stream_message(raw)
                    if not message:
                        continue
                    if message["type"] == "crypto_ticker":
                        service.record_quote_snapshots([message["item"]])
                    elif message["type"] == "crypto_kline":
                        service.record_klines([message["item"]])
                    await websocket.send_json(message)
        except Exception as exc:
            await websocket.send_json(_error_message(f"Binance 实时行情不可用: {exc}"))
            delay = min(30, 2**min(reconnect_attempt, 5))
            await websocket.send_json(
                {
                    "type": "crypto_status",
                    "state": "reconnecting",
                    "message": f"{delay} 秒后重连 Binance 实时行情",
                    "timestamp": _now(),
                }
            )
            await asyncio.sleep(delay)


def _unique_symbols(symbols: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for symbol in symbols:
        item = normalize_crypto_symbol(symbol)
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _binance_symbol(symbol: str) -> str:
    return normalize_crypto_symbol(symbol).replace("/", "").lower()


def _symbol_from_binance(value: Any, quote: str = "USDT") -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
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
