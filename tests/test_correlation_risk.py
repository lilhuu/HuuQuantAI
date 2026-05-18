from core.correlation_risk import CorrelationCalculator, CorrelationMatrix, CorrelationPair, CorrelationPositionSizer


def _candles(closes):
    return [{"close": close} for close in closes]


def _from_returns(start, returns):
    closes = [start]
    for item in returns:
        closes.append(closes[-1] * (1 + item))
    return closes


def test_perfect_and_negative_correlation():
    returns = [0.001 * index for index in range(1, 35)]
    matrix = CorrelationCalculator(window=30, min_points=5).compute_matrix(
        {
            "BTC/USDT": _candles(_from_returns(100, returns)),
            "ETH/USDT": _candles(_from_returns(200, returns)),
            "DOGE/USDT": _candles(_from_returns(300, [-item for item in returns])),
        }
    )

    assert matrix.get("BTC/USDT", "ETH/USDT") > 0.99
    assert matrix.get("BTC/USDT", "DOGE/USDT") < -0.99


def test_insufficient_data_not_significant():
    matrix = CorrelationCalculator(window=30, min_points=20).compute_matrix(
        {"BTC/USDT": _candles([1, 2, 3]), "ETH/USDT": _candles([2, 3, 4])}
    )

    assert matrix.get("BTC/USDT", "ETH/USDT") == 0


def test_two_highly_correlated_same_direction_halved():
    matrix = CorrelationMatrix({tuple(sorted(["BTC/USDT", "ETH/USDT"])): CorrelationPair("BTC/USDT", "ETH/USDT", 0.9, 30)})
    adjusted = CorrelationPositionSizer().adjust(
        [
            {"symbol": "BTC/USDT", "action": "BUY", "position_ratio": 0.2},
            {"symbol": "ETH/USDT", "action": "BUY", "position_ratio": 0.2},
        ],
        matrix,
    )

    assert all(item.multiplier == 0.5 for item in adjusted)
    assert all(item.adjusted_ratio == 0.1 for item in adjusted)


def test_opposite_direction_no_reduction_and_floor():
    pairs = {
        tuple(sorted(["BTC/USDT", "ETH/USDT"])): CorrelationPair("BTC/USDT", "ETH/USDT", 0.9, 30),
        tuple(sorted(["BTC/USDT", "SOL/USDT"])): CorrelationPair("BTC/USDT", "SOL/USDT", 0.9, 30),
        tuple(sorted(["BTC/USDT", "BNB/USDT"])): CorrelationPair("BTC/USDT", "BNB/USDT", 0.9, 30),
        tuple(sorted(["BTC/USDT", "XRP/USDT"])): CorrelationPair("BTC/USDT", "XRP/USDT", 0.9, 30),
    }
    matrix = CorrelationMatrix(pairs)
    opposite = CorrelationPositionSizer().adjust(
        [
            {"symbol": "BTC/USDT", "action": "BUY", "position_ratio": 0.2},
            {"symbol": "ETH/USDT", "action": "SELL", "position_ratio": 0.2},
        ],
        matrix,
    )
    assert opposite[0].multiplier == 1.0

    many = CorrelationPositionSizer().adjust(
        [{"symbol": symbol, "action": "BUY", "position_ratio": 0.2} for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]],
        matrix,
    )
    assert many[0].multiplier == 0.25
