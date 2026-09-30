import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from metrics import calculate_cost_basis, is_long_term
from insights import stock_profit_breakdown

TODAY = pd.Timestamp('2026-09-29')


def _tx(date, category, amount=0.0, symbol="", quantity=0.0, account="Individual"):
    return {'Run Date': pd.Timestamp(date), 'Account': account, 'Category': category,
            'Symbol': symbol, 'Quantity': quantity, 'Amount': amount,
            'Action': "", 'Description': ""}


def _taxable():
    return pd.DataFrame([
        _tx('2024-01-02', 'DEPOSIT', 1000.0),
        _tx('2024-01-02', 'BUY', -100.0, 'A', 10.0),     # lot 1 @10
        _tx('2025-06-01', 'BUY', -200.0, 'A', 10.0),     # lot 2 @20
        _tx('2025-07-01', 'SELL', 450.0, 'A', -15.0),    # @30: 10 long-term, 5 short-term
        _tx('2026-09-01', 'BUY', -200.0, 'B', 2.0),      # @100, held 28 days
    ])


def test_long_term_means_held_more_than_one_year():
    assert not is_long_term(pd.Timestamp('2025-01-02'), pd.Timestamp('2026-01-02'))
    assert is_long_term(pd.Timestamp('2025-01-02'), pd.Timestamp('2026-01-03'))


def test_sale_splits_realized_pl_by_lot_age():
    _, realized = calculate_cost_basis(_taxable())
    (sale,) = realized
    assert sale['Long-Term P/L'] == 200.0     # 10 x (30 - 10)
    assert sale['Short-Term P/L'] == 50.0     # 5 x (30 - 20)
    assert sale['Realized P/L'] == 250.0


def test_holdings_keep_remaining_lots_with_purchase_dates():
    holdings, _ = calculate_cost_basis(_taxable())
    a = next(h for h in holdings if h['Symbol'] == 'A')
    assert [(lot['date'], lot['qty'], lot['cost']) for lot in a['Lots']] == \
        [(pd.Timestamp('2025-06-01'), 5.0, 20.0)]


def _enrich(holdings, prices):
    return [{**h, 'Current Price': prices[h['Symbol']]} for h in holdings]


def test_stock_profit_breakdown_per_stock():
    holdings, realized = calculate_cost_basis(_taxable())
    rows = stock_profit_breakdown(
        [('brokerage', _enrich(holdings, {'A': 40.0, 'B': 110.0}), realized)], today=TODAY)
    a = rows.loc['A']
    assert (a['realized_st'], a['realized_lt']) == (50.0, 200.0)
    assert (a['unrealized_st'], a['unrealized_lt']) == (0.0, 100.0)   # lot 2 now > 1 year old
    assert a['total'] == 350.0
    b = rows.loc['B']
    assert (b['unrealized_st'], b['unrealized_lt']) == (20.0, 0.0)
    assert b['next_lt_date'] == pd.Timestamp('2027-09-02')
    assert b['next_lt_shares'] == 2.0
    assert list(rows.index) == ['A', 'B']                            # largest total first


def test_retirement_gains_go_to_their_own_column():
    plan = pd.DataFrame([_tx('2025-01-02', 'CONTRIBUTION', 100.0, 'C', 10.0, account="401K")])
    holdings, realized = calculate_cost_basis(plan)
    rows = stock_profit_breakdown(
        [('retirement', _enrich(holdings, {'C': 15.0}), realized)], today=TODAY)
    c = rows.loc['C']
    assert c['retirement'] == 50.0
    assert c['unrealized_lt'] == 0.0 and c['realized_st'] == 0.0
    assert c['total'] == 50.0


def test_same_stock_in_two_accounts_is_combined():
    t1 = pd.DataFrame([_tx('2026-09-01', 'BUY', -100.0, 'B', 1.0)])
    t2 = pd.DataFrame([_tx('2026-09-02', 'BUY', -100.0, 'B', 1.0, account="Individual 2026")])
    parts = []
    for df in (t1, t2):
        h, r = calculate_cost_basis(df)
        parts.append(('brokerage', _enrich(h, {'B': 110.0}), r))
    b = stock_profit_breakdown(parts, today=TODAY).loc['B']
    assert b['unrealized_st'] == 20.0 and b['shares'] == 2.0
    assert b['next_lt_date'] == pd.Timestamp('2027-09-02') and b['next_lt_shares'] == 1.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
