from core.risk_budget import RiskBudgetConfig, RiskBudgetSizer


def test_basic_risk_budget_calculation():
    size = RiskBudgetSizer().calculate(10000, 65000, 63700)

    assert size.risk_budget == 200
    assert round(size.quantity, 4) == 0.1538
    assert size.notional_value == 10000


def test_tight_stop_gives_larger_position_than_wide_stop():
    sizer = RiskBudgetSizer(RiskBudgetConfig(max_position_pct=10))
    tight = sizer.calculate(10000, 100, 98)
    wide = sizer.calculate(10000, 100, 90)

    assert tight.quantity > wide.quantity
    assert tight.risk_budget == wide.risk_budget


def test_total_risk_cap_blocks_new_trade():
    size = RiskBudgetSizer().calculate(10000, 100, 95, current_positions_risk=600)

    assert size.quantity == 0
    assert size.is_capped_by_total_risk is True


def test_position_limit_caps_notional():
    size = RiskBudgetSizer(RiskBudgetConfig(max_position_pct=0.25)).calculate(10000, 100, 99)

    assert size.notional_value == 2500
    assert size.is_capped_by_position_limit is True


def test_min_position_value_filter_and_zero_equity():
    assert RiskBudgetSizer().calculate(0, 100, 95).quantity == 0
    size = RiskBudgetSizer(RiskBudgetConfig(min_position_value=1000)).calculate(100, 100, 90)

    assert size.quantity == 0
    assert "minimum" in size.reason


def test_calculate_total_risk_for_multiple_positions():
    total = RiskBudgetSizer().calculate_total_risk(
        [
            {"entry_price": 100, "stop_loss_price": 95, "quantity": 2},
            {"avg_price": 50, "stop_loss_price": 45, "quantity": 3},
        ]
    )

    assert total == 25
