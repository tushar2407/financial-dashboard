import json
import os
import sys
from functools import lru_cache

import dash
from dash import html, dcc, ctx, ALL
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
import pandas as pd
from data_loader import (get_current_cash, load_and_clean_data, categorize_transactions, get_portfolio_history,
                         fetch_price_data, calculate_portfolio_value, fetch_sector_data,
                         discover_accounts, tag_account_types)
from metrics import (calculate_dividend_income, calculate_net_invested, calculate_cost_basis,
                     calculate_net_invested_breakdown, get_daily_cash_flows, calculate_performance_metrics,
                     calculate_yearly_returns)
from components import create_history_table
from insights import (allocation_summary, compare_window, filter_realized, last_sales, load_goals,
                      monthly_deposits, realized_by_symbol, search_breakdown,
                      stock_profit_breakdown, trading_summary, trades_per_month,
                      yearly_tax_summary)
from charts import (allocation_treemap, growth_vs_benchmark, monthly_bars, realized_by_symbol_chart,
                    tax_years_chart, yearly_returns_chart)
import views
from fidelity_scraper import refresh_if_stale

# ── category storage ──────────────────────────────────────────────────────────
CATEGORIES_PATH = os.path.join('data', 'stock_categories.json')


def load_categories() -> dict:
    if os.path.exists(CATEGORIES_PATH):
        with open(CATEGORIES_PATH) as f:
            return json.load(f)
    return {}


def save_categories(cats: dict) -> None:
    with open(CATEGORIES_PATH, 'w') as f:
        json.dump(cats, f, indent=2)


def _enrich_holdings(holdings_data: list, prices) -> list:
    """Add Current Price, Market Value, Unrealized P/L, P/L % to each holding in-place."""
    if not prices.empty:
        latest_prices = prices.iloc[-1]
        for item in holdings_data:
            sym = item['Symbol']
            if sym in latest_prices:
                curr_price = latest_prices[sym]
                item['Current Price'] = curr_price
                item['Market Value'] = item['Quantity'] * curr_price
                item['Unrealized P/L'] = item['Market Value'] - item['Total Cost']
                item['P/L %'] = (item['Unrealized P/L'] / item['Total Cost']) if item['Total Cost'] != 0 else 0
            else:
                item['Current Price'] = 0
                item['Market Value'] = 0
                item['Unrealized P/L'] = 0
                item['P/L %'] = 0
    return holdings_data

# ── Refresh stale data on server start ────────────────────────────────────────
# Only when launched as a server (not when imported, e.g. by tests), and only in
# the first process: Dash's debug reloader re-runs this module in a child
# process with WERKZEUG_RUN_MAIN=true, which then loads the freshly fetched data.
_IS_SERVER_START = __name__ == '__main__' and os.environ.get('WERKZEUG_RUN_MAIN') != 'true'
if _IS_SERVER_START and '--no-fetch' not in sys.argv:
    refresh_if_stale()


# ── Load Data Globally (to avoid reloading on every callback) ─────────────────
print("Loading data...")
global_df = load_and_clean_data()
global_df = categorize_transactions(global_df)

# Discover accounts and tag types
account_meta = discover_accounts(global_df)
global_df = tag_account_types(global_df, account_meta)
print(f"Discovered {len(account_meta['accounts'])} accounts: "
      f"{[a['name'] for a in account_meta['accounts']]}")

goals = load_goals()
BENCHMARK = goals['benchmark']

# Fetch prices for all symbols (plus the benchmark) once
all_symbols = global_df['Symbol'].dropna().unique()
all_symbols = [s for s in all_symbols if isinstance(s, str) and s.strip() != '']
start_date = global_df['Run Date'].min().strftime('%Y-%m-%d')
global_prices = fetch_price_data(sorted(set(all_symbols) | {BENCHMARK}), start_date, tx_df=global_df)

