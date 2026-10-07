"""Page builders for the Overview, Allocation, Activity and Taxes views."""
from dash import dcc, html
import dash_bootstrap_components as dbc
import pandas as pd

from components import (create_category_accordion_item, data_table, empty_state, kpi, kpi_strip,
                        panel, pl_td, td, two_line)
from formatting import date, money, pct, shares, sign_class

RANGE_OPTIONS = ['1D', '5D', '1M', '6M', '1Y', '5Y', 'ALL']
_RANGE_WORDS = {'1D': "last day", '5D': "last 5 days", '1M': "last month",
                '6M': "last 6 months", '1Y': "last year", '5Y': "last 5 years"}

_TERM_INFO = [
    html.P("Short-term: shares held one year or less when sold. Taxed like ordinary income."),
    html.P("Long-term: shares held more than one year. Taxed at the lower long-term rate."),
    html.P("Shares you still hold are classed by how long you've held them so far; "
           "\"Turns long-term\" is when your next short-term shares cross one year."),
]

_TAX_INFO = [
    html.P("Taxable (non-retirement) accounts only. Dividends include reinvested ones, "
           "which are taxable too. Foreign tax withheld can usually be claimed as a credit."),
    html.P("Estimates from your Fidelity history: no wash-sale adjustments, and ESPP cost "
           "basis is the purchase price. Your 1099 is authoritative."),
]


def _search(input_id: str, placeholder: str = "Search symbol"):
    return dbc.Input(id=input_id, type='search', placeholder=placeholder,
                     className="search-input", autoComplete='off')


# ── Overview ──────────────────────────────────────────────────────────────────

def summary_strip(s: dict):
    """Value, net invested, P&L, XIRR and TWR as one KPI strip.

    `s` holds: current_val, pl_pct, total_invested, breakdown, pl, realized,
    unrealized, dividends, xirr, xirr_1y, twr, twr_1y, xirr_info, twr_info.
    """
    b = s['breakdown']
    invested_rows = [(label, money(v, cents=True), cls) for label, v, cls in (
        ("Transfers", b['transfers'], ""),
        ("ESPP", b['espp'], ""),
        ("Contributions", b['contributions'], ""),
        ("Between accounts", b['internal_transfers'], ""),
        ("Withdrawals", b['withdrawals'], ""),
    ) if abs(v) >= 0.01]
    pl_rows = [(label, money(v, signed=True, cents=True), sign_class(v)) for label, v in (
        ("Realized", s['realized']), ("Unrealized", s['unrealized']), ("Dividends (net)", s['dividends']))]

    return kpi_strip([
        kpi("Portfolio value", money(s['current_val'], cents=True),
            sub=f"{pct(s['pl_pct'] / 100)} all time", sub_class=sign_class(s['pl_pct'])),
        kpi("Net invested", money(s['total_invested'], cents=True), rows=invested_rows),
        kpi("Total P&L", money(s['pl'], signed=True, cents=True), value_class=sign_class(s['pl']),
            rows=pl_rows),
        kpi("Personal return · XIRR", pct(s['xirr'] / 100, signed=False, digits=2),
            sub=f"{pct(s['xirr_1y'] / 100)} last 12 months · annualized", info=s['xirr_info'],
            kpi_id="xirr"),
        kpi("Portfolio return · TWR", pct(s['twr'] / 100, signed=False, digits=2),
            sub=f"{pct(s['twr_1y'] / 100)} last 12 months · cumulative", info=s['twr_info'],
            kpi_id="twr"),
    ])


def _period_words(window: dict) -> str:
    if window['range'] == 'ALL' or window['clipped']:
        return f"Since {date(window['start'])}"
    return f"{_RANGE_WORDS[window['range']].capitalize()} · {date(window['start'])} – {date(window['end'])}"


