import sys
import os
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.append(os.path.abspath('src'))

from data_loader import find_stale_price_symbols

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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