# Held symbols valued at an old trade price because the market download failed
_held_symbols = {h['Symbol'] for h in calculate_cost_basis(global_df)[0]}
stale_held_symbols = sorted(_held_symbols & set(global_prices.attrs.get('stale_symbols', [])))
if stale_held_symbols:
    print(f"\nWARNING: no recent market price for {len(stale_held_symbols)} holding(s); "
          f"valuing them at their last trade price: {', '.join(stale_held_symbols)}\n")
global_sectors = fetch_sector_data(all_symbols, retry_unknown=_held_symbols)

app = dash.Dash(__name__,
                external_stylesheets=[dbc.themes.DARKLY],
                assets_folder='../assets',
                suppress_callback_exceptions=True)
server = app.server
app.title = "Financial Dashboard"

# ── Account filter helpers ────────────────────────────────────────────────────
def _acct_tab_id(name: str) -> str:
    """Convert an account name to a stable filter value."""
    return f"acct_{name.lower().replace(' ', '_')}"


def _account_options(meta: dict) -> list:
    """Dropdown options: groups first (when they add something), then accounts."""
    options = []
    if meta['brokerage_accounts'] and meta['retirement_accounts']:
        options.append({'label': 'All accounts', 'value': 'combined'})
    if len(meta['brokerage_accounts']) >= 2:
        options.append({'label': 'Brokerage', 'value': 'all_brokerage'})
    if len(meta['retirement_accounts']) >= 2:
        options.append({'label': 'Retirement', 'value': 'all_retirement'})
    options += [{'label': a['name'], 'value': _acct_tab_id(a['name'])} for a in meta['accounts']]
    return options


def _filter_df(account_tab: str):
    """Filter global_df based on the selected account filter value."""
    if account_tab == 'all_brokerage':
        return global_df[global_df['Account'].isin(account_meta['brokerage_accounts'])].copy()
    if account_tab == 'all_retirement':
        return global_df[global_df['Account'].isin(account_meta['retirement_accounts'])].copy()
    if account_tab == 'combined':
        return global_df.copy()

    for acct in account_meta['accounts']:
        if _acct_tab_id(acct['name']) == account_tab:
            return global_df[global_df['Account'] == acct['name']].copy()

    return global_df.copy()


_ACCOUNT_OPTIONS = _account_options(account_meta)

app.layout = html.Div([
    dcc.Store(id='categories-store', data=load_categories()),
    dbc.Container([
        html.Div([
            html.H1("Financial Dashboard", className="text-center mb-2 text-white display-4",
                    style={'fontWeight': '700', 'letterSpacing': '-0.04em'}),
            html.P("Portfolio Analytics & Performance",
                   className="text-center text-muted mb-0 lead",
                   style={'fontWeight': '400', 'letterSpacing': '-0.02em'}),
        ], className="dashboard-header mb-5"),

        dbc.Alert(
            [
                html.Strong("Prices are out of date. "),
                f"Market prices for {len(stale_held_symbols)} holding(s) could not be downloaded, "
                f"so they are valued at their last trade price: {', '.join(stale_held_symbols)}. "
                "Upgrade yfinance (pip install -U yfinance) or start the app with venv/bin/python.",
            ],
            color="warning", className="mb-4",
        ) if stale_held_symbols else None,

        # ── Controls: view tabs + account filter, in one row ──────────────────
        dbc.Row([
            dbc.Col(dbc.Tabs(id='view-tabs', active_tab='overview', children=[
                dbc.Tab(label='Overview', tab_id='overview'),
                dbc.Tab(label='Allocation', tab_id='allocation'),
                dbc.Tab(label='Behavior', tab_id='behavior'),
            ], className='view-tabs'), width=12, md=True, className="mb-3 mb-md-0"),
            dbc.Col(dcc.Dropdown(
                id='account-select', options=_ACCOUNT_OPTIONS,
                value=_ACCOUNT_OPTIONS[0]['value'] if _ACCOUNT_OPTIONS else 'combined',
                clearable=False, searchable=False, className='account-select',
            ), width=12, md=4, lg=3),
        ], className="align-items-center controls-row mb-4"),

        # Spinner only when the whole view is rebuilt (tab/account change), not
        # when a callback updates something inside it (search, filters, ranges)
        dcc.Loading(html.Div(id='view-content'), type='dot', color='#3987e5',
                    target_components={'view-content': 'children'}),

    ], fluid=False, className="pb-5")
], style={'overflowX': 'hidden'})


