"""Facts layer: turns transactions and holdings into the numbers the Overview,
Allocation and Behavior views show.

Everything here is a pure function of its inputs so it can be tested directly,
and so a later AI reflection can read the same facts instead of doing its own
arithmetic.
"""
import json
import os

import pandas as pd

from metrics import align_flows, calculate_twr, is_long_term

GOALS_PATH = os.path.join('data', 'goals.json')
DEFAULT_GOALS = {
    'cash_target': 0.10,        # share of the portfolio held as cash
    'benchmark': 'VOO',         # "what if every deposit went here instead"
    'trading_is_intentional': True,
}
SMALL_POSITION_WEIGHT = 0.01
TRADE_CATEGORIES = ('BUY', 'SELL')
NEW_MONEY_CATEGORIES = ('DEPOSIT', 'CONTRIBUTION')


def load_goals(path: str = GOALS_PATH) -> dict:
    """User goals from data/goals.json layered over DEFAULT_GOALS."""
    goals = dict(DEFAULT_GOALS)
    if os.path.exists(path):
        try:
            with open(path) as f:
                goals.update(json.load(f))
        except (OSError, ValueError) as e:
            print(f"Could not read {path} ({e}); using default goals.")
    return goals


# ── allocation ────────────────────────────────────────────────────────────────

def allocation_summary(holdings: list, cash: float, sectors: dict, cash_target: float) -> dict:
    """Weights, concentration and cash position for a set of enriched holdings.

    `holdings` are dicts with 'Symbol' and 'Market Value'; weights are shares
    of the total including cash.
    """
    total = sum(h.get('Market Value', 0) for h in holdings) + cash
    positions = sorted(
        (
            {
                'Symbol': h['Symbol'],
                'Value': h.get('Market Value', 0),
                'Weight': h.get('Market Value', 0) / total if total else 0.0,
                'Sector': sectors.get(h['Symbol'], 'Unknown') or 'Unknown',
            }
            for h in holdings
        ),
        key=lambda p: -p['Value'],
    )

    sector_weights = {}
    for p in positions:
        sector_weights[p['Sector']] = sector_weights.get(p['Sector'], 0.0) + p['Weight']
    if cash and total:
        sector_weights['Cash'] = sector_weights.get('Cash', 0.0) + cash / total

    return {
        'total': total,
        'cash': cash,
        'cash_pct': cash / total if total else 0.0,
        'cash_target': cash_target,
        'cash_excess': cash - cash_target * total,
        'positions': positions,
        'position_count': len(positions),
        'top5_pct': sum(p['Weight'] for p in positions[:5]),
        'small_positions': [p['Symbol'] for p in positions if p['Weight'] < SMALL_POSITION_WEIGHT],
        'sector_weights': dict(sorted(sector_weights.items(), key=lambda kv: -kv[1])),
    }


# ── behavior ──────────────────────────────────────────────────────────────────

def _monthly(series_by_date: pd.Series, how: str) -> pd.Series:
    """Group a date-indexed series by month, filling empty months with 0."""
    if series_by_date.empty:
        return pd.Series(dtype=float)
    grouped = series_by_date.groupby(series_by_date.index.to_period('M'))
    result = grouped.size() if how == 'count' else grouped.sum()
    full = pd.period_range(result.index.min(), result.index.max(), freq='M')
    return result.reindex(full, fill_value=0)


def trades_per_month(df: pd.DataFrame) -> pd.Series:
    trades = df[df['Category'].isin(TRADE_CATEGORIES)]
    return _monthly(trades.set_index('Run Date')['Amount'], how='count')


def monthly_deposits(df: pd.DataFrame) -> pd.Series:
    """New money added per month: deposits and retirement contributions."""
    new_money = df[df['Category'].isin(NEW_MONEY_CATEGORIES)]
    return _monthly(new_money.set_index('Run Date')['Amount'].abs(), how='sum').astype(float)


def realized_by_symbol(realized: list) -> pd.Series:
    """Total realized P/L per symbol, worst first."""
    if not realized:
        return pd.Series(dtype=float)
    r = pd.DataFrame(realized)
    return r.groupby('Symbol')['Realized P/L'].sum().sort_values()


def trading_summary(df: pd.DataFrame, realized: list) -> dict:
    per_month = trades_per_month(df)
    r = pd.DataFrame(realized)
    has_sales = not r.empty
    return {
        'trade_count': int(per_month.sum()) if not per_month.empty else 0,
        'months': len(per_month),
        'median_per_month': float(per_month.median()) if not per_month.empty else 0.0,
        'busiest_month': per_month.idxmax() if not per_month.empty else None,
        'busiest_count': int(per_month.max()) if not per_month.empty else 0,
        'sale_count': len(r),
        'win_rate': float((r['Realized P/L'] > 0).mean()) if has_sales else 0.0,
        'median_holding_days': float(r['Holding Days'].median()) if has_sales else 0.0,
        'realized_total': float(r['Realized P/L'].sum()) if has_sales else 0.0,
    }


# ── benchmark ─────────────────────────────────────────────────────────────────

