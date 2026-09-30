"""Page builders for the Overview, Allocation and Behavior views."""
from dash import dcc, html
import dash_bootstrap_components as dbc
import pandas as pd

from components import create_card, create_category_accordion_item, create_info_icon


# ── small building blocks ─────────────────────────────────────────────────────

def stat_tile(label: str, value: str, detail: str = None, info=None, tile_id: str = None):
    """A headline number with a one-line explanation."""
    tile_id = tile_id or label.lower().replace(' ', '-').replace('%', 'pct')
    return html.Div([
        html.Div([label, create_info_icon(f"{tile_id}-info", info) if info else None],
                 className="stat-label"),
        html.Div(value, className="stat-value"),
        html.Div(detail, className="stat-detail") if detail else None,
    ], className="glass-card stat-tile h-100")


def _stat_row(tiles: list):
    return dbc.Row([dbc.Col(t, width=12, sm=6, xl=True, className="mb-4") for t in tiles],
                   className="stat-row")


def _panel(child, **col):
    return dbc.Col(html.Div(child, className="glass-card p-3 h-100"), className="mb-4", **col)


def _breakdown_line(label: str, value: float, color_by_sign: bool = False, last: bool = False):
    cls = "text-white"
    if color_by_sign:
        cls = 'text-success' if value >= 0 else 'text-danger'
    return html.Div([
        html.Span(label, className="text-muted small"),
        html.Span(f"${value:,.2f}", className=f"float-end small {cls}"),
    ], className="d-flex justify-content-between" + ("" if last else " mb-1"))


# ── summary cards (shared by Overview) ────────────────────────────────────────

def summary_cards(s: dict):
    """Current value, net invested, P&L, XIRR and TWR cards.

    `s` holds: current_val, pl_pct, total_invested, breakdown, pl, realized,
    unrealized, dividends, xirr, xirr_1y, twr, twr_1y, xirr_info, twr_info.
    """
    b = s['breakdown']
    invested_lines = [
        ("Transfers", b['transfers'], False, b['transfers'] != 0),
        ("ESPP", b['espp'], False, b['espp'] != 0),
        ("Contributions", b['contributions'], False, b['contributions'] != 0),
        ("Internal Transfers", b['internal_transfers'], True, abs(b['internal_transfers']) > 0.01),
        ("Withdrawals", b['withdrawals'], False, b['withdrawals'] != 0),
    ]
    shown = [line for line in invested_lines if line[3]]
    invested_rows = [_breakdown_line(lbl, v, sign, last=(i == len(shown) - 1))
                     for i, (lbl, v, sign, _) in enumerate(shown)]

    pl = s['pl']
    col = dict(width=12, md=6, xl=True, className="mb-4")
    return dbc.Row([
        dbc.Col(create_card("Current Value", f"${s['current_val']:,.2f}",
                            f"{s['pl_pct']:+.2f}% All Time", "primary"), **col),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Net Invested", className="card-subtitle mb-2 text-muted text-uppercase"),
            html.H2(f"${s['total_invested']:,.2f}", className="card-title text-white"),
            html.Hr(className="my-2 border-secondary"),
            html.Div(invested_rows),
        ], className="p-3"), className="glass-card h-100"), **col),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("Total P&L", className="card-subtitle mb-2 text-muted text-uppercase"),
            html.H2(f"${pl:,.2f}", className=f"card-title {'text-success' if pl >= 0 else 'text-danger'}"),
            html.Hr(className="my-2 border-secondary"),
            html.Div([
                _breakdown_line("Realized", s['realized'], color_by_sign=True),
                _breakdown_line("Unrealized", s['unrealized'], color_by_sign=True),
                _breakdown_line("Dividends (net)", s['dividends'], color_by_sign=True, last=True),
            ]),
        ], className="p-3"), className="glass-card h-100"), **col),
        dbc.Col(create_card("Personal Return (XIRR)", f"{s['xirr']:.2f}%", f"{s['xirr_1y']:+.2f}% 1Y",
                            "info", annotation="till date", info=s['xirr_info']), **col),
        dbc.Col(create_card("Portfolio Return (TWR)", f"{s['twr']:.2f}%", f"{s['twr_1y']:+.2f}% 1Y",
                            "success", annotation="till date", info=s['twr_info']), **col),
    ], className="summary-row")


