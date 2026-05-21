from core.portfolio_returns import build_portfolio_return_analytics, normalize_shadow_row, normalize_trade_row


def test_portfolio_returns_summarizes_local_trades():
    rows = [
        {
            "trade_id": "t1",
            "symbol": "BTC/USDT",
            "side": "SELL",
            "status": "closed",
            "closed_at": "2026-05-01T00:00:00+00:00",
            "realized_pnl": 120,
            "fee": 1,
            "quantity": 0.01,
            "price": 65000,
            "strategy_id": "ma",
        },
        {
            "trade_id": "t2",
            "symbol": "ETH/USDT",
            "side": "SELL",
            "status": "closed",
            "closed_at": "2026-05-02T00:00:00+00:00",
            "realized_pnl": -40,
            "fee": 1,
            "quantity": 0.2,
            "price": 3000,
            "strategy_id": "rsi",
        },
    ]

    analytics = build_portfolio_return_analytics("demo", "all", trades=rows, capital_base=10_000)

    assert analytics.summary.total_pnl == 80
    assert analytics.summary.closed_trades == 2
    assert analytics.summary.win_rate == 50
    assert analytics.summary.profit_factor == 3
    assert analytics.by_symbol[0].key == "BTC/USDT"
    assert len(analytics.equity_curve) == 2


def test_portfolio_returns_includes_open_unrealized_rows():
    row = normalize_trade_row(
        {
            "id": "open_btc",
            "symbol": "BTC/USDT",
            "side": "BUY",
            "status": "open",
            "timestamp": 1_800_000_000,
            "unrealized_pnl": 25,
            "quantity": 0.01,
            "avg_price": 60000,
            "current_price": 62500,
            "strategy_id": "open_position",
        },
        capital_base=10_000,
        mode="demo",
    )

    assert row is not None
    assert row.status == "open"
    assert row.total_pnl == 25
    assert row.account_return_pct == 0.25


def test_shadow_row_estimates_unrealized_pnl_from_mark_price():
    row = normalize_shadow_row(
        {
            "symbol": "BTC/USDT",
            "quantity": 0.1,
            "avg_price": 100,
            "mark_price": 110,
            "created_at": "2026-05-01T00:00:00+00:00",
            "signal_source": "shadow_unit",
        },
        capital_base=1000,
    )

    assert row.source == "shadow"
    assert row.unrealized_pnl == 1
    assert row.trade_roi_pct == 10
    assert row.is_estimated is True
