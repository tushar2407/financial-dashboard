import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from formatting import MINUS, ZERO, date, money, pct, sign_class, shares


def test_money_plain_and_signed():
    assert money(1234.4) == "$1,234"
    assert money(-978) == f"{MINUS}$978"
    assert money(401.1, signed=True, cents=True) == "+$401.10"
    assert money(-6000, cents=True) == f"{MINUS}$6,000.00"


def test_money_zero_is_a_dash():
    assert money(0) == ZERO
    assert money(0.004, cents=True) == ZERO
    assert money(0, zero_dash=False) == "$0"


def test_money_none_or_nan():
    assert money(None) == ZERO
    assert money(float('nan')) == ZERO


def test_pct():
    assert pct(0.1234) == "+12.3%"
    assert pct(-0.071, digits=2) == f"{MINUS}7.10%"
    assert pct(0.5, signed=False) == "50.0%"
    assert pct(None) == ZERO


def test_shares_and_date():
    assert shares(18.0251) == "18.03"
    assert shares(0.001) == "<0.01"
    assert date(pd.Timestamp('2026-09-22')) == "Sep 22, 2026"
    assert date(None) == ZERO


def test_sign_class():
    assert sign_class(5) == "pos"
    assert sign_class(-5) == "neg"
    assert sign_class(0.001) == "zero"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
