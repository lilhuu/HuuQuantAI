"""Authentication service for the local crypto control panel."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
import threading
from typing import Any, Dict, Optional

from api.models.response import (
    AuthSessionResponse,
    AuthStatusResponse,
    AuthUserResponse,
    UserPreferencesResponse,
)
from core.app_state import AppStateStore


class AuthService:
    """Manage local users, sessions, and persisted user preferences."""

    def __init__(self, storage_path: str = "data/app_state.db", session_hours: int = 168):
        self.storage = AppStateStore(storage_path)
        self.session_hours = max(int(session_hours), 1)
        self._lock = threading.RLock()

    def get_status(self, token: Optional[str] = None) -> AuthStatusResponse:
        user = self.authenticate_token(token) if token else None
        return AuthStatusResponse(
            setup_required=self.storage.count_users() == 0,
            authenticated=user is not None,
            user=self._build_user_response(user) if user else None,
        )

    def bootstrap_user(self, username: str, password: str, display_name: Optional[str] = None) -> AuthSessionResponse:
        with self._lock:
            if self.storage.count_users() > 0:
                raise ValueError("系统已经完成初始化，请直接登录。")

            salt = secrets.token_hex(16)
            password_hash = self._hash_password(password, salt)
            user = self.storage.create_user(
                username=username,
                password_hash=password_hash,
                password_salt=salt,
                display_name=display_name or username,
            )
            self.storage.save_user_preferences(user["user_id"], self._default_preferences())
            return self._issue_session(user)

    def login(self, username: str, password: str) -> AuthSessionResponse:
        with self._lock:
            user = self.storage.get_user_by_username(username)
            if not user:
                raise ValueError("用户名或密码错误。")
            if not bool(user.get("is_active", 1)):
                raise ValueError("当前账户已被停用。")

            password_hash = self._hash_password(password, user["password_salt"])
            if not hmac.compare_digest(password_hash, str(user["password_hash"])):
                raise ValueError("用户名或密码错误。")

            return self._issue_session(user)

    def logout(self, token: str) -> None:
        if token:
            self.storage.delete_session(self._hash_token(token))

    def authenticate_token(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None

        session = self.storage.get_session(self._hash_token(token))
        if not session:
            return None
        if not bool(session.get("is_active", 1)):
            return None

        expires_at = self._parse_datetime(session.get("expires_at"))
        if expires_at is not None and expires_at <= datetime.now():
            self.storage.delete_session(str(session.get("token_hash", "")))
            return None

        self.storage.touch_session(str(session.get("token_hash", "")))
        return {
            "user_id": int(session["user_id"]),
            "username": str(session["username"]),
            "display_name": session.get("display_name"),
            "created_at": session.get("user_created_at"),
        }

    def get_preferences(self, user_id: int) -> UserPreferencesResponse:
        with self._lock:
            payload = self.storage.get_user_preferences(user_id)
            return UserPreferencesResponse(
                preferences=payload.get("preferences", {}),
                updated_at=payload.get("updated_at"),
            )

    def update_preferences(self, user_id: int, preferences: Dict[str, Any]) -> UserPreferencesResponse:
        with self._lock:
            payload = self.storage.save_user_preferences(user_id, preferences)
            return UserPreferencesResponse(
                preferences=payload.get("preferences", {}),
                updated_at=payload.get("updated_at"),
            )

    def _issue_session(self, user: Dict[str, Any]) -> AuthSessionResponse:
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now() + timedelta(hours=self.session_hours)).isoformat()
        self.storage.save_session(self._hash_token(token), int(user["user_id"]), expires_at)

        return AuthSessionResponse(
            access_token=token,
            token_type="bearer",
            expires_at=expires_at,
            user=self._build_user_response(user),
        )

    def _build_user_response(self, user: Dict[str, Any]) -> AuthUserResponse:
        return AuthUserResponse(
            user_id=int(user["user_id"]),
            username=str(user["username"]),
            display_name=str(user.get("display_name") or user["username"]),
            created_at=str(user.get("created_at")) if user.get("created_at") else None,
        )

    def _hash_password(self, password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            310000,
        )
        return digest.hex()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _default_preferences(self) -> Dict[str, Any]:
        return {
            "workspace": {
                "cryptoWatchSymbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                "selectedCryptoSymbol": "BTC/USDT",
            }
        }
