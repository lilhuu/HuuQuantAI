from core.take_profit_manager import MonitorConfig, TakeProfitManager, TriggerType


class PriceProvider:
    def __init__(self, price):
        self.price = price

    def fetch_quotes(self, symbols):
        return [{"symbol": symbols[0], "price": self.price}]


def test_sl_and_tp_triggers_for_long_positions():
    sl_manager = TakeProfitManager(PriceProvider(94))
    sl_manager.register_position("BTC/USDT", 1, 100, sl_price=95, tp_price=110)
    sl = sl_manager.check_once()[0]
    assert sl.trigger_type == TriggerType.STOP_LOSS

    tp_manager = TakeProfitManager(PriceProvider(111))
    tp_manager.register_position("BTC/USDT", 1, 100, sl_price=95, tp_price=110)
    tp = tp_manager.check_once()[0]
    assert tp.trigger_type == TriggerType.TAKE_PROFIT


def test_no_trigger_and_unregister_after_trigger():
    manager = TakeProfitManager(PriceProvider(100))
    manager.register_position("BTC/USDT", 1, 100, sl_price=95, tp_price=110)
    assert manager.check_once() == []

    manager.provider.price = 94
    assert manager.check_once()
    assert manager.check_once() == []


def test_callback_and_disabled_sl():
    calls = []
    manager = TakeProfitManager(PriceProvider(94), MonitorConfig(sl_enabled=False))
    manager.set_trigger_callback(lambda result: calls.append(result))
    manager.register_position("BTC/USDT", 1, 100, sl_price=95, tp_price=110)
    assert manager.check_once() == []
    assert calls == []

    manager.config.sl_enabled = True
    assert manager.check_once()
    assert len(calls) == 1


def test_short_position_and_trailing_stop():
    short = TakeProfitManager(PriceProvider(106))
    short.register_position("BTC/USDT", 1, 100, sl_price=105, tp_price=90, direction="short")
    assert short.check_once()[0].trigger_type == TriggerType.STOP_LOSS

    trailing = TakeProfitManager(PriceProvider(110), MonitorConfig(trailing_stop_enabled=True, trailing_stop_distance_pct=0.05))
    trailing.register_position("BTC/USDT", 1, 100, sl_price=None, tp_price=None)
    assert trailing.check_once() == []
    trailing.provider.price = 104
    assert trailing.check_once()[0].trigger_type == TriggerType.TRAILING_STOP