# ── views ─────────────────────────────────────────────────────────────────────

RANGE_OPTIONS = ['1D', '5D', '1M', '6M', '1Y', '5Y', 'ALL']
_RANGE_WORDS = {'1D': "the last day", '5D': "the last 5 days", '1M': "the last month",
                '6M': "the last 6 months", '1Y': "the last year", '5Y': "the last 5 years"}


def _period_words(window: dict) -> str:
    if window['range'] == 'ALL' or window['clipped']:
        return f"since {window['start']:%b %d, %Y}"
    fmt = '%b %d' if window['start'].year == window['end'].year else '%b %d, %Y'
    return (f"over {_RANGE_WORDS[window['range']]} "
            f"({window['start'].strftime(fmt)} to {window['end'].strftime(fmt)})")


def benchmark_tile(window: dict, name: str):
    period = _period_words(window)
    if window['diff'] is None:
        return stat_tile(f"vs. {name}", "n/a", f"No {name} prices available", tile_id="vs-benchmark")
    diff = window['diff']
    you = window['portfolio_return']
    lines = [f"{'ahead of' if diff >= 0 else 'behind'} the same money in {name} {period}"]
    if you is not None and window['benchmark_return'] is not None:
        lines.append(f"You {you:+.1%} · {name} {window['benchmark_return']:+.1%}")
    return stat_tile(
        f"vs. {name}",
        f"{'+' if diff >= 0 else '-'}${abs(diff):,.0f}",
        html.Span([lines[0], *([html.Br(), html.Strong(lines[1])] if len(lines) > 1 else [])]),
        info=[html.P(f"Your portfolio compared with putting the same money into {name}: "
                     "its value at the start of the period, plus every deposit or withdrawal "
                     "on the day it happened."),
              html.P(f"Returns ignore deposit timing: yours is time-weighted (TWR), {name}'s "
                     "is its price change.", className="mb-0")],
        tile_id="vs-benchmark",
    )


def overview_view(summary: dict, yearly_chart, default_range: str = 'ALL'):
    """Chart and benchmark tile are filled by the range callback."""
    range_picker = dbc.RadioItems(
        id='compare-range', value=default_range,
        options=[{'label': 'All' if r == 'ALL' else r, 'value': r} for r in RANGE_OPTIONS],
        className='btn-group range-picker', inputClassName='btn-check',
        labelClassName='btn btn-sm range-btn', labelCheckedClassName='active',
    )
    return html.Div([
        summary_cards(summary),
        dbc.Row([
            dbc.Col(html.Div([
                html.Div(range_picker, className="d-flex justify-content-end mb-1"),
                dcc.Loading(html.Div(id='compare-chart'), type='dot', color='#3987e5'),
            ], className="glass-card p-3 h-100"), width=12, lg=9, className="mb-4"),
            dbc.Col(html.Div(id='compare-tile', className="h-100"), width=12, lg=3, className="mb-4"),
        ]),
        dbc.Row([_panel(yearly_chart, width=12)]),
    ])


def allocation_view(alloc: dict, treemap, holdings):
    cash_pct, target = alloc['cash_pct'], alloc['cash_target']
    excess = alloc['cash_excess']
    cash_detail = (f"${excess:,.0f} above your {target:.0%} target" if excess > 0
                   else f"${-excess:,.0f} below your {target:.0%} target")
    small = alloc['small_positions']
    return html.Div([
        _stat_row([
            stat_tile("Cash", f"{cash_pct:.1%}", cash_detail,
                      info="Uninvested cash as a share of this view's total. "
                           "Set your target in data/goals.json (cash_target)."),
            stat_tile("Top 5 holdings", f"{alloc['top5_pct']:.1%}", "of total value in your 5 largest positions"),
            stat_tile("Positions", f"{alloc['position_count']}", "securities held"),
            stat_tile("Small positions", f"{len(small)}",
                      ("under 1% each: " + ", ".join(small)) if small else "none under 1%"),
        ]),
        dbc.Row([_panel(treemap, width=12)]),
        holdings,
    ])


