import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from data_loader import trailing_dividends_per_share
from insights import dividends_by_symbol, dividends_by_year, stock_profit_breakdown
from metrics import calculate_cost_basis

TODAY = pd.Timestamp('2026-09-29')


def _tx(date, category, amount=0.0, symbol="", quantity=0.0, account_type="brokerage"):
    return {'Run Date': pd.Timestamp(date), 'Account': "Individual", 'Account Type': account_type,
            'Category': category, 'Symbol': symbol, 'Quantity': quantity, 'Amount': amount,
            'Action': "", 'Description': ""}


def _df():
    return pd.DataFrame([
        _tx('2025-01-02', 'BUY', -1000.0, 'A', 10.0),            # cost $100/share
        _tx('2025-03-01', 'DIVIDEND', 10.0, 'A'),
        _tx('2025-03-01', 'TAX', -1.0, 'A'),
        _tx('2026-03-01', 'DIVIDEND', 12.0, 'A'),
        _tx('2026-03-01', 'DIVIDEND', 3.0, 'SPAXX'),
        _tx('2026-03-01', 'DIVIDEND', 50.0, 'F', account_type='retirement'),
    ])


def test_dividends_by_symbol_net_of_foreign_tax_split_by_account_type():
    d = dividends_by_symbol(_df())
    assert d.loc['A', 'taxable'] == 21.0
    assert d.loc['F', 'retirement'] == 50.0 and d.loc['F', 'taxable'] == 0.0


def test_breakdown_counts_dividends_in_total_and_drops_money_market():
    df = _df()
    holdings, realized = calculate_cost_basis(df[df['Account Type'] == 'brokerage'])
    enriched = [{**h, 'Current Price': 110.0} for h in holdings if h['Symbol'] == 'A']
    rows = stock_profit_breakdown([('brokerage', enriched, realized)], today=TODAY,
                                  dividends=dividends_by_symbol(df), dividend_per_share={'A': 2.0})
    a = rows.loc['A']
    assert a['dividends'] == 21.0
    assert a['total'] == 100.0 + 21.0                  # unrealized + dividends
    assert 'SPAXX' not in rows.index                    # cash, not a stock
    assert rows.loc['F', 'retirement'] == 50.0          # retirement dividends stay apart
    assert abs(a['current_yield'] - 2.0 / 110.0) < 1e-12
    assert abs(a['yield_on_cost'] - 2.0 / 100.0) < 1e-12


def test_yield_missing_without_dividend_data():
    holdings, realized = calculate_cost_basis(_df()[lambda d: d['Account Type'] == 'brokerage'])
    enriched = [{**h, 'Current Price': 110.0} for h in holdings]
    a = stock_profit_breakdown([('brokerage', enriched, realized)], today=TODAY).loc['A']
    assert pd.isna(a['current_yield']) and pd.isna(a['yield_on_cost']) and a['dividends'] == 0.0


def test_dividends_by_year_gross_per_symbol_taxable_only():
    t = dividends_by_year(_df())
    assert list(t.index) == ['A', 'SPAXX']              # retirement F excluded; money market kept
    assert t.loc['A', 2025] == 10.0 and t.loc['A', 2026] == 12.0
    assert t.loc['A', 'foreign_tax'] == 1.0
    assert t.loc['A', 'total'] == 22.0
    assert t.loc['SPAXX', 2025] == 0.0


def test_trailing_dividends_per_share_sums_last_twelve_months():
    idx = pd.to_datetime(['2025-06-01', '2025-10-01', '2026-03-01', '2026-06-01'])
    divs = pd.DataFrame({'A': [9.0, 1.0, 1.0, 1.0], 'B': [0.0, 0.0, 0.0, 0.0]}, index=idx)
    out = trailing_dividends_per_share(divs, end=TODAY)
    assert out == {'A': 3.0}                            # 2025-10-01 onward; zero payers omitted


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
