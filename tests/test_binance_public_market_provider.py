from core.binance_public_market_provider import BinancePublicMarketProvider


def test_usdm_exchange_info_and_ticker_are_normalized_from_official_fields():
    provider = BinancePublicMarketProvider()

    def fake_request(market_type, path, params=None):
        if path == "/fapi/v1/exchangeInfo":
            return {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "pair": "BTCUSDT",
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "contractType": "PERPETUAL",
                        "status": "TRADING",
                    },
                    {
                        "symbol": "OLDUSDT",
                        "pair": "OLDUSDT",
                        "baseAsset": "OLD",
                        "quoteAsset": "USDT",
                        "contractType": "PERPETUAL",
                        "status": "BREAK",
                    },
                ]
            }
        if path == "/fapi/v1/ticker/24hr":
            return [
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "65000",
                    "openPrice": "64000",
                    "highPrice": "66000",
                    "lowPrice": "63000",
                    "volume": "10",
                    "quoteVolume": "650000",
                    "priceChange": "1000",
                    "priceChangePercent": "1.5625",
                    "bidPrice": "64999",
                    "askPrice": "65001",
                    "closeTime": 1770000000000,
                }
            ]
        raise AssertionError(path)

    provider._request = fake_request

    instruments = provider.load_markets("um_futures")
    assert instruments[0]["market_type"] == "um_futures"
    assert instruments[0]["symbol"] == "BTC/USDT"
    assert instruments[0]["contract_type"] == "PERPETUAL"
    assert instruments[0]["status"] == "active"
    assert instruments[1]["status"] == "inactive"

    quotes = provider.fetch_all_tickers("um_futures")
    assert quotes[0]["market_type"] == "um_futures"
    assert quotes[0]["symbol"] == "BTC/USDT"
    assert quotes[0]["price"] == 65000.0
    assert quotes[0]["change"] == 0.015625
    assert quotes[0]["amount"] == 650000.0


def test_derivative_metrics_merge_mark_price_funding_and_open_interest():
    provider = BinancePublicMarketProvider()

    def fake_request(market_type, path, params=None):
        if path == "/fapi/v1/premiumIndex":
            return {
                "symbol": "BTCUSDT",
                "markPrice": "65010",
                "indexPrice": "65005",
                "lastFundingRate": "0.0001",
                "nextFundingTime": 1770003600000,
                "time": 1770000000000,
            }
        if path == "/fapi/v1/openInterest":
            return {"symbol": "BTCUSDT", "openInterest": "12345.67", "time": 1770000000000}
        if path == "/fapi/v1/fundingRate":
            return [{"fundingRate": "0.00009", "fundingTime": 1769990000000, "markPrice": "65000"}]
        raise AssertionError(path)

    provider._request = fake_request

    metrics = provider.fetch_derivative_metrics("um_futures", "BTC/USDT")

    assert metrics["market_type"] == "um_futures"
    assert metrics["symbol"] == "BTC/USDT"
    assert metrics["mark_price"] == 65010.0
    assert metrics["index_price"] == 65005.0
    assert metrics["funding_rate"] == 0.0001
    assert metrics["open_interest"] == 12345.67