def benchmark_value(daily_flows: pd.Series, benchmark_prices: pd.Series) -> pd.Series:
    """Daily value of investing each external cash flow in the benchmark on the
    day it happened (withdrawals sell shares). Non-trading days use the last
    close; flows before the first price use the first available close.
    """
    prices = benchmark_prices.dropna()
    if prices.empty or daily_flows.empty:
        return pd.Series(dtype=float)

    start = min(daily_flows.index.min(), prices.index.min())
    days = pd.date_range(start, prices.index.max(), freq='D')
    daily_prices = prices.reindex(days).ffill().bfill()

    flows = daily_flows.groupby(daily_flows.index.normalize()).sum().reindex(days, fill_value=0.0)
    shares = (flows / daily_prices).cumsum()
    value = shares * daily_prices
    first_flow = daily_flows.index.min().normalize()
    return value[value.index >= first_flow]


# ── time windows for the comparison chart ─────────────────────────────────────

# Point-based ranges count valued days (the data is daily closes, so 1D is the
# last close vs. the one before); calendar ranges go back by date.
RANGES = {
    '1D': 1, '5D': 5,
    '1M': pd.DateOffset(months=1), '6M': pd.DateOffset(months=6),
    '1Y': pd.DateOffset(years=1), '5Y': pd.DateOffset(years=5),
    'ALL': None,
}


def window_start(index: pd.DatetimeIndex, range_key: str) -> tuple:
    """(start date, clipped) for a range ending at the last date in `index`.

    Calendar ranges start on the last date on or before the cutoff so the
    window covers the whole range. `clipped` is True when history is shorter
    than the range and the window falls back to the first date.
    """
    spec = RANGES[range_key]
    if spec is None:
        return index[0], False
    if isinstance(spec, int):
        return (index[-(spec + 1)], False) if len(index) > spec else (index[0], True)
    cutoff = index[-1] - spec
    before = index[index <= cutoff]
    return (before[-1], False) if len(before) else (index[0], True)


def compare_window(portfolio_value: pd.Series, daily_flows: pd.Series,
                   benchmark_prices: pd.Series, range_key: str) -> dict:
    """Portfolio vs. benchmark over a time window.

    The benchmark starts with the portfolio's value on the window's first day
    (all of it bought at that day's price) and then buys or sells with each
    deposit or withdrawal inside the window. 'ALL' starts from zero, so it
    equals benchmark_value over the full history.
    """
    if daily_flows.empty:
        daily_flows = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    start, clipped = window_start(portfolio_value.index, range_key)
    end = portfolio_value.index[-1]
    pv = portfolio_value[portfolio_value.index >= start]

    if range_key == 'ALL':
        start_value, flows = 0.0, daily_flows[daily_flows.index >= start]
    else:
        start_value, flows = float(pv.iloc[0]), daily_flows[daily_flows.index > start]
    flows = flows[flows.index <= end]

    days = pd.date_range(start, end, freq='D')
    prices = benchmark_prices.dropna()
    if prices.empty:
        bench = pd.Series(dtype=float)
        bench_return = None
    else:
        daily_prices = prices.reindex(prices.index.union(days)).ffill().bfill().reindex(days)
        daily_flows_in = flows.groupby(flows.index.normalize()).sum().reindex(days, fill_value=0.0)
        shares = start_value / daily_prices.iloc[0] + (daily_flows_in / daily_prices).cumsum()
        bench = (shares * daily_prices).reindex(pv.index)
        bench_return = float(daily_prices.iloc[-1] / daily_prices.iloc[0] - 1)

    invested = start_value + align_flows(flows, pv.index).cumsum()
    twr = calculate_twr(pv, flows if range_key == 'ALL' else daily_flows[daily_flows.index > start])
    return {
        'range': range_key,
        'start': start,
        'end': end,
        'clipped': clipped,
        'portfolio': pv,
        'benchmark': bench,
        'invested': invested,
        'portfolio_return': twr,
        'benchmark_return': bench_return,
        'diff': float(pv.iloc[-1] - bench.iloc[-1]) if not bench.empty else None,
    }


# ── profit by stock, split by tax term ────────────────────────────────────────

PROFIT_COLUMNS = ['realized_st', 'realized_lt', 'unrealized_st', 'unrealized_lt',
                  'retirement', 'total', 'shares', 'next_lt_date', 'next_lt_shares',
                  'held_days', 'sold_days']


