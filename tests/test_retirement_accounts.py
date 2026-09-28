import sys
import os

import pandas as pd

sys.path.append(os.path.abspath('src'))

from data_loader import (categorize_transactions, discover_accounts, get_current_cash,
                         get_portfolio_history)
from metrics import calculate_cost_basis, calculate_net_invested_breakdown, get_daily_cash_flows


def _tx(date, account, category, amount, symbol="", quantity=0.0, account_type="retirement"):
    return {
        'Run Date': pd.Timestamp(date),
        'Account': account,
        'Account Type': account_type,
        'Category': category,
        'Action': "",
        'Description': "",
        'Symbol': symbol,
        'Quantity': quantity,
        'Amount': amount,
    }


def test_brokeragelink_is_retirement():
    df = pd.DataFrame({'Account': ["Individual", "BrokerageLink", "MICROSOFT 401K PLAN"]})
    meta = discover_accounts(df)
    assert meta['brokerage_accounts'] == ["Individual"]
    assert sorted(meta['retirement_accounts']) == ["BrokerageLink", "MICROSOFT 401K PLAN"]


def test_contributions_action_is_contribution_category():
    df = pd.DataFrame([{
        'Run Date': pd.Timestamp('2025-08-15'), 'Account': "MICROSOFT 401K PLAN",
        'Action': "Contributions", 'Description': "", 'Symbol': "FUND", 'Amount': 100.0,
    }])
    assert categorize_transactions(df)['Category'].tolist() == ['CONTRIBUTION']


def _brokeragelink_sample():
    # Money arrives by transfer, then buys shares: no new contributions.
    return pd.DataFrame([
        _tx('2026-08-31', "BrokerageLink", 'INTERNAL_TRANSFER', 1000.0),
        _tx('2026-08-31', "BrokerageLink", 'BUY', -900.0, 'VOO', 2.0),
    ])


def test_retirement_buy_spends_cash_and_is_not_a_contribution():
    df = _brokeragelink_sample()
    assert abs(get_current_cash(df) - 100.0) < 1e-9
    assert get_daily_cash_flows(df).sum() == 1000.0
    assert calculate_net_invested_breakdown(df)['contributions'] == 0


def test_contribution_adds_shares_and_capital_but_not_cash():
    df = pd.DataFrame([
        _tx('2025-08-15', "MICROSOFT 401K PLAN", 'CONTRIBUTION', 200.0, 'FUND', 4.0),
    ])
    holdings, _ = get_portfolio_history(df)
    assert holdings['FUND'].iloc[-1] == 4.0
    assert holdings['Cash'].iloc[-1] == 0.0
    assert get_daily_cash_flows(df).sum() == 200.0
    assert calculate_net_invested_breakdown(df)['contributions'] == 200.0
    lots, _ = calculate_cost_basis(df)
    assert lots[0]['Symbol'] == 'FUND' and abs(lots[0]['Total Cost'] - 200.0) < 1e-9


PLAN = "MICROSOFT 401K PLAN"
BLINK = "BrokerageLink"


def _plan_and_brokeragelink_raw():
    """Two contributions into the plan's BROKERAGELINK placeholder; only the first
    has arrived in the BrokerageLink account so far."""
    def raw(date, account, action, amount, symbol="", quantity=0.0):
        return {'Run Date': pd.Timestamp(date), 'Account': account, 'Action': action,
                'Description': "", 'Symbol': symbol, 'Quantity': quantity, 'Amount': amount}
    return pd.DataFrame([
        raw('2026-08-28', PLAN, "Contributions", 400.0, 'BROKERAGELINK', 400.0),
        raw('2026-08-31', BLINK, "TRANSFERRED FROM TO BROKERAGE OPTION (Cash)", 400.0),
        raw('2026-08-31', BLINK, "YOU BOUGHT VOO (Cash)", -390.0, 'VOO', 1.0),
        raw('2026-09-11', PLAN, "Contributions", 100.0, 'BROKERAGELINK', 100.0),
    ])


def test_brokeragelink_arrival_drains_plan_placeholder():
    df = categorize_transactions(_plan_and_brokeragelink_raw())
    plan = df[df['Account'] == PLAN]
    assert plan['Category'].tolist().count('PLAN_TRANSFER_OUT') == 1

    holdings, _ = get_portfolio_history(plan)
    assert abs(holdings['BROKERAGELINK'].iloc[-1] - 100.0) < 1e-9  # only the in-transit part
    assert holdings['Cash'].iloc[-1] == 0.0

    lots, realized = calculate_cost_basis(plan)
    assert [(h['Symbol'], round(h['Quantity'], 6)) for h in lots] == [('BROKERAGELINK', 100.0)]
    assert realized == []  # moving money is not a sale


def test_plan_transfer_nets_to_zero_across_both_accounts():
    df = categorize_transactions(_plan_and_brokeragelink_raw())
    plan = df[df['Account'] == PLAN]
    blink = df[df['Account'] == BLINK]
    assert get_daily_cash_flows(plan).sum() == 100.0       # 500 contributed - 400 moved out
    assert get_daily_cash_flows(blink).sum() == 400.0      # 400 moved in
    assert get_daily_cash_flows(df).sum() == 500.0         # only real contributions
    assert calculate_net_invested_breakdown(df)['total'] == 500.0


def test_no_placeholder_account_means_no_derived_rows():
    raw = _plan_and_brokeragelink_raw()
    df = categorize_transactions(raw[raw['Account'] == BLINK])
    assert 'PLAN_TRANSFER_OUT' not in df['Category'].tolist()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} passed")
