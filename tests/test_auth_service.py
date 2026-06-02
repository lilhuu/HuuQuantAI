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
