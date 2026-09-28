import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from metrics import calculate_dividend_income


def test_dividend_income_is_net_of_tax_and_fees():
    df = pd.DataFrame({
        'Category': ['DIVIDEND', 'DIVIDEND', 'REINVESTMENT', 'TAX', 'FEE', 'BUY'],
        'Amount': [10.0, 5.0, -10.0, -1.0, -0.5, -600.0],
    })
    assert abs(calculate_dividend_income(df) - 13.5) < 1e-9


def test_dividend_income_empty():
    assert calculate_dividend_income(pd.DataFrame()) == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
