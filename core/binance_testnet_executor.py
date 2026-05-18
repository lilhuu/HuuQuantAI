"""Binance Spot Testnet preparation executor.

This module deliberately does not implement mainnet trading. Testnet order
submission is guarded behind explicit configuration, encrypted local
credentials, and a confirmation phrase. The first version supports dry-run
validation only, so no exchange order is sent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.credential_manager import CredentialManager
from core.crypto_market_data_provider import normalize_crypto_symbol


DEFAULT_CONFIRMATION_PHRASE = "I_UNDERSTAND_CRYPTO_TESTNET"


@dataclass
class BinanceTestnetOrder:
    symbol: str
    action: str
    quantity: float
    price: float = 0.0
    order_type: str = "LIMIT"
    dry_run: bool = True
    client_order_id: str = ""
    status: str = "dry_run"
    message: str = ""
    created_time: datetime = field(default_factory=datetime.now)

    def to_response(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "status": self.status,
            "message": self.message,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "price": self.price,
            "order_type": self.order_type,
            "dry_run": self.dry_run,
            "created_time": self.created_time.isoformat(),
        }


class BinanceTestnetExecutor:
    """Safety-first Binance Spot Testnet adapter."""

    def __init__(self, config: dict[str, Any] | None = None, storage_config: dict[str, Any] | None = None) -> None:
        testnet_config = dict(config or {})
        storage = dict(storage_config or {})
        self.enabled = bool(testnet_config.get("enabled", False))
        self.exchange = str(testnet_config.get("exchange", "binance") or "binance").lower()
        self.base_url = str(testnet_config.get("base_url", "https://testnet.binance.vision") or "")
        self.real_trading_enabled = bool(testnet_config.get("real_trading_enabled", False))
        self.dry_run = bool(testnet_config.get("dry_run", True))
        self.required_confirmation = str(testnet_config.get("required_confirmation") or DEFAULT_CONFIRMATION_PHRASE)
        self.confirmation_phrase = str(testnet_config.get("confirm_testnet_trading") or "")
        self.mainnet_real_trading_enabled = bool(testnet_config.get("mainnet_real_trading_enabled", False))
        self.config_api_key = str(testnet_config.get("api_key") or "").strip()
        self.config_api_secret = str(testnet_config.get("api_secret") or "").strip()
        credential_path = str(
            testnet_config.get("credential_store_path")
            or storage.get("binance_testnet_credentials_path")
            or "data/binance_testnet_credentials.enc"
        )
        key_path = str(testnet_config.get("credential_key_path") or storage.get("binance_testnet_key_path") or "data/binance_testnet.key")
        self.credential_store_path = self._resolve_path(credential_path)
        self.credential_key_path = self._resolve_path(key_path)
        self._credential_manager = CredentialManager(str(self.credential_key_path))
        self._runtime_confirmation_phrase = ""

    def status(self) -> dict[str, Any]:
        credentials = self._load_credentials(mask=True)
        has_credentials = bool(credentials.get("api_key")) and bool(credentials.get("api_secret"))
        confirmation_ok = self._confirmation_ok()
        return {
            "exchange": "binance",
            "network": "testnet",
            "enabled": self.enabled,
            "base_url": self.base_url,
            "has_api_key": has_credentials,
            "api_key_preview": credentials.get("api_key", ""),
            "real_trading_enabled": False,
            "configured_real_trading_enabled": self.real_trading_enabled,
            "dry_run": self.dry_run,
            "confirmation_required": self.required_confirmation,
            "confirmation_ok": confirmation_ok,
            "testnet_orders_allowed": self.enabled and confirmation_ok and has_credentials and not self.dry_run,
            "mainnet_supported": False,
            "mainnet_real_trading_enabled": False,
            "message": self._status_message(has_credentials, confirmation_ok),
        }

    def save_credentials(self, api_key: str, api_secret: str) -> dict[str, Any]:
        api_key = str(api_key or "").strip()
        api_secret = str(api_secret or "").strip()
        if not api_key or not api_secret:
            return {**self.status(), "success": False, "message": "api_key and api_secret are required"}
        payload = {
            "api_key": api_key,
            "api_secret": api_secret,
            "network": "testnet",
            "exchange": "binance",
            "updated_at": datetime.now().isoformat(),
        }
        self.credential_store_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self._credential_manager.encrypt(json.dumps(payload, ensure_ascii=False))
        self.credential_store_path.write_bytes(encrypted)
        return {**self.status(), "success": True, "message": "Binance testnet API key saved locally with encryption"}

    def clear_credentials(self) -> dict[str, Any]:
        if self.credential_store_path.exists():
            self.credential_store_path.unlink()
        return {**self.status(), "success": True, "message": "Binance testnet credentials cleared"}

    def enable_testnet_orders(self, confirmation_phrase: str) -> dict[str, Any]:
        self._runtime_confirmation_phrase = str(confirmation_phrase or "").strip()
        if not self._confirmation_ok():
            return {**self.status(), "success": False, "message": "confirmation phrase mismatch"}
        self.enabled = True
        return {**self.status(), "success": True, "message": "testnet order gate unlocked for this runtime only"}

    def place_order(
        self,
        *,
        symbol: str,
        action: str,
        quantity: float,
        price: float = 0.0,
        order_type: str = "LIMIT",
        dry_run: bool | None = None,
    ) -> BinanceTestnetOrder:
        order = BinanceTestnetOrder(
            symbol=normalize_crypto_symbol(symbol),
            action=str(action or "").upper(),
            quantity=self._float(quantity),
            price=self._float(price),
            order_type=str(order_type or "LIMIT").upper(),
            dry_run=self.dry_run if dry_run is None else bool(dry_run),
            client_order_id=f"BTEST_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        )
        error = self._validate_order(order)
        if error:
            order.status = "rejected"
            order.message = error
            return order
        if order.dry_run:
            order.status = "dry_run"
            order.message = "dry-run accepted; no Binance Testnet order was sent"
            return order
        order.status = "rejected"
        order.message = "live Binance Testnet transport is intentionally disabled in this build"
        return order

    def _validate_order(self, order: BinanceTestnetOrder) -> str:
        if self.mainnet_real_trading_enabled:
            return "mainnet trading is not supported"
        if self.real_trading_enabled and not self._confirmation_ok():
            return "testnet real_trading_enabled=true refused without confirmation phrase"
        if not order.symbol:
            return "symbol is required"
        if order.action not in {"BUY", "SELL"}:
            return "unsupported action"
        if order.quantity <= 0:
            return "quantity must be greater than 0"
        if order.order_type not in {"LIMIT", "MARKET"}:
            return "unsupported order_type"
        if order.order_type == "LIMIT" and order.price <= 0:
            return "limit price must be greater than 0"
        if not order.dry_run:
            if not self.enabled:
                return "testnet executor is disabled"
            if not self._confirmation_ok():
                return "testnet confirmation phrase is required"
            credentials = self._load_credentials(mask=False)
            if not credentials.get("api_key") or not credentials.get("api_secret"):
                return "Binance Testnet API key is not configured"
        return ""

    def _status_message(self, has_credentials: bool, confirmation_ok: bool) -> str:
        if self.mainnet_real_trading_enabled:
            return "mainnet trading is blocked"
        if not has_credentials:
            return "testnet credentials not configured; public data and paper trading remain available"
        if self.dry_run:
            return "testnet dry-run mode; no exchange orders will be sent"
        if not confirmation_ok:
            return "testnet confirmation phrase is required before any non-dry-run order"
        return "testnet gate prepared; live transport remains disabled in this build"

    def _confirmation_ok(self) -> bool:
        expected = self.required_confirmation.strip()
        configured = self.confirmation_phrase.strip()
        runtime = self._runtime_confirmation_phrase.strip()
        return bool(expected) and (configured == expected or runtime == expected)

    def _load_credentials(self, *, mask: bool) -> dict[str, str]:
        if self.credential_store_path.exists():
            try:
                payload = json.loads(self._credential_manager.decrypt(self.credential_store_path.read_bytes()))
                api_key = str(payload.get("api_key") or "")
                api_secret = str(payload.get("api_secret") or "")
                return {
                    "api_key": self._mask(api_key) if mask else api_key,
                    "api_secret": self._mask(api_secret) if mask else api_secret,
                }
            except Exception:
                return {"api_key": "", "api_secret": ""}
        api_key = self.config_api_key
        api_secret = self.config_api_secret
        return {
            "api_key": self._mask(api_key) if mask else api_key,
            "api_secret": self._mask(api_secret) if mask else api_secret,
        }

    def _mask(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def _resolve_path(self, value: str) -> Path:
        path = Path(value or "")
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
