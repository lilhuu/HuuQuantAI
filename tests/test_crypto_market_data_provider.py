from core.crypto_market_data_provider import CryptoMarketDataProvider


class _FakeExchange:
    def load_markets(self, reload=False):
        return {
            "BTC/USDT": {
                "type": "spot",
                "active": True,
                "base": "BTC",
                "quote": "USDT",
                "info": {"status": "TRADING", "permissions": ["SPOT"]},
                "precision": {"price": 2, "amount": 6},
                "limits": {"cost": {"min": 5}},
            },
            "ETH/BTC": {
                "type": "spot",
                "active": True,
                "base": "ETH",
                "quote": "BTC",
                "info": {"status": "TRADING", "permissions": ["SPOT"]},
                "precision": {"price": 8, "amount": 5},
                "limits": {"cost": {"min": 0.0001}},
            },
            "BNB/USDC": {
                "type": "spot",
                "active": True,
                "base": "BNB",
                "quote": "USDC",
                "info": {"status": "TRADING", "permissions": ["SPOT"]},
                "precision": {"price": 3, "amount": 4},
                "limits": {"cost": {"min": 5}},
            },
            "BTC/USDT:USDT": {
                "type": "swap",
                "active": True,
                "base": "BTC",
                "quote": "USDT",
            },
            "OLD/USDT": {
                "type": "spot",
                "active": False,
                "base": "OLD",
                "quote": "USDT",
                "info": {"status": "HALT", "permissions": ["SPOT"]},
            },
            "MARGINONLY/USDT": {
                "type": "spot",
                "active": True,
                "base": "MARGINONLY",
                "quote": "USDT",
                "info": {"status": "TRADING", "permissions": ["MARGIN"]},
            },
        }


def test_load_markets_returns_all_spot_quote_assets_and_skips_derivatives():
    provider = CryptoMarketDataProvider({"default_quote_currency": "USDT"})
    provider._exchange = _FakeExchange()

    symbols = provider.load_markets()

    assert [item["symbol"] for item in symbols] == ["BNB/USDC", "BTC/USDT", "ETH/BTC", "OLD/USDT"]
    assert {item["quote"] for item in symbols} == {"USDT", "BTC", "USDC"}
    assert {item["status"] for item in symbols} == {"active", "inactive"}
