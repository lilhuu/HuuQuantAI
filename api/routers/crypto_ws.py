"""WebSocket endpoints for live crypto market streams."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from api.dependencies import authenticate_websocket, get_crypto_service
from core.binance_market_stream import send_initial_market_snapshots, stream_binance_market
from core.binance_public_market_provider import normalize_instrument_symbol, normalize_market_type
from core.crypto_market_data_provider import normalize_crypto_symbol


router = APIRouter(tags=["crypto-websocket"])


def _parse_symbols(value: str | None, market_type: str = "spot") -> list[str]:
    if not value:
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    if market_type == "spot":
        items = [normalize_crypto_symbol(item) for item in value.split(",")]
    else:
        items = [normalize_instrument_symbol(item, market_type) for item in value.split(",")]
    items = [item for item in items if item]
    return items or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


@router.websocket("/ws/crypto")
async def crypto_market_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await authenticate_websocket(websocket)
    except RuntimeError:
        return

    try:
        market_type = normalize_market_type(websocket.query_params.get("market_type") or "spot")
    except ValueError:
        market_type = "spot"
    symbols = _parse_symbols(websocket.query_params.get("symbols"), market_type=market_type)
    period = str(websocket.query_params.get("period") or "1h")
    all_market = str(websocket.query_params.get("all_market") or "").lower() in {"1", "true", "yes"}
    selected_symbol = (
        normalize_crypto_symbol(websocket.query_params.get("selected_symbol") or symbols[0])
        if market_type == "spot"
        else normalize_instrument_symbol(websocket.query_params.get("selected_symbol") or symbols[0], market_type)
    )
    try:
        depth_limit = int(websocket.query_params.get("depth_limit") or 20)
    except ValueError:
        depth_limit = 20
    depth_limit = max(1, min(depth_limit, 20))

    service = get_crypto_service()
    proxy = (service.crypto_config.get("proxy") or "").strip() or None
    await websocket.send_json(
        {
            "type": "crypto_status",
            "state": "snapshot_loading",
            "message": "正在加载 REST 行情快照",
        }
    )
    try:
        snapshot_kwargs = {
            "symbols": symbols,
            "period": period,
            "selected_symbol": selected_symbol,
            "depth_limit": depth_limit,
            "all_market": all_market,
        }
        stream_kwargs = {
            **snapshot_kwargs,
            "proxy": proxy,
        }
        if market_type != "spot":
            snapshot_kwargs["market_type"] = market_type
            stream_kwargs["market_type"] = market_type
        await send_initial_market_snapshots(websocket, service, **snapshot_kwargs)
        await stream_binance_market(websocket, service, **stream_kwargs)
    except WebSocketDisconnect:
        return