# ── View builders ─────────────────────────────────────────────────────────────

def _metric_info(df, portfolio_value):
    data_start = df['Run Date'].min().strftime('%b %d, %Y')
    # 1Y metrics are measured back from the last valued day, not the last transaction
    metrics_end = portfolio_value.index[-1] if not portfolio_value.empty else df['Run Date'].max()
    y1_start = (metrics_end - pd.Timedelta(days=365)).strftime('%b %d, %Y')
    xirr_info = [
        html.P("Your personal return. It accounts for when and how much money "
               "you put in or took out, so good or bad timing shows up here."),
        html.P(f"Headline: annualized, {data_start} to today. "
               f"1Y: annualized, trailing year from {y1_start}."),
        html.P("Use it to answer: how did my money actually grow?", className="mb-0"),
    ]
    twr_info = [
        html.P("How your investments performed, ignoring the size and timing of "
               "deposits and withdrawals."),
        html.P(f"Headline: total (not annualized) return, {data_start} to today. "
               f"1Y: trailing year from {y1_start}."),
        html.P("Use it to compare against an index like the S&P 500.", className="mb-0"),
    ]
    return xirr_info, twr_info


def _enriched_holdings(df):
    holdings, realized = calculate_cost_basis(df)
    return _enrich_holdings(holdings, global_prices), realized


@lru_cache(maxsize=16)
def _history(account: str):
    """Portfolio value, net invested and cash flows for an account filter.
    Data is loaded once per server start, so results can be cached."""
    df = _filter_df(account)
    history, _ = get_portfolio_history(df)
    return (calculate_portfolio_value(history, global_prices),
            calculate_net_invested(df), get_daily_cash_flows(df))


def _overview(df, account):
    portfolio_value, net_invested, daily_flows = _history(account)
    perf = calculate_performance_metrics(portfolio_value, daily_flows)
    holdings, realized = _enriched_holdings(df)

    current_val = portfolio_value.iloc[-1] if not portfolio_value.empty else 0
    total_invested = net_invested.iloc[-1] if not net_invested.empty else 0
    pl = current_val - total_invested
    xirr_info, twr_info = _metric_info(df, portfolio_value)
    summary = {
        'current_val': current_val,
        'pl_pct': (pl / total_invested * 100) if total_invested else 0,
        'total_invested': total_invested,
        'breakdown': calculate_net_invested_breakdown(df),
        'pl': pl,
        'realized': sum(r['Realized P/L'] for r in realized),
        'unrealized': sum(h.get('Unrealized P/L', 0) for h in holdings),
        'dividends': calculate_dividend_income(df),
        'xirr': (perf.get('Lifetime_XIRR') or 0) * 100,
        'xirr_1y': (perf.get('1Y_XIRR') or 0) * 100,
        'twr': (perf.get('Lifetime_TWR') or 0) * 100,
        'twr_1y': (perf.get('1Y_TWR') or 0) * 100,
        'xirr_info': xirr_info,
        'twr_info': twr_info,
    }
    yearly = calculate_yearly_returns(portfolio_value, daily_flows)
    return views.overview_view(summary, yearly_returns_chart(yearly))


def _allocation(df, categories):
    holdings, _ = _enriched_holdings(df)
    cash = get_current_cash(df)
    alloc = allocation_summary(holdings, cash, global_sectors, goals['cash_target'])
    return views.allocation_view(
        alloc,
        allocation_treemap(alloc['positions'], cash),
        views.holdings_section(holdings, categories, cash, alloc['total']),
    )


def _profit_parts(df):
    """(account type, enriched holdings, realized sales) per account, so lot
    matching stays within each account like Fidelity's."""
    parts = []
    for _, acct_df in df.groupby('Account'):
        holdings, realized = _enriched_holdings(acct_df)
        parts.append((acct_df['Account Type'].iloc[0], holdings, realized))
    return parts


