import sys
import os
import json
import tempfile

import pandas as pd

sys.path.append(os.path.abspath('src'))

from insights import (allocation_summary, benchmark_value, compare_window, load_goals,
                      monthly_deposits, realized_by_symbol, trading_summary, trades_per_month,
                      window_start)
from metrics import calculate_cost_basis


def _holding(symbol, value):
    return {'Symbol': symbol, 'Market Value': value}


# ── allocation ────────────────────────────────────────────────────────────────

def test_allocation_summary_weights_cash_and_concentration():
    holdings = [_holding('A', 400.0), _holding('B', 300.0), _holding('C', 5.0),
                _holding('D', 100.0), _holding('E', 90.0), _holding('F', 5.0)]
    sectors = {'A': 'Technology', 'B': 'Technology', 'D': 'ETF - S&P 500'}
    s = allocation_summary(holdings, cash=100.0, sectors=sectors, cash_target=0.05)

    assert s['total'] == 1000.0
    assert abs(s['cash_pct'] - 0.10) < 1e-9
    assert abs(s['cash_excess'] - 50.0) < 1e-9          # 100 held vs 50 target
    assert [p['Symbol'] for p in s['positions']][:2] == ['A', 'B']
    assert abs(s['top5_pct'] - 0.895) < 1e-9             # A+B+D+E+C over total incl. cash
    assert s['position_count'] == 6
    assert s['small_positions'] == ['C', 'F']            # under 1% each
    assert abs(s['sector_weights']['Technology'] - 0.70) < 1e-9
    assert abs(s['sector_weights']['Cash'] - 0.10) < 1e-9
    assert abs(s['sector_weights']['Unknown'] - 0.10) < 1e-9


def test_allocation_summary_empty():
    s = allocation_summary([], cash=0.0, sectors={}, cash_target=0.1)
    assert s['total'] == 0.0 and s['position_count'] == 0 and s['cash_pct'] == 0.0


# ── behavior ──────────────────────────────────────────────────────────────────

def _tx(date, category, amount=0.0, symbol="", quantity=0.0):
    return {'Run Date': pd.Timestamp(date), 'Account': "Individual", 'Category': category,
            'Symbol': symbol, 'Quantity': quantity, 'Amount': amount,
            'Action': "", 'Description': ""}


def _behavior_df():
    return pd.DataFrame([
        _tx('2025-01-02', 'DEPOSIT', 1000.0),
        _tx('2025-01-03', 'BUY', -500.0, 'A', 5.0),
        _tx('2025-01-10', 'BUY', -300.0, 'B', 3.0),
        _tx('2025-03-03', 'SELL', 600.0, 'A', -5.0),     # +100, held 59 days
        _tx('2025-03-04', 'SELL', 250.0, 'B', -3.0),     # -50, held 53 days
        _tx('2025-03-05', 'DEPOSIT', 500.0),
        _tx('2025-03-06', 'ROUND_TRIP_TRANSFER', 200.0),
        _tx('2025-03-07', 'CONTRIBUTION', 50.0, 'FUND', 1.0),
    ])


def test_realized_sales_record_holding_days():
    _, realized = calculate_cost_basis(_behavior_df())
    assert [r['Holding Days'] for r in realized] == [59, 53]


def test_trades_per_month_counts_buys_and_sells():
    counts = trades_per_month(_behavior_df())
    assert counts.to_dict() == {pd.Period('2025-01', 'M'): 2, pd.Period('2025-02', 'M'): 0,
                                pd.Period('2025-03', 'M'): 2}


def test_trading_summary():
    df = _behavior_df()
    _, realized = calculate_cost_basis(df)
    s = trading_summary(df, realized)
    assert s['trade_count'] == 4
    assert s['win_rate'] == 0.5
    assert s['median_holding_days'] == 56
    assert s['realized_total'] == 50.0
    assert s['busiest_month'] == pd.Period('2025-01', 'M')


def test_realized_by_symbol_sorted_worst_to_best():
    _, realized = calculate_cost_basis(_behavior_df())
    assert realized_by_symbol(realized).to_dict() == {'B': -50.0, 'A': 100.0}


def test_monthly_deposits_counts_new_money_only():
    d = monthly_deposits(_behavior_df())
    assert d.to_dict() == {pd.Period('2025-01', 'M'): 1000.0, pd.Period('2025-02', 'M'): 0.0,
                           pd.Period('2025-03', 'M'): 550.0}


# ── benchmark ─────────────────────────────────────────────────────────────────

