import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from insights import filter_realized, last_sales, search_breakdown, yearly_tax_summary
from metrics import calculate_cost_basis


def _tx(date, category, amount=0.0, symbol="", quantity=0.0, account_type="brokerage"):
    return {'Run Date': pd.Timestamp(date), 'Account': "Individual", 'Account Type': account_type,
            'Category': category, 'Symbol': symbol, 'Quantity': quantity, 'Amount': amount,
            'Action': "", 'Description': ""}


def _sale(symbol, date, st, lt, price=10.0, account_type="brokerage"):
    return {'Symbol': symbol, 'Date': pd.Timestamp(date), 'Sell Price': price,
            'Realized P/L': st + lt, 'Short-Term P/L': st, 'Long-Term P/L': lt,
            'Account Type': account_type}


def test_yearly_tax_summary_splits_terms_and_skips_retirement():
    df = pd.DataFrame([
        _tx('2025-03-01', 'DIVIDEND', 10.0, 'A'),
        _tx('2025-03-01', 'TAX', -1.5, 'A'),
        _tx('2026-03-01', 'DIVIDEND', 20.0, 'A'),
        _tx('2026-03-01', 'DIVIDEND', 99.0, 'F', account_type='retirement'),
    ])
    realized = [
        _sale('A', '2025-06-01', 30.0, 0.0),
        _sale('A', '2026-06-01', -10.0, 5.0),
        _sale('F', '2026-06-01', 500.0, 0.0, account_type='retirement'),
    ]
    s = yearly_tax_summary(df, realized)
    assert list(s.index) == [2025, 2026]
    assert s.loc[2025].to_dict() == {'realized_st': 30.0, 'realized_lt': 0.0, 'dividends': 10.0,
                                     'foreign_tax': 1.5, 'total': 40.0}
    assert s.loc[2026].to_dict() == {'realized_st': -10.0, 'realized_lt': 5.0, 'dividends': 20.0,
                                     'foreign_tax': 0.0, 'total': 15.0}


def test_yearly_tax_summary_empty_when_only_retirement():
    df = pd.DataFrame([_tx('2026-03-01', 'DIVIDEND', 5.0, 'F', account_type='retirement')])
    assert yearly_tax_summary(df, []).empty


def test_filter_realized_by_year_and_search():
    realized = [_sale('META', '2025-06-01', 1, 0), _sale('MSFT', '2026-02-01', 1, 0),
                _sale('META', '2026-03-01', 1, 0)]
    assert [r['Date'].year for r in filter_realized(realized, 2026)] == [2026, 2026]
    assert [r['Symbol'] for r in filter_realized(realized, None, 'me')] == ['META', 'META']
    assert len(filter_realized(realized, 2026, 'meta')) == 1
    assert filter_realized(realized, 'all', '') == realized


def test_last_sales_takes_most_recent_sale_per_stock():
    realized = [_sale('A', '2026-01-01', 0, 0, price=10.0), _sale('A', '2026-03-01', 0, 0, price=12.0),
                _sale('B', '2025-05-05', 0, 0, price=7.0)]
    out = last_sales(realized)
    assert out['A'] == {'date': pd.Timestamp('2026-03-01'), 'price': 12.0}
    assert out['B']['price'] == 7.0


def test_search_breakdown_is_case_insensitive_substring():
    b = pd.DataFrame({'total': [1.0, 2.0, 3.0]}, index=['NVDA', 'NVO', 'AMD'])
    assert list(search_breakdown(b, 'nv').index) == ['NVDA', 'NVO']
    assert list(search_breakdown(b, '').index) == ['NVDA', 'NVO', 'AMD']
    assert list(search_breakdown(b, None).index) == ['NVDA', 'NVO', 'AMD']


def test_realized_sales_record_account_type():
    df = pd.DataFrame([
        _tx('2025-01-02', 'BUY', -100.0, 'A', 10.0),
        _tx('2025-02-02', 'SELL', 120.0, 'A', -10.0),
    ])
    _, realized = calculate_cost_basis(df)
    assert realized[0]['Account Type'] == 'brokerage'
    assert realized[0]['Account'] == 'Individual'


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
