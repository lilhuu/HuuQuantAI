from types import SimpleNamespace

import pytest

from api.error_codes import ApiError, ErrorCode
from api.routers import crypto


def test_market_data_rate_limit_rejects_excess_requests(monkeypatch):
    monkeypatch.setattr(crypto, "_MARKET_RATE_LIMIT_MAX_REQUESTS", 1)
    crypto._market_rate_buckets.clear()
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        url=SimpleNamespace(path="/api/v1/crypto/quotes"),
    )

    crypto._rate_limit_market_data(request)
    with pytest.raises(ApiError) as exc_info:
        crypto._rate_limit_market_data(request)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error_code"] == ErrorCode.RATE_LIMITED
