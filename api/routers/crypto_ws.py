"""WebSocket endpoints for live crypto market streams."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from api.dependencies import authenticate_websocket, get_crypto_service
from core.binance_market_stream import send_initial_market_snapshots, stream_binance_market
from core.crypto_market_data_provider import normalize_crypto_symbol


router = APIRouter(tags=["crypto-websocket"])


def _parse_symbols(value: str | None) -> list[str]:
    if not value:
        return ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    items = [normalize_crypto_symbol(item) for item in value.split(",")]
    items = [item for item in items if item]
    return items or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


@router.websocket("/ws/crypto")
async def crypto_market_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await authenticate_websocket(websocket)
    except RuntimeError:
        return

    symbols = _parse_symbols(websocket.query_params.get("symbols"))
    period = str(websocket.query_params.get("period") or "1h")
    selected_symbol = normalize_crypto_symbol(websocket.query_params.get("selected_symbol") or symbols[0])
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
        await send_initial_market_snapshots(
            websocket,
            service,
            symbols=symbols,
            period=period,
            selected_symbol=selected_symbol,
            depth_limit=depth_limit,
        )
        await stream_binance_market(
            websocket,
            service,
            symbols=symbols,
            period=period,
            selected_symbol=selected_symbol,
            depth_limit=depth_limit,
            proxy=proxy,
        )
    except WebSocketDisconnect:
        return
