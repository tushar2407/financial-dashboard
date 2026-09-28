import json
import os
import threading
from datetime import datetime, timedelta

import dash
from dash import html, dcc, ctx, ALL
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
import pandas as pd
from data_loader import (get_current_cash, load_and_clean_data, categorize_transactions, get_portfolio_history,
                         fetch_price_data, calculate_portfolio_value, fetch_sector_data,
                         discover_accounts, tag_account_types)
from metrics import calculate_dividend_income, calculate_xirr, calculate_cagr, calculate_net_invested, calculate_cost_basis, calculate_net_invested_breakdown, get_daily_cash_flows, calculate_performance_metrics, calculate_yearly_returns
from components import create_card, create_portfolio_graph, create_history_table, create_yearly_returns_chart, create_category_accordion_item
from fidelity_scraper import get_latest_transaction_date, run_scraper

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

# ── background fetch state ────────────────────────────────────────────────────
_fetch_state = {"status": "idle", "message": ""}  # statuses: idle | fetching | done | error


def _run_scraper_background() -> None:
    global global_df, global_prices, global_sectors, all_symbols
    _fetch_state["status"] = "fetching"
    _fetch_state["message"] = "Fetching latest data from Fidelity..."
    try:
        run_scraper()
        # Reload globals so the next page interaction picks up new data
        global_df = categorize_transactions(load_and_clean_data())
        all_symbols = [s for s in global_df['Symbol'].dropna().unique()
                       if isinstance(s, str) and s.strip() != '']
        start_date = global_df['Run Date'].min().strftime('%Y-%m-%d')
        global_prices = fetch_price_data(all_symbols, start_date, tx_df=global_df)
        global_sectors = fetch_sector_data(all_symbols)
        _fetch_state["status"] = "done"
        _fetch_state["message"] = "Data updated. Refresh the page to see the latest figures."
    except Exception as exc:
        _fetch_state["status"] = "error"
        _fetch_state["message"] = f"Fetch failed: {exc}"


def _maybe_start_background_fetch() -> None:
    """Check if data is stale and warn (but don't auto-launch the scraper,
    since it opens Chrome and requires MFA)."""
    latest = get_latest_transaction_date()
    if latest.date() < (datetime.now() - timedelta(days=1)).date():
        print(f"\n⚠️  Data is stale (latest: {latest.date()}). "
              f"Run 'python fetch_data.py' to update.\n")
    else:
        print(f"Data is up to date (latest: {latest.date()}). Skipping fetch.")


# ── Load Data Globally (to avoid reloading on every callback) ─────────────────
print("Loading data...")
global_df = load_and_clean_data()
global_df = categorize_transactions(global_df)

# Discover accounts and tag types
account_meta = discover_accounts(global_df)
global_df = tag_account_types(global_df, account_meta)
print(f"Discovered {len(account_meta['accounts'])} accounts: "
      f"{[a['name'] for a in account_meta['accounts']]}")

# Fetch prices for all symbols once
all_symbols = global_df['Symbol'].dropna().unique()
all_symbols = [s for s in all_symbols if isinstance(s, str) and s.strip() != '']
start_date = global_df['Run Date'].min().strftime('%Y-%m-%d')
global_prices = fetch_price_data(all_symbols, start_date, tx_df=global_df)
global_sectors = fetch_sector_data(all_symbols)

_maybe_start_background_fetch()

app = dash.Dash(__name__,
                external_stylesheets=[dbc.themes.DARKLY],
                assets_folder='../assets',
                suppress_callback_exceptions=True)
server = app.server
app.title = "Financial Dashboard"

# ── Dynamic tab & filter helpers ──────────────────────────────────────────────
def _acct_tab_id(name: str) -> str:
    """Convert an account name to a stable tab ID."""
    return f"acct_{name.lower().replace(' ', '_')}"


def _build_account_tabs(meta: dict) -> list:
    """Build the list of dbc.Tab objects from discovered account metadata."""
    tabs = []

    # One tab per individual account
    for acct in meta['accounts']:
        tabs.append(dbc.Tab(label=acct['name'], tab_id=_acct_tab_id(acct['name'])))

    # "All Brokerage" aggregate tab if 2+ brokerage accounts exist
    if len(meta['brokerage_accounts']) >= 2:
        tabs.append(dbc.Tab(label='All Brokerage', tab_id='all_brokerage'))

    # "Combined" tab if there are both brokerage and retirement accounts
    if meta['brokerage_accounts'] and meta['retirement_accounts']:
        tabs.append(dbc.Tab(label='Combined', tab_id='combined'))

    return tabs


