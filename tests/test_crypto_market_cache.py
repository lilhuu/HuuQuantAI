from core.crypto_market_cache import CryptoMarketCache


def _quote(symbol, amount):
    return {
        "symbol": symbol,
        "price": 1,
        "open": 1,
        "high": 1,
        "low": 1,
        "volume": 1,
        "amount": amount,
        "change": 0,
        "change_amount": 0,
        "bid": 1,
        "ask": 1,
        "timestamp": "2026-06-12T00:00:00Z",
        "source": "binance",
    }


def test_quote_page_filters_all_quote_search_and_pagination(tmp_path):
    cache = CryptoMarketCache(str(tmp_path / "market.db"))
    cache.upsert_quotes([
        _quote("BTC/USDT", 100),
        _quote("ETH/BTC", 200),
        _quote("BNB/USDC", 300),
    ])

    all_rows, all_total = cache.get_quote_page(quote="ALL")
    assert all_total == 3
    assert [row["symbol"] for row in all_rows] == ["BNB/USDC", "BTC/USDT", "ETH/BTC"]

    usdt_rows, usdt_total = cache.get_quote_page(quote="USDT")
    assert usdt_total == 1
    assert usdt_rows[0]["symbol"] == "BTC/USDT"

    search_rows, search_total = cache.get_quote_page(search="btc", limit=1, offset=1)
    assert search_total == 2
    assert [row["symbol"] for row in search_rows] == ["ETH/BTC"]
