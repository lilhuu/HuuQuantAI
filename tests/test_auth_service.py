from datetime import datetime, timedelta

import pytest

from api.services.auth_service import AuthService


def test_login_failure_rate_limit_and_success_reset(tmp_path):
    service = AuthService(storage_path=str(tmp_path / "auth.db"))
    service.bootstrap_user(username="owner", password="password123", display_name="Owner")

    for _ in range(5):
        with pytest.raises(ValueError, match="用户名或密码错误"):
            service.login("owner", "wrong-password")

    with pytest.raises(ValueError, match="登录尝试过于频繁"):
        service.login("owner", "password123")

    service._login_failures["owner"]["blocked_until"] = datetime.now() - timedelta(seconds=1)
    session = service.login("owner", "password123")

    assert session.access_token
    assert "owner" not in service._login_failures


def test_bootstrap_requires_configured_one_time_token(tmp_path):
    service = AuthService(
        storage_path=str(tmp_path / "bootstrap-token.db"),
        bootstrap_token="setup-secret",
    )

    with pytest.raises(PermissionError, match="初始化令牌"):
        service.bootstrap_user("owner", "password123", bootstrap_token="wrong")

    session = service.bootstrap_user(
        "owner",
        "password123",
        bootstrap_token="setup-secret",
    )
    assert session.access_token

    with pytest.raises(ValueError, match="初始化"):
        service.bootstrap_user(
            "second",
            "password123",
            bootstrap_token="setup-secret",
        )
