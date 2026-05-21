from core.shadow_trading import OrderbookImpactCalculator, ShadowTradingEngine


ORDER_BOOK = {
    "asks": [[100, 1], [101, 2], [103, 5]],
    "bids": [[99, 1], [98, 2], [95, 5]],
}


class FakeProvider:
    def fetch_order_book(self, symbol, limit=20):
        return ORDER_BOOK

    def fetch_quotes(self, symbols):
        return [{"symbol": symbols[0], "price": 100}]


def test_small_and_large_orderbook_fill():
    calc = OrderbookImpactCalculator()
    small = calc.simulate_fill(ORDER_BOOK, "BUY", 0.5)
    large = calc.simulate_fill(ORDER_BOOK, "BUY", 2.5)

    assert small.levels_consumed == 1
    assert large.levels_consumed == 2
    assert large.average_price > small.average_price
    assert large.slippage_pct > small.slippage_pct


def test_max_slippage_caps_fill_and_empty_book():
    calc = OrderbookImpactCalculator()
    capped = calc.simulate_fill(ORDER_BOOK, "BUY", 8, max_slippage_pct=0.1)
    empty = calc.simulate_fill({}, "BUY", 1)

    assert capped.remaining_quantity > 0
    assert empty.filled_quantity == 0


def test_sell_side_uses_bids():
    fill = OrderbookImpactCalculator().simulate_fill(ORDER_BOOK, "SELL", 2)

    assert fill.average_price < 99


def test_shadow_position_created_and_removed():
    engine = ShadowTradingEngine(FakeProvider())
    buy = engine.execute_shadow_trade("BTC/USDT", "BUY", 1, "unit")
    assert buy["orderbook_available"] is True
    assert engine.get_positions()[0]["symbol"] == "BTC/USDT"

    engine.execute_shadow_trade("BTC/USDT", "SELL", 1, "unit")
    assert engine.get_positions() == []


def test_shadow_fallback_to_fixed_slippage():
    class BrokenProvider(FakeProvider):
        def fetch_order_book(self, symbol, limit=20):
            raise RuntimeError("down")

    engine = ShadowTradingEngine(BrokenProvider())
    trade = engine.execute_shadow_trade("BTC/USDT", "BUY", 1, "fallback")

    assert trade["orderbook_available"] is False
    assert trade["price"] == 100.05


def test_shadow_state_persists_to_sqlite(tmp_path):
    storage_path = tmp_path / "trading.db"
    engine = ShadowTradingEngine(FakeProvider(), storage_path=str(storage_path))
    engine.execute_shadow_trade("BTC/USDT", "BUY", 1, "unit", sl_price=90, tp_price=120)

    restored = ShadowTradingEngine(FakeProvider(), storage_path=str(storage_path))

    assert restored.get_positions()[0]["symbol"] == "BTC/USDT"
    assert restored.get_positions()[0]["stop_loss_price"] == 90
    assert restored.trade_log[-1]["strategy_id"] == "unit"
