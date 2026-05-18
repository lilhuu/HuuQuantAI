"""凭据与环境变量辅助工具。"""

import os
import re
from pathlib import Path
from typing import Any


class CredentialManager:
    """凭据管理器。

    加密功能依赖 cryptography；如果未安装，只有环境变量解析功能可用。
    """

    def __init__(self, key_file: str = ".secret.key"):
        self.key_file = Path(key_file)
        self._cipher = None

    def encrypt(self, text: str) -> bytes:
        cipher = self._get_cipher()
        return cipher.encrypt(text.encode("utf-8"))

    def decrypt(self, encrypted: bytes) -> str:
        cipher = self._get_cipher()
        return cipher.decrypt(encrypted).decode("utf-8")

    def _get_cipher(self):
        if self._cipher is not None:
            return self._cipher
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:
            raise ImportError("请先安装 cryptography: pip install cryptography") from e

        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)

        self._cipher = Fernet(key)
        return self._cipher


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def resolve_env_placeholders(value: Any) -> Any:
    """Resolve ${ENV_NAME} and ${ENV_NAME:-default} recursively.

    Placeholders may be the entire value or embedded inside a longer string, for
    example "tcp://${BROKER_HOST:-127.0.0.1}:${BROKER_PORT:-7700}".
    Missing variables without a default resolve to an empty string, preserving
    the previous safe behavior for optional credentials.
    """
    if isinstance(value, dict):
        return {key: resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_env_placeholders(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match) -> str:
        env_name = match.group(1)
        default = match.group(2)
        if env_name in os.environ:
            return os.environ.get(env_name, "")
        return "" if default is None else default

    return _ENV_PATTERN.sub(replace, value)
