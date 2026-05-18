"""Misc helper functions."""


def calc_order_quantity(cash: float, price: float, ratio: float = 0.1) -> int:
    budget = cash * ratio
    qty = int(budget // price)
    return max(qty, 0)
