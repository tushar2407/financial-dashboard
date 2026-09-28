import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from data_loader import get_portfolio_history, get_current_cash


def _tx(date, category, amount, symbol="", quantity=0.0):
    return {
        'Run Date': pd.Timestamp(date),
        'Account': "Individual",
        'Category': category,
        'Symbol': symbol,
        'Quantity': quantity,
        'Amount': amount,
    }


def _sample():
    return pd.DataFrame([
        _tx('2024-01-02', 'DEPOSIT', 1000.0),
        _tx('2024-01-03', 'BUY', -600.0, 'ABC', 6.0),
        _tx('2024-02-01', 'DIVIDEND', 10.0, 'ABC'),
        _tx('2024-02-01', 'REINVESTMENT', -10.0, 'ABC', 0.1),
        _tx('2024-03-01', 'DIVIDEND', 5.0, 'ABC'),
        _tx('2024-03-02', 'TAX', -1.0, 'ABC'),
        _tx('2024-04-01', 'SELL', 200.0, 'ABC', -2.0),
        _tx('2024-05-01', 'WITHDRAWAL', -100.0),
    ])


def test_reinvested_dividend_does_not_add_cash():
    holdings, _ = get_portfolio_history(_sample())
    # 1000 - 600 + (10 - 10) + 5 - 1 + 200 - 100
    assert abs(holdings['Cash'].iloc[-1] - 504.0) < 1e-9
    assert abs(holdings['ABC'].iloc[-1] - 4.1) < 1e-9


def test_current_cash_matches_history():
    df = _sample()
    holdings, _ = get_portfolio_history(df)
    assert abs(get_current_cash(df) - holdings['Cash'].iloc[-1]) < 1e-9


def test_current_cash_empty():
    assert get_current_cash(pd.DataFrame()) == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