def benchmark_tile(window: dict, name: str):
    """Standalone KPI comparing the portfolio with the benchmark over a window."""
    info = [html.P(f"Your portfolio compared with putting the same money into {name}: its value "
                   "at the start of the period, plus every deposit or withdrawal on the day it "
                   "happened."),
            html.P(f"Returns ignore deposit timing: yours is time-weighted (TWR), {name}'s is its "
                   "price change.")]
    if window['diff'] is None:
        cell = kpi(f"vs. {name}", "—", sub=f"No {name} prices available", info=info, kpi_id="vs-benchmark")
        return html.Div(cell, className="kpi-standalone")
    diff, you, them = window['diff'], window['portfolio_return'], window['benchmark_return']
    cell = html.Div([
        kpi(f"vs. {name}", money(diff, signed=True), value_class=sign_class(diff),
            sub=f"{'Ahead of' if diff >= 0 else 'Behind'} the same money in {name}",
            info=info, kpi_id="vs-benchmark"),
        html.Div([
            html.Div([html.Span("Period"), html.Span(_period_words(window), className="text-2")]),
            html.Div([html.Span("Your return"), html.Span(pct(you), className=sign_class(you))]),
            html.Div([html.Span(f"{name} return"), html.Span(pct(them), className=sign_class(them))]),
        ], className="kpi-compare"),
    ])
    return html.Div(cell, className="kpi-standalone")


def overview_view(summary: dict, yearly_chart, default_range: str = 'ALL'):
    """Chart and benchmark tile are filled by the range callback."""
    range_picker = dbc.RadioItems(
        id='compare-range', value=default_range,
        options=[{'label': 'All' if r == 'ALL' else r, 'value': r} for r in RANGE_OPTIONS],
        className='segmented', inputClassName='seg-input',
        labelClassName='seg-btn', labelCheckedClassName='active', inline=True,
    )
    chart = dcc.Loading(html.Div(id='compare-chart'), type='circle', color='#3987e5',
                        target_components={'compare-chart': 'children'})
    return html.Div([
        summary_strip(summary),
        html.Div([
            panel("Performance vs. benchmark", chart, actions=range_picker, panel_id="performance"),
            html.Div(id='compare-tile'),
        ], className="grid grid-main-side"),
        panel("Returns by year", yearly_chart, panel_id="returns-by-year"),
    ])


# ── Allocation ────────────────────────────────────────────────────────────────

def allocation_view(alloc: dict, treemap, holdings):
    target, excess = alloc['cash_target'], alloc['cash_excess']
    cash_sub = (f"{money(abs(excess))} {'above' if excess > 0 else 'below'} "
                f"your {pct(target, signed=False, digits=0)} target")
    small = alloc['small_positions']
    return html.Div([
        kpi_strip([
            kpi("Cash", pct(alloc['cash_pct'], signed=False), sub=cash_sub,
                info="Uninvested cash as a share of this view's total. "
                     "Set your target in data/goals.json (cash_target).", kpi_id="cash"),
            kpi("Top 5 positions", pct(alloc['top5_pct'], signed=False), sub="of total value"),
            kpi("Positions", str(alloc['position_count']), sub="securities held"),
            kpi("Under 1% each", str(len(small)),
                sub=", ".join(small) if small else "none", kpi_id="small-positions"),
        ]),
        panel("Allocation by sector", treemap, panel_id="allocation-map"),
        holdings,
    ])


def holdings_section(holdings: list, categories: dict, cash: float, total_value: float):
    """Portfolio (pinned) + user categories, and the create-category form."""
    held_symbols = sorted(h['Symbol'] for h in holdings)
    items = [create_category_accordion_item("All holdings", holdings, total_value,
                                            deletable=False, cash=cash)]
    items += [create_category_accordion_item(name, [h for h in holdings if h['Symbol'] in symbols],
                                             total_value)
              for name, symbols in categories.items()]
    create_form = html.Div([
        dbc.Input(id='category-name-input', placeholder="New category name"),
        dcc.Dropdown(id='category-symbols-dropdown', multi=True, placeholder="Select symbols",
                     options=[{'label': s, 'value': s} for s in held_symbols]),
        dbc.Button("Create category", id='create-category-btn', color='primary', n_clicks=0),
    ], className="create-row")
    return html.Div([
        panel("Holdings", dbc.Accordion(items, start_collapsed=True, active_item="All holdings",
                                        className="category-accordion"),
              subtitle="Group holdings into your own categories", flush=True, panel_id="holdings"),
        panel("New category", create_form, panel_id="new-category"),
    ])