def _filter_df(account_tab: str):
    """Filter global_df based on the selected account tab."""
    if account_tab == 'all_brokerage':
        return global_df[global_df['Account'].isin(account_meta['brokerage_accounts'])].copy()
    if account_tab == 'combined':
        return global_df.copy()

    # Individual account tab: match by tab ID → account name
    for acct in account_meta['accounts']:
        if _acct_tab_id(acct['name']) == account_tab:
            return global_df[global_df['Account'] == acct['name']].copy()

    # Fallback: return everything
    return global_df.copy()


app.layout = html.Div([
    dcc.Interval(id='fetch-status-interval', interval=3000, n_intervals=0),
    dbc.Toast(
        id='fetch-status-toast',
        header="Data Sync",
        is_open=False,
        dismissable=True,
        duration=0,
        style={"position": "fixed", "top": 20, "right": 20, "width": 360, "zIndex": 9999},
    ),
    dcc.Store(id='categories-store', data=load_categories()),
    dbc.Container([
        # Centered Apple-style Header
        html.Div([
            html.H1("Financial Dashboard", className="text-center mb-2 text-white display-4",
                    style={'fontWeight': '700', 'letterSpacing': '-0.04em'}),
            html.P("Portfolio Analytics & Performance",
                   className="text-center text-muted mb-0 lead",
                   style={'fontWeight': '400', 'letterSpacing': '-0.02em'}),
        ], className="dashboard-header mb-5"),

        # ── Dynamic account tabs ──────────────────────────────────────────────
        dbc.Row([
            dbc.Col([
                dbc.Tabs(
                    id='account-tabs',
                    active_tab=f"acct_{account_meta['accounts'][0]['name'].lower().replace(' ', '_')}" if account_meta['accounts'] else 'combined',
                    children=_build_account_tabs(account_meta),
                    className='justify-content-center mb-5',
                ),
            ], width=12)
        ]),

        # Summary cards + performance charts (dynamic per account)
        html.Div(id='dashboard-content'),

        # Inner content tabs: Holdings | History
        dbc.Row([
            dbc.Col([
                dbc.Tabs(id='content-tabs', active_tab='holdings', children=[
                    dbc.Tab(label='Holdings', tab_id='holdings'),
                    dbc.Tab(label='History', tab_id='history'),
                ], className='mb-0'),
            ], width=12)
        ], className="mt-2"),
        html.Div(id='content-tab-body', className="mb-5 mt-3"),

    ], fluid=False, className="pb-5")
], style={'overflowX': 'hidden'})

@app.callback(
    Output('fetch-status-toast', 'children'),
    Output('fetch-status-toast', 'is_open'),
    Output('fetch-status-toast', 'icon'),
    Output('fetch-status-interval', 'disabled'),
    Input('fetch-status-interval', 'n_intervals'),
)
def update_fetch_status(n):
    status = _fetch_state["status"]
    message = _fetch_state["message"]
    if status == "idle":
        return "", False, "primary", True
    if status == "fetching":
        return message, True, "warning", False
    if status == "done":
        return message, True, "success", True
    if status == "error":
        return message, True, "danger", True
    return "", False, "primary", True


