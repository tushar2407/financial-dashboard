import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from metrics import calculate_twr
from insights import compare_window


def _idx(*days):
    return pd.to_datetime(list(days))


def test_twr_counts_deposit_on_non_trading_day_as_deposit():
    # Valued on Jan 2, 3, 6 only; $100 deposited on Sat Jan 4. No market move.
    pv = pd.Series([100.0, 100.0, 200.0], index=_idx('2025-01-02', '2025-01-03', '2025-01-06'))
    flows = pd.Series([100.0, 100.0], index=_idx('2025-01-02', '2025-01-04'))
    assert abs(calculate_twr(pv, flows)) < 1e-9


def test_compare_window_invested_keeps_non_trading_day_deposits():
    pv = pd.Series([100.0, 100.0, 200.0], index=_idx('2025-01-02', '2025-01-03', '2025-01-06'))
    flows = pd.Series([100.0, 100.0], index=_idx('2025-01-02', '2025-01-04'))
    prices = pd.Series([10.0, 10.0, 10.0], index=pv.index)
    w = compare_window(pv, flows, prices, 'ALL')
    assert w['invested'].iloc[-1] == 200.0
    assert abs(w['portfolio_return']) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