# ── Activity ──────────────────────────────────────────────────────────────────

def activity_view(trading: dict, trades_chart, deposits_chart, realized_chart, years: list):
    busiest = trading['busiest_month']
    return html.Div([
        kpi_strip([
            kpi("Trades per month", f"{trading['median_per_month']:.0f}",
                sub=f"median · {trading['trade_count']} trades in {trading['months']} months"),
            kpi("Busiest month", busiest.strftime('%b %Y') if busiest else "—",
                sub=f"{trading['busiest_count']} trades" if busiest else None),
            kpi("Sales at a profit", pct(trading['win_rate'], signed=False, digits=0),
                sub=f"of {trading['sale_count']} closed sales"),
            kpi("Median holding period", f"{trading['median_holding_days']:.0f} days",
                sub="purchase to sale, first-in first-out"),
            kpi("Realized P&L", money(trading['realized_total'], signed=True),
                value_class=sign_class(trading['realized_total']), sub="all closed sales"),
        ]),
        html.Div([
            panel("Trades per month", trades_chart, panel_id="trades-per-month"),
            panel("New money per month", deposits_chart, panel_id="new-money"),
        ], className="grid grid-2"),
        panel("Biggest realized gains and losses", realized_chart, panel_id="realized-by-stock"),
        closed_trades_section(years),
    ])


def closed_trades_section(years: list):
    """Year filter + search; the closed-trades callback fills the container."""
    year_select = dcc.Dropdown(
        id='trades-year', value='all', clearable=False, searchable=False, className="select-xs",
        options=[{'label': 'All years', 'value': 'all'}] +
                [{'label': str(y), 'value': y} for y in sorted(years, reverse=True)])
    return panel("Closed trades", html.Div(id='closed-trades-container'),
                 actions=[year_select, _search('trades-search')], flush=True, panel_id="closed-trades")


# ── Taxes ─────────────────────────────────────────────────────────────────────

def has_retirement(breakdown) -> bool:
    return abs(breakdown['retirement'].sum()) >= 0.005


def taxes_view(summary, tax_chart, breakdown):
    """Term totals, the tax-year chart and table, and profit by stock."""
    return html.Div([
        _term_strip(breakdown),
        tax_year_section(summary, tax_chart),
        profit_by_stock_section(breakdown),
    ])


def _term_strip(breakdown):
    if breakdown.empty:
        return None
    t = breakdown[['realized_st', 'realized_lt', 'unrealized_st', 'unrealized_lt', 'retirement']].sum()
    cells = [
        kpi("Realized · short-term", money(t['realized_st'], signed=True),
            value_class=sign_class(t['realized_st']), sub="sold within a year of buying",
            info=_TERM_INFO, kpi_id="made-st"),
        kpi("Realized · long-term", money(t['realized_lt'], signed=True),
            value_class=sign_class(t['realized_lt']), sub="sold after more than a year", kpi_id="made-lt"),
        kpi("Unrealized · short-term", money(t['unrealized_st'], signed=True),
            value_class=sign_class(t['unrealized_st']), sub="held a year or less", kpi_id="hold-st"),
        kpi("Unrealized · long-term", money(t['unrealized_lt'], signed=True),
            value_class=sign_class(t['unrealized_lt']), sub="held more than a year", kpi_id="hold-lt"),
    ]
    if has_retirement(breakdown):
        cells.append(kpi("Retirement accounts", money(t['retirement'], signed=True),
                         value_class=sign_class(t['retirement']),
                         sub="not taxed by holding period", kpi_id="retirement-pl"))
    return kpi_strip(cells)