@app.callback(
    Output('dashboard-content', 'children'),
    [Input('account-tabs', 'active_tab')]
)
def update_dashboard(tab):
    # Filter Data based on dynamic tab ID
    df = _filter_df(tab)
        
    if df.empty:
        return html.Div([
            html.H3("No Data Available", className="text-center text-muted mt-5")
        ])

    # Recalculate everything for the filtered DF
    holdings, symbols = get_portfolio_history(df)
    
    # We can reuse global prices
    prices = global_prices
    
    portfolio_value = calculate_portfolio_value(holdings, prices)
    net_invested = calculate_net_invested(df)
    net_invested_breakdown = calculate_net_invested_breakdown(df)

    # Calculate Metrics
    current_val = portfolio_value.iloc[-1] if not portfolio_value.empty else 0
    total_invested = net_invested.iloc[-1] if not net_invested.empty else 0
    pl = current_val - total_invested
    pl_pct = (pl / total_invested * 100) if total_invested != 0 else 0

    # XIRR Metrics
    daily_flows = get_daily_cash_flows(df)
    perf_metrics = calculate_performance_metrics(portfolio_value, daily_flows)
    
    # Lifetime metrics
    cagr = perf_metrics.get('Lifetime_XIRR', 0) * 100
    lifetime_twr = perf_metrics.get('Lifetime_TWR', 0) * 100
    
    # 1Y metrics
    yoy_xirr = perf_metrics.get('1Y_XIRR', 0) * 100
    yoy_twr = perf_metrics.get('1Y_TWR', 0) * 100
    
    # YTD metrics
    ytd_xirr = perf_metrics.get('YTD_XIRR', 0) * 100
    ytd_twr = perf_metrics.get('YTD_TWR', 0) * 100

    # Detailed Holdings & History
    current_holdings_data, realized_pnl_data = calculate_cost_basis(df)
    _enrich_holdings(current_holdings_data, prices)

    # Calculate realized and unrealized P/L
    total_realized_pl = sum(pnl['Realized P/L'] for pnl in realized_pnl_data)
    total_unrealized_pl = sum(item.get('Unrealized P/L', 0) for item in current_holdings_data)
    dividend_income = calculate_dividend_income(df)

    # Annual Performance
    yearly_data = calculate_yearly_returns(portfolio_value, daily_flows)
    
    # Extract Previous Year (2025) for Summary Cards
    prev_year_metrics = next((y for y in yearly_data if y['Year'] == 2025), {'XIRR': 0, 'TWR': 0})
    py_xirr = prev_year_metrics['XIRR'] * 100
    py_twr = prev_year_metrics['TWR'] * 100

    # Dates for tooltips
    data_start = df['Run Date'].min().strftime('%b %d, %Y')
    data_end = df['Run Date'].max().strftime('%b %d, %Y')
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

    return html.Div([
        dbc.Row([
            dbc.Col(create_card("Current Value", f"${current_val:,.2f}", f"{pl_pct:+.2f}% All Time", "primary"), width=12, md=6, lg=3, className="mb-4"),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Net Invested", className="card-subtitle mb-2 text-muted text-uppercase"),
                        html.H2(f"${total_invested:,.2f}", className="card-title text-white"),
                        html.Hr(className="my-2 border-secondary"),
                        html.Div([
                            # Transfers (external EFTs) — show if non-zero
                            *(
                                [
                                    html.Div([
                                        html.Span("Transfers", className="text-muted small"),
                                        html.Span(f"${net_invested_breakdown['transfers']:,.2f}", className="float-end text-white small")
                                    ], className="d-flex justify-content-between mb-1")
                                ] if net_invested_breakdown['transfers'] != 0 else []
                            ),
                            # ESPP — show if non-zero
                            *(
                                [
                                    html.Div([
                                        html.Span("ESPP", className="text-muted small"),
                                        html.Span(f"${net_invested_breakdown['espp']:,.2f}", className="float-end text-white small")
                                    ], className="d-flex justify-content-between mb-1")
                                ] if net_invested_breakdown['espp'] != 0 else []
                            ),
                            # Contributions – only for views that include 401k
                            *(
                                [
                                    html.Div([
                                        html.Span("Contributions", className="text-muted small"),
                                        html.Span(f"${net_invested_breakdown['contributions']:,.2f}", className="float-end text-white small")
                                    ], className="d-flex justify-content-between mb-1")
                                ] if net_invested_breakdown['contributions'] != 0 else []
                            ),
                            # Internal Transfers — show if non-zero (nets to $0 in combined views)
                            *(
                                [
                                    html.Div([
                                        html.Span("Internal Transfers", className="text-muted small"),
                                        html.Span(f"${net_invested_breakdown['internal_transfers']:,.2f}",
                                                   className=f"float-end small {'text-success' if net_invested_breakdown['internal_transfers'] >= 0 else 'text-danger'}")
                                    ], className="d-flex justify-content-between mb-1")
                                ] if abs(net_invested_breakdown['internal_transfers']) > 0.01 else []
                            ),
                            # Withdrawals — show if non-zero
                            *(
                                [
                                    html.Div([
                                        html.Span("Withdrawals", className="text-muted small"),
                                        html.Span(f"${net_invested_breakdown['withdrawals']:,.2f}", className="float-end text-white small")
                                    ], className="d-flex justify-content-between")
                                ] if net_invested_breakdown['withdrawals'] != 0 else []
                            ),
                        ])
                    ], className="p-3")
                ], className="glass-card h-100")
            ], width=12, md=6, lg=3, className="mb-4"),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Total P&L", className="card-subtitle mb-2 text-muted text-uppercase"),
                        html.H2(f"${pl:,.2f}", className=f"card-title {'text-success' if pl >= 0 else 'text-danger'}"),
                        html.Hr(className="my-2 border-secondary"),
                        html.Div([
                            html.Div([
                                html.Span("Realized", className="text-muted small"),
                                html.Span(f"${total_realized_pl:,.2f}", className=f"float-end {'text-success' if total_realized_pl >= 0 else 'text-danger'} small")
                            ], className="d-flex justify-content-between mb-1"),
                            html.Div([
                                html.Span("Unrealized", className="text-muted small"),
                                html.Span(f"${total_unrealized_pl:,.2f}", className="float-end small", style={'color': 'var(--apple-green)' if total_unrealized_pl >= 0 else 'var(--apple-red)'})
                            ], className="d-flex justify-content-between mb-1"),
                            html.Div([
                                html.Span("Dividends (net)", className="text-muted small"),
                                html.Span(f"${dividend_income:,.2f}", className=f"float-end {'text-success' if dividend_income >= 0 else 'text-danger'} small")
                            ], className="d-flex justify-content-between")
                        ])
                    ], className="p-3")
                ], className="glass-card h-100")
            ], width=12, md=6, lg=3, className="mb-4"),
            dbc.Col(
                create_card("Personal Return (XIRR)", f"{cagr:.2f}%", f"{yoy_xirr:+.2f}% 1Y", "info", annotation="till date", info=xirr_info),
                width=12, md=6, lg=3, className="mb-4"
            ),
            dbc.Col(
                create_card("Portfolio Return (TWR)", f"{lifetime_twr:.2f}%", f"{yoy_twr:+.2f}% 1Y", "success", annotation="till date", info=twr_info),
                width=12, md=6, lg=3, className="mb-4"
            ),
        ]),
        
        dbc.Row([
            dbc.Col([
                html.Div([
                    create_portfolio_graph(portfolio_value, net_invested)
                ], className="glass-card p-4")
            ], width=12, lg=8, className="mb-5"),
            dbc.Col([
                html.Div([
                    create_yearly_returns_chart(yearly_data)
                ], className="glass-card p-4 h-100")
            ], width=12, lg=4, className="mb-5")
        ]),
    ])