_TERM_INFO = [
    html.P("Short-term: shares held one year or less when sold. Taxed like ordinary income."),
    html.P("Long-term: shares held more than one year. Taxed at the lower long-term rate."),
    html.P("Shares you still hold are classed by how long you've held them so far; "
           "\"Turns long-term\" is when your next short-term shares cross one year.", className="mb-0"),
]


def _money_cell(v: float, bold: bool = False):
    color = 'rgba(255,255,255,0.35)' if abs(v) < 0.005 else (
        'var(--apple-green)' if v > 0 else 'var(--apple-red)')
    text = f"{'+' if v > 0 else '-' if v < 0 else ''}${abs(v):,.0f}"
    return html.Td(text, style={'textAlign': 'right', 'color': color,
                                'fontWeight': '700' if bold else '500'})


def profit_by_stock_section(breakdown):
    """Per-stock profit already made (realized) vs. still held (unrealized),
    split into short- and long-term. `breakdown` is insights.stock_profit_breakdown."""
    if breakdown.empty:
        return html.Div()
    totals = breakdown[['realized_st', 'realized_lt', 'unrealized_st', 'unrealized_lt',
                        'retirement', 'total']].sum()
    has_retirement = abs(totals['retirement']) >= 0.005

    def signed(v):
        return f"{'+' if v >= 0 else '-'}${abs(v):,.0f}"

    tiles = [
        stat_tile("Made · short-term", signed(totals['realized_st']), "sold within a year of buying",
                  info=_TERM_INFO, tile_id="made-st"),
        stat_tile("Made · long-term", signed(totals['realized_lt']), "sold after more than a year",
                  tile_id="made-lt"),
        stat_tile("Holding · short-term", signed(totals['unrealized_st']), "on shares held a year or less",
                  tile_id="hold-st"),
        stat_tile("Holding · long-term", signed(totals['unrealized_lt']), "on shares held more than a year",
                  tile_id="hold-lt"),
    ]
    if has_retirement:
        tiles.append(stat_tile("Retirement accounts", signed(totals['retirement']),
                               "made + holding; not taxed by holding period", tile_id="retirement-pl"))

    columns = [("Stock", 'left'), ("Made · short-term", 'right'), ("Made · long-term", 'right'),
               ("Holding · short-term", 'right'), ("Holding · long-term", 'right')]
    if has_retirement:
        columns.append(("Retirement", 'right'))
    columns += [("Total", 'right'), ("Shares held", 'right'), ("Turns long-term", 'right')]
    header = html.Thead(html.Tr([html.Th(c, style={'textAlign': a}) for c, a in columns]))

    def cells(r, label, bold=False):
        out = [html.Td(label, style={'textAlign': 'left', 'fontWeight': '600'}),
               _money_cell(r['realized_st']), _money_cell(r['realized_lt']),
               _money_cell(r['unrealized_st']), _money_cell(r['unrealized_lt'])]
        if has_retirement:
            out.append(_money_cell(r['retirement']))
        out.append(_money_cell(r['total'], bold=True))
        return out

    body = []
    for symbol, r in breakdown.iterrows():
        next_lt = ""
        if pd.notna(r['next_lt_date']):
            qty = r['next_lt_shares']
            next_lt = [f"{r['next_lt_date']:%Y-%m-%d}", html.Br(),
                       html.Span(f"{qty:,.2f} shares" if qty >= 0.01 else "<0.01 shares",
                                 className="small text-muted")]
        body.append(html.Tr(cells(r, symbol) + [
            html.Td(f"{r['shares']:,.2f}" if r['shares'] else "", style={'textAlign': 'right'}),
            html.Td(next_lt, style={'textAlign': 'right', 'color': '#c3c2b7', 'whiteSpace': 'nowrap'}),
        ]))
    footer = html.Tfoot(html.Tr(cells(totals, "Total", bold=True) + [html.Td(""), html.Td("")],
                                className="totals-row"))

    return html.Div([
        html.H4(["Profit by stock", create_info_icon("profit-by-stock-info", _TERM_INFO)],
                className="text-white mb-1"),
        html.P("What you've already made by selling, and what's still on paper in shares you hold. "
               "Click a column to sort.", className="text-muted small mb-3"),
        _stat_row(tiles),
        # One scroll box (no Bootstrap responsive wrapper) so the header can stick
        html.Div(dbc.Table([header, html.Tbody(body), footer], className="glass-table mb-0",
                           hover=True, borderless=True, size="sm"),
                 className="sticky-table-box"),
    ], className="glass-card p-4 mb-4")


