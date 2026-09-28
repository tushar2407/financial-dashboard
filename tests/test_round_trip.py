import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from data_loader import categorize_transactions

EFT_PAID = "Electronic Funds Transfer Paid (Cash)"
EFT_RECEIVED = "Electronic Funds Transfer Received (Cash)"


def _tx(date, action, amount, account="Individual"):
    return {
        'Run Date': pd.Timestamp(date),
        'Account': account,
        'Action': action,
        'Description': "No Description",
        'Symbol': "",
        'Amount': amount,
    }


def _categories(rows):
    return categorize_transactions(pd.DataFrame(rows))['Category'].tolist()


def test_withdrawal_returned_within_window_is_round_trip():
    cats = _categories([
        _tx('2024-09-13', EFT_PAID, -8000.0),
        _tx('2024-09-19', EFT_RECEIVED, 8000.0),
    ])
    assert cats == ['ROUND_TRIP_TRANSFER', 'ROUND_TRIP_TRANSFER']


def test_unreturned_withdrawal_stays_withdrawal():
    cats = _categories([
        _tx('2024-11-18', EFT_PAID, -2000.0),
        _tx('2024-11-19', EFT_PAID, -1000.0),
    ])
    assert cats == ['WITHDRAWAL', 'WITHDRAWAL']


def test_deposit_outside_window_is_not_matched():
    cats = _categories([
        _tx('2024-09-01', EFT_PAID, -500.0),
        _tx('2024-10-01', EFT_RECEIVED, 500.0),
    ])
    assert cats == ['WITHDRAWAL', 'DEPOSIT']


def test_deposit_before_withdrawal_is_not_matched():
    cats = _categories([
        _tx('2024-09-01', EFT_RECEIVED, 500.0),
        _tx('2024-09-03', EFT_PAID, -500.0),
    ])
    assert cats == ['DEPOSIT', 'WITHDRAWAL']


def test_different_amount_or_account_is_not_matched():
    cats = _categories([
        _tx('2024-09-01', EFT_PAID, -500.0),
        _tx('2024-09-02', EFT_RECEIVED, 499.0),
        _tx('2024-09-02', EFT_RECEIVED, 500.0, account="Other"),
    ])
    assert cats == ['WITHDRAWAL', 'DEPOSIT', 'DEPOSIT']


def test_each_deposit_matches_only_one_withdrawal():
    cats = _categories([
        _tx('2024-09-01', EFT_PAID, -500.0),
        _tx('2024-09-02', EFT_PAID, -500.0),
        _tx('2024-09-03', EFT_RECEIVED, 500.0),
    ])
    assert cats == ['ROUND_TRIP_TRANSFER', 'WITHDRAWAL', 'ROUND_TRIP_TRANSFER']


def test_input_dataframe_is_not_mutated():
    df = pd.DataFrame([_tx('2024-09-13', EFT_PAID, -8000.0)])
    categorize_transactions(df)
    assert 'Category' not in df.columns


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