@app.callback(
    Output('content-tab-body', 'children'),
    Input('content-tabs', 'active_tab'),
    Input('account-tabs', 'active_tab'),
    Input('categories-store', 'data'),
)
def update_content_tab(content_tab, account_tab, categories_data):
    df = _filter_df(account_tab)
    if df.empty:
        return html.Div("No data available.", className="text-muted p-4")

    current_holdings_data, realized_pnl_data = calculate_cost_basis(df)
    _enrich_holdings(current_holdings_data, global_prices)

    if content_tab == 'history':
        return html.Div([
            html.H4("Transaction History (Realized P/L)", className="text-white mb-4"),
            create_history_table(realized_pnl_data)
        ], className="glass-card p-4")

    # holdings tab: Portfolio (pinned) + user categories + create form
    categories = categories_data or {}
    cash = get_current_cash(df)
    total_portfolio_value = sum(h.get('Market Value', 0) for h in current_holdings_data) + cash
    held_symbols = sorted(h['Symbol'] for h in current_holdings_data)
    symbol_options = [{'label': s, 'value': s} for s in held_symbols]

    accordion_items = [
        create_category_accordion_item(
            "Portfolio", current_holdings_data, total_portfolio_value, deletable=False, cash=cash
        )
    ]
    for cat_name, cat_symbols in categories.items():
        cat_holdings = [h for h in current_holdings_data if h['Symbol'] in cat_symbols]
        accordion_items.append(
            create_category_accordion_item(cat_name, cat_holdings, total_portfolio_value)
        )

    return html.Div([
        dbc.Accordion(accordion_items, start_collapsed=True, className="category-accordion mb-4"),
        html.Div([
            html.H6("Create Category", className="text-white mb-3"),
            dbc.Row([
                dbc.Col(
                    dbc.Input(
                        id='category-name-input',
                        placeholder='Category name (e.g. Memory, Quantum)...',
                        style={'backgroundColor': 'rgba(255,255,255,0.07)',
                               'border': '1px solid rgba(255,255,255,0.2)',
                               'color': 'white'},
                    ),
                    width=12, md=4, className="mb-2 mb-md-0"
                ),
                dbc.Col(
                    dcc.Dropdown(
                        id='category-symbols-dropdown',
                        options=symbol_options,
                        multi=True,
                        placeholder='Select stocks...',
                        style={'backgroundColor': 'rgba(30,30,30,0.9)'},
                    ),
                    width=12, md=6, className="mb-2 mb-md-0"
                ),
                dbc.Col(
                    dbc.Button('Create', id='create-category-btn',
                               color='primary', n_clicks=0, className="w-100"),
                    width=12, md=2
                ),
            ], className="align-items-center"),
        ], className="glass-card p-4", style={"position": "relative", "zIndex": 10}),
    ])


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