def tax_year_section(summary, chart):
    if summary.empty:
        return panel("By tax year", empty_state("No taxable accounts in this view."), panel_id="tax-year")
    current = pd.Timestamp.now().year
    columns = [("Year", False), ("Short-term gains", True), ("Long-term gains", True),
               ("Dividends", True), ("Gains + dividends", True), ("Foreign tax withheld", True)]
    rows = [html.Tr([
        td(f"{year} (to date)" if year == current else str(year), cls="sym"),
        pl_td(r['realized_st']), pl_td(r['realized_lt']), pl_td(r['dividends']),
        pl_td(r['total'], strong=True),
        td(money(r['foreign_tax'], cents=True), numeric=True, cls="text-2"),
    ]) for year, r in summary.iterrows()]
    return panel("By tax year", html.Div([chart, html.Div(data_table(columns, rows, auto_height=True),
                                                          style={'marginTop': '12px'})]),
                 info=_TAX_INFO, panel_id="tax-year")


def profit_by_stock_section(breakdown):
    """Search box in the header; the profit-search callback fills the table."""
    if breakdown.empty:
        return None
    return panel("Profit by stock", html.Div(id='profit-table-container'),
                 actions=_search('profit-search'), info=_TERM_INFO,
                 subtitle="Realized and unrealized, by holding period", flush=True,
                 panel_id="profit-by-stock")


def profit_table(breakdown, sales: dict, prices, show_retirement: bool):
    """Per-stock rows (already filtered by search) with the last sale price and
    today's price so you can compare. `sales` is insights.last_sales."""
    if breakdown.empty:
        return empty_state("No stocks match.")
    columns = [("Symbol", False), ("Realized ST", True), ("Realized LT", True),
               ("Unrealized ST", True), ("Unrealized LT", True)]
    if show_retirement:
        columns.append(("Retirement", True))
    columns += [("Total", True), ("Last sold", True), ("Price now", True),
                ("Shares", True), ("Turns long-term", True)]

    def pl_cells(r):
        cells = [pl_td(r['realized_st']), pl_td(r['realized_lt']),
                 pl_td(r['unrealized_st']), pl_td(r['unrealized_lt'])]
        if show_retirement:
            cells.append(pl_td(r['retirement']))
        return cells + [pl_td(r['total'], strong=True)]

    rows = []
    for symbol, r in breakdown.iterrows():
        sale = sales.get(symbol)
        now = prices.get(symbol) if symbol in prices else None
        now = None if now is None or pd.isna(now) else float(now)
        change = (now / sale['price'] - 1) if (sale and now is not None and sale['price']) else None
        next_lt = None
        if pd.notna(r['next_lt_date']):
            next_lt = two_line(date(r['next_lt_date']), f"{shares(r['next_lt_shares'])} shares")
        rows.append(html.Tr([td(symbol, cls="sym")] + pl_cells(r) + [
            td(two_line(money(sale['price'], cents=True), date(sale['date'])) if sale else "—",
               numeric=True, cls="two-line" if sale else "muted"),
            td(two_line(money(now, cents=True), f"{pct(change)} vs. last sale" if change is not None else None)
               if now is not None else "—", numeric=True, cls="two-line"),
            td(shares(r['shares']) if r['shares'] else "—", numeric=True, cls="" if r['shares'] else "muted"),
            td(next_lt or "—", numeric=True, cls="two-line" if next_lt else "muted"),
        ]))
    totals = breakdown[['realized_st', 'realized_lt', 'unrealized_st', 'unrealized_lt',
                        'retirement', 'total']].sum()
    footer = html.Tr([td("Total")] + pl_cells(totals) + [td("")] * 4)
    return data_table(columns, rows, footer=footer, table_id="profit-table")