@lru_cache(maxsize=16)
def _behavior_data(account: str):
    """Realized sales and per-stock profit breakdown for an account filter.
    Cached: data is loaded once per server start. Callers must not mutate."""
    df = _filter_df(account)
    _, realized = calculate_cost_basis(df)
    return realized, stock_profit_breakdown(_profit_parts(df))


def _behavior(df, account):
    realized, breakdown = _behavior_data(account)
    tax_summary = yearly_tax_summary(df, realized)
    return views.behavior_view(
        trading_summary(df, realized),
        monthly_bars(trades_per_month(df), "Trades per month", "Trades"),
        monthly_bars(monthly_deposits(df), "New money added per month", "Added", money=True),
        realized_by_symbol_chart(realized_by_symbol(realized)),
        views.tax_year_section(tax_summary, tax_years_chart(tax_summary)),
        views.profit_by_stock_section(breakdown),
        views.closed_trades_section(sorted({r['Date'].year for r in realized})),
    )


@app.callback(
    Output('profit-table-container', 'children'),
    Input('profit-search', 'value'),
    Input('account-select', 'value'),
)
def update_profit_table(query, account):
    realized, breakdown = _behavior_data(account)
    return views.profit_table(search_breakdown(breakdown, query), last_sales(realized),
                              global_prices.iloc[-1], views.has_retirement(breakdown))


@app.callback(
    Output('closed-trades-container', 'children'),
    Input('trades-year', 'value'),
    Input('trades-search', 'value'),
    Input('account-select', 'value'),
)
def update_closed_trades(year, query, account):
    realized, _ = _behavior_data(account)
    return create_history_table(filter_realized(realized, year, query))


@app.callback(
    Output('view-content', 'children'),
    Input('view-tabs', 'active_tab'),
    Input('account-select', 'value'),
    Input('categories-store', 'data'),
)
def render_view(view, account, categories_data):
    df = _filter_df(account)
    if df.empty:
        return html.H3("No Data Available", className="text-center text-muted mt-5")
    if view == 'allocation':
        return _allocation(df, categories_data or {})
    if view == 'behavior':
        return _behavior(df, account)
    return _overview(df, account)


@app.callback(
    Output('compare-chart', 'children'),
    Output('compare-tile', 'children'),
    Input('compare-range', 'value'),
    Input('account-select', 'value'),
)
def update_comparison(range_key, account):
    portfolio_value, _, daily_flows = _history(account)
    if portfolio_value.empty:
        return html.Div("No portfolio history yet", className="text-muted p-4"), None
    bench_prices = global_prices[BENCHMARK] if BENCHMARK in global_prices else pd.Series(dtype=float)
    window = compare_window(portfolio_value, daily_flows, bench_prices, range_key or 'ALL')
    return growth_vs_benchmark(window, BENCHMARK), views.benchmark_tile(window, BENCHMARK)


@app.callback(
    Output('categories-store', 'data'),
    Output('category-name-input', 'value'),
    Output('category-symbols-dropdown', 'value'),
    Input('create-category-btn', 'n_clicks'),
    Input({'type': 'delete-category-btn', 'index': ALL}, 'n_clicks'),
    State('category-name-input', 'value'),
    State('category-symbols-dropdown', 'value'),
    State('categories-store', 'data'),
    prevent_initial_call=True,
)
def manage_categories(_create, _deletes, name, symbols, current_cats):
    current_cats = current_cats or {}
    triggered = ctx.triggered_id

    if triggered == 'create-category-btn':
        if name and name.strip() and symbols:
            current_cats[name.strip()] = symbols
            save_categories(current_cats)
            return current_cats, '', None
        return current_cats, name, symbols

    if isinstance(triggered, dict) and triggered.get('type') == 'delete-category-btn':
        cat_name = triggered['index']
        current_cats.pop(cat_name, None)
        save_categories(current_cats)

    return current_cats, name, symbols


if __name__ == '__main__':
    app.run(debug=True, port=8050)
