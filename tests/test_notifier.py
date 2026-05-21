from core.notifier import TradeNotifier


def test_notifier_is_disabled_without_smtp_config():
    notifier = TradeNotifier({})

    assert notifier.enabled is False
    assert notifier.send_trade_alert("unit", "body") is False


def test_daily_summary_returns_false_when_disabled():
    notifier = TradeNotifier({"smtp": {}})

    assert notifier.send_daily_summary({"equity": 1000}, [{"realized_pnl": 12}]) is False