def stock_profit_breakdown(parts: list, today=None) -> pd.DataFrame:
    """Realized and unrealized P/L per stock, split into short- and long-term.

    `parts` is a list of (account_type, enriched holdings, realized sales), one
    per account, so first-in-first-out lot matching stays within each account
    (as Fidelity does). Retirement accounts are not taxed by holding period, so
    their gains go to a single 'retirement' column. Unrealized shares are
    classed by how long they have been held as of `today`; `next_lt_date` is
    when the next short-term shares turn long-term. `held_days` is the
    share-weighted average age of shares still held; `sold_days` the
    share-weighted average holding period of shares sold (NaN when none).
    """
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    rows = {}
    share_days = {}   # symbol -> [held share-days, sold share-days, sold shares]

    def row(symbol):
        return rows.setdefault(symbol, {c: 0.0 for c in PROFIT_COLUMNS} |
                               {'next_lt_date': pd.NaT, 'next_lt_shares': 0.0})

    for account_type, holdings, realized in parts:
        retirement = account_type == 'retirement'
        for sale in realized:
            r = row(sale['Symbol'])
            acc = share_days.setdefault(sale['Symbol'], [0.0, 0.0, 0.0])
            acc[1] += sale.get('Holding Days', 0) * sale.get('Qty', 0)
            acc[2] += sale.get('Qty', 0)
            if retirement:
                r['retirement'] += sale['Realized P/L']
            else:
                r['realized_st'] += sale.get('Short-Term P/L', 0.0)
                r['realized_lt'] += sale.get('Long-Term P/L', 0.0)
        for h in holdings:
            r = row(h['Symbol'])
            r['shares'] += h['Quantity']
            price = h.get('Current Price') or 0.0
            for lot in h.get('Lots', []):
                share_days.setdefault(h['Symbol'], [0.0, 0.0, 0.0])[0] += lot['qty'] * (today - lot['date']).days
                gain = lot['qty'] * (price - lot['cost']) if price else 0.0
                if retirement:
                    r['retirement'] += gain
                elif is_long_term(lot['date'], today):
                    r['unrealized_lt'] += gain
                else:
                    r['unrealized_st'] += gain
                    turns_lt = lot['date'] + pd.DateOffset(years=1) + pd.Timedelta(days=1)
                    if pd.isna(r['next_lt_date']) or turns_lt < r['next_lt_date']:
                        r['next_lt_date'], r['next_lt_shares'] = turns_lt, lot['qty']
                    elif turns_lt == r['next_lt_date']:
                        r['next_lt_shares'] += lot['qty']

    if not rows:
        return pd.DataFrame(columns=PROFIT_COLUMNS)
    for symbol, (held, sold, sold_qty) in share_days.items():
        r = rows[symbol]
        r['held_days'] = held / r['shares'] if r['shares'] else float('nan')
        r['sold_days'] = sold / sold_qty if sold_qty else float('nan')
    df = pd.DataFrame.from_dict(rows, orient='index')[PROFIT_COLUMNS]
    df['total'] = df[['realized_st', 'realized_lt', 'unrealized_st', 'unrealized_lt', 'retirement']].sum(axis=1)
    return df.sort_values('total', ascending=False)


# ── tax-year view, search and filters ─────────────────────────────────────────

TAX_YEAR_COLUMNS = ['realized_st', 'realized_lt', 'dividends', 'foreign_tax', 'total']


def _taxable(df: pd.DataFrame) -> pd.DataFrame:
    if 'Account Type' not in df.columns:
        return df
    return df[df['Account Type'] != 'retirement']


def yearly_tax_summary(df: pd.DataFrame, realized: list) -> pd.DataFrame:
    """Per calendar year, for taxable (non-retirement) accounts: short- and
    long-term realized gains, dividends received (reinvested ones included,
    they are taxable too) and foreign tax withheld. `total` is gains plus
    dividends; foreign tax is shown separately since it is usually a credit."""
    taxable = _taxable(df)
    by_year = {}

    def row(year):
        return by_year.setdefault(int(year), {c: 0.0 for c in TAX_YEAR_COLUMNS})

    for sale in realized:
        if sale.get('Account Type') == 'retirement':
            continue
        r = row(sale['Date'].year)
        r['realized_st'] += sale.get('Short-Term P/L', 0.0)
        r['realized_lt'] += sale.get('Long-Term P/L', 0.0)
    for category, column, sign in (('DIVIDEND', 'dividends', 1), ('TAX', 'foreign_tax', -1)):
        rows = taxable[taxable['Category'] == category]
        for year, amount in rows.groupby(rows['Run Date'].dt.year)['Amount'].sum().items():
            row(year)[column] += sign * amount

    if not by_year:
        return pd.DataFrame(columns=TAX_YEAR_COLUMNS)
    out = pd.DataFrame.from_dict(by_year, orient='index')[TAX_YEAR_COLUMNS].sort_index()
    out['total'] = out['realized_st'] + out['realized_lt'] + out['dividends']
    return out


def filter_realized(realized: list, year=None, query=None) -> list:
    """Sales in `year` (None or 'all' for every year) whose symbol contains `query`."""
    q = (query or '').strip().upper()
    return [r for r in realized
            if (year in (None, 'all') or r['Date'].year == int(year))
            and q in str(r['Symbol']).upper()]


def last_sales(realized: list) -> dict:
    """Most recent sale per symbol: {symbol: {'date', 'price'}}."""
    out = {}
    for r in sorted(realized, key=lambda r: r['Date']):
        out[r['Symbol']] = {'date': r['Date'], 'price': r['Sell Price']}
    return out


def search_breakdown(breakdown: pd.DataFrame, query) -> pd.DataFrame:
    q = (query or '').strip().upper()
    if not q:
        return breakdown
    return breakdown[breakdown.index.astype(str).str.upper().str.contains(q, regex=False)]