def behavior_view(trading: dict, trades_chart, deposits_chart, realized_chart, history_table,
                  profit_section=None):
    busiest = trading['busiest_month']
    return html.Div([
        _stat_row([
            stat_tile("Trades per month", f"{trading['median_per_month']:.0f}",
                      (f"median · {trading['trade_count']} trades over {trading['months']} months"
                       + (f" · busiest {busiest.strftime('%b %Y')} ({trading['busiest_count']})" if busiest else ""))),
            stat_tile("Sales at a profit", f"{trading['win_rate']:.0%}",
                      f"of {trading['sale_count']} closed sales"),
            stat_tile("Median holding period", f"{trading['median_holding_days']:.0f} days",
                      "from purchase to sale, first-in first-out"),
            stat_tile("Realized P/L", f"${trading['realized_total']:,.0f}", "from all closed sales"),
        ]),
        dbc.Row([
            _panel(trades_chart, width=12, lg=6),
            _panel(deposits_chart, width=12, lg=6),
        ]),
        dbc.Row([_panel(realized_chart, width=12)]),
        profit_section,
        html.Div([
            html.H4("Closed trades", className="text-white mb-4"),
            history_table,
        ], className="glass-card p-4 mb-4"),
    ])


def holdings_section(holdings: list, categories: dict, cash: float, total_value: float):
    """Portfolio accordion (pinned) + user categories + the create-category form."""
    held_symbols = sorted(h['Symbol'] for h in holdings)
    accordion_items = [
        create_category_accordion_item("Portfolio", holdings, total_value, deletable=False, cash=cash)
    ]
    for cat_name, cat_symbols in categories.items():
        cat_holdings = [h for h in holdings if h['Symbol'] in cat_symbols]
        accordion_items.append(create_category_accordion_item(cat_name, cat_holdings, total_value))

    input_style = {'backgroundColor': 'rgba(255,255,255,0.07)',
                   'border': '1px solid rgba(255,255,255,0.2)', 'color': 'white'}
    return html.Div([
        html.H4("Holdings", className="text-white mb-3"),
        dbc.Accordion(accordion_items, start_collapsed=True, className="category-accordion mb-4"),
        html.Div([
            html.H6("Create Category", className="text-white mb-3"),
            dbc.Row([
                dbc.Col(dbc.Input(id='category-name-input',
                                  placeholder='Category name (e.g. Memory, Quantum)...',
                                  style=input_style),
                        width=12, md=4, className="mb-2 mb-md-0"),
                dbc.Col(dcc.Dropdown(id='category-symbols-dropdown',
                                     options=[{'label': s, 'value': s} for s in held_symbols],
                                     multi=True, placeholder='Select stocks...',
                                     style={'backgroundColor': 'rgba(30,30,30,0.9)'}),
                        width=12, md=6, className="mb-2 mb-md-0"),
                dbc.Col(dbc.Button('Create', id='create-category-btn', color='primary',
                                   n_clicks=0, className="w-100"),
                        width=12, md=2),
            ], className="align-items-center"),
        ], className="glass-card p-4", style={"position": "relative", "zIndex": 10}),
    ], className="mb-5")