def test_benchmark_value_invests_each_flow_on_its_date():
    prices = pd.Series([10.0, 20.0, 20.0, 40.0],
                       index=pd.to_datetime(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-04']))
    flows = pd.Series([100.0, 200.0, -80.0],
                      index=pd.to_datetime(['2025-01-01', '2025-01-02', '2025-01-03']))
    value = benchmark_value(flows, prices)
    # 10 shares, +10 shares, -4 shares -> 16 shares
    assert value.loc['2025-01-03'] == 16 * 20.0
    assert value.iloc[-1] == 16 * 40.0


def test_benchmark_value_uses_last_price_for_non_trading_days():
    prices = pd.Series([10.0, 12.0], index=pd.to_datetime(['2025-01-03', '2025-01-06']))
    flows = pd.Series([120.0], index=pd.to_datetime(['2025-01-04']))   # Saturday
    value = benchmark_value(flows, prices)
    assert value.iloc[-1] == 12 * 12.0


# ── time windows ──────────────────────────────────────────────────────────────

_DAYS = pd.to_datetime(['2024-07-22', '2025-09-01', '2026-08-25', '2026-09-23',
                        '2026-09-24', '2026-09-25'])


def test_window_start_by_points_and_calendar():
    assert window_start(_DAYS, '1D') == (pd.Timestamp('2026-09-24'), False)
    assert window_start(_DAYS, '5D') == (pd.Timestamp('2024-07-22'), False)   # 5 points back
    assert window_start(_DAYS, '1M') == (pd.Timestamp('2026-08-25'), False)
    assert window_start(_DAYS, '1Y') == (pd.Timestamp('2025-09-01'), False)   # last day <= cutoff
    assert window_start(_DAYS, '5Y') == (pd.Timestamp('2024-07-22'), True)    # history is shorter
    assert window_start(_DAYS, 'ALL') == (pd.Timestamp('2024-07-22'), False)


def test_compare_window_rebases_benchmark_on_portfolio_value_at_start():
    idx = pd.to_datetime(['2026-09-23', '2026-09-24', '2026-09-25'])
    pv = pd.Series([100.0, 110.0, 121.0], index=idx)
    prices = pd.Series([10.0, 10.0, 20.0], index=idx)
    w = compare_window(pv, pd.Series(dtype=float), prices, '1D')
    assert w['start'] == pd.Timestamp('2026-09-24')
    assert w['benchmark'].tolist() == [110.0, 220.0]      # 11 shares bought with 110
    assert w['invested'].tolist() == [110.0, 110.0]
    assert abs(w['portfolio_return'] - 0.10) < 1e-9
    assert abs(w['benchmark_return'] - 1.0) < 1e-9
    assert w['diff'] == 121.0 - 220.0


def test_compare_window_adds_deposits_made_inside_the_window():
    idx = pd.to_datetime(['2026-09-23', '2026-09-24', '2026-09-25'])
    pv = pd.Series([100.0, 150.0, 150.0], index=idx)
    prices = pd.Series([10.0, 10.0, 10.0], index=idx)
    flows = pd.Series([100.0, 50.0], index=pd.to_datetime(['2026-09-20', '2026-09-24']))
    w = compare_window(pv, flows, prices, '5D')              # clipped: starts 9/23
    assert w['benchmark'].tolist() == [100.0, 150.0, 150.0]  # 50 deposit on 9/24 buys 5 shares
    assert w['invested'].tolist() == [100.0, 150.0, 150.0]
    assert abs(w['portfolio_return']) < 1e-9


def test_compare_window_all_matches_full_history_benchmark():
    idx = pd.to_datetime(['2025-01-01', '2025-01-02'])
    pv = pd.Series([100.0, 130.0], index=idx)
    prices = pd.Series([10.0, 12.0], index=idx)
    flows = pd.Series([100.0], index=pd.to_datetime(['2025-01-01']))
    w = compare_window(pv, flows, prices, 'ALL')
    assert w['benchmark'].tolist() == benchmark_value(flows, prices).tolist() == [100.0, 120.0]
    assert w['invested'].tolist() == [100.0, 100.0]


# ── goals ─────────────────────────────────────────────────────────────────────

def test_load_goals_defaults_and_overrides():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'goals.json')
        assert load_goals(path)['cash_target'] == 0.10
        with open(path, 'w') as f:
            json.dump({'cash_target': 0.05}, f)
        goals = load_goals(path)
        assert goals['cash_target'] == 0.05 and goals['benchmark'] == 'VOO'


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
