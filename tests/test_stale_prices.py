import sys
import os
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.append(os.path.abspath('src'))

from data_loader import find_stale_price_symbols, unadjust_for_splits

TODAY = datetime(2026, 9, 27)


def _market(**cols):
    idx = pd.date_range('2026-09-01', '2026-09-25', freq='D')
    return pd.DataFrame({k: v(idx) for k, v in cols.items()}, index=idx)


def test_missing_or_old_market_prices_are_stale():
    market = _market(
        NVDA=lambda idx: np.ones(len(idx)),                                  # fresh (Fri close)
        AMD=lambda idx: np.where(idx <= '2026-09-10', 1.0, np.nan),         # last price 9/10
    )
    stale = find_stale_price_symbols(market, ['NVDA', 'AMD', 'MU'], today=TODAY)
    assert stale == ['AMD', 'MU']


def test_empty_market_data_marks_everything_stale():
    assert find_stale_price_symbols(pd.DataFrame(), ['A', 'B'], today=TODAY) == ['A', 'B']


def test_unadjust_for_splits_restores_pre_split_prices():
    idx = pd.to_datetime(['2024-12-09', '2024-12-10', '2026-04-20', '2026-04-21', '2026-04-22'])
    prices = pd.DataFrame({'VOOG': [60.0, 62.0, 70.0, 71.0, 72.0], 'NVDA': [1.0] * 5}, index=idx)
    splits = pd.DataFrame({'VOOG': [0, 0, 0, 6.0, 0], 'NVDA': [0.0] * 5}, index=idx)
    out = unadjust_for_splits(prices, splits)
    assert out['VOOG'].tolist() == [360.0, 372.0, 420.0, 71.0, 72.0]   # split day is post-split
    assert out['NVDA'].tolist() == [1.0] * 5
    assert prices['VOOG'].iloc[0] == 60.0                               # input not mutated


def test_unadjust_for_splits_compounds_multiple_splits():
    idx = pd.to_datetime(['2024-01-01', '2024-06-01', '2025-01-01'])
    prices = pd.DataFrame({'X': [10.0, 10.0, 10.0]}, index=idx)
    splits = pd.DataFrame({'X': [0.0, 2.0, 3.0]}, index=idx)
    assert unadjust_for_splits(prices, splits)['X'].tolist() == [60.0, 30.0, 10.0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
