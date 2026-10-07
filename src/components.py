"""Shared UI building blocks: panels, KPI cells, data tables.

Styling lives in assets/style.css; nothing here sets inline colors. Numbers go
through formatting.py so every amount reads the same way.
"""
from dash import html
import dash_bootstrap_components as dbc

from formatting import date, money, pct, shares, sign_class


# ── primitives ────────────────────────────────────────────────────────────────

def info_icon(target_id: str, info):
    """Small circled 'i' that shows `info` (text or components) on hover."""
    return html.Span([
        html.Span("i", id=target_id, className="info-icon", tabIndex=0),
        dbc.Tooltip(info, target=target_id, placement="bottom", className="info-tooltip"),
    ])


def panel(title, body, actions=None, info=None, subtitle=None, panel_id=None, flush=False):
    """Bordered panel; the header row holds the title and the panel's controls."""
    slug = panel_id or str(title).lower().replace(' ', '-')
    head = html.Div([
        html.Div([title,
                  info_icon(f"{slug}-info", info) if info else None,
                  html.Span(subtitle, className="panel-sub") if subtitle else None],
                 className="panel-title"),
        html.Div(actions, className="panel-actions") if actions is not None else None,
    ], className="panel-head")
    ids = {'id': panel_id} if panel_id else {}
    return html.Div([head, html.Div(body, className="panel-body flush" if flush else "panel-body")],
                    className="panel", **ids)


def empty_state(text: str):
    return html.Div(text, className="empty-state")


# ── KPIs ──────────────────────────────────────────────────────────────────────

def kpi(label: str, value: str, sub=None, value_class: str = "", sub_class: str = "",
        info=None, kpi_id: str = None, rows=None):
    """One KPI cell. `rows` is an optional breakdown: [(label, text, css class)]."""
    kpi_id = kpi_id or label.lower().replace(' ', '-').replace('·', '').replace('%', 'pct')
    return html.Div([
        html.Div([label, info_icon(f"{kpi_id}-info", info) if info else None], className="kpi-label"),
        html.Div(value, className=f"kpi-value {value_class}".strip()),
        html.Div(sub, className=f"kpi-sub {sub_class}".strip()) if sub else None,
        html.Div([html.Div([html.Span(lbl), html.Span(txt, className=cls)], className="kpi-row")
                  for lbl, txt, cls in rows], className="kpi-rows") if rows else None,
    ], className="kpi", id=kpi_id)


def kpi_strip(cells: list):
    """KPIs joined into one bordered strip with dividers."""
    return html.Div(cells, className="kpi-strip")


# ── tables ────────────────────────────────────────────────────────────────────

def th(label: str, numeric: bool = False):
    return html.Th(label, className="num" if numeric else None)


def td(content, numeric: bool = False, cls: str = ""):
    classes = " ".join(c for c in ("num" if numeric else "", cls) if c)
    return html.Td(content, className=classes or None)


def pl_td(v: float, cents: bool = False, strong: bool = False):
    """P/L cell: signed, colored by sign, em dash for zero."""
    return td(money(v, signed=True, cents=cents), numeric=True,
              cls=f"{sign_class(v)}{' strong' if strong else ''}")


def two_line(main, sub):
    return [main, html.Span(sub, className="sub")] if sub else main


def data_table(columns: list, rows: list, footer=None, table_id=None, auto_height=False):
    """`columns` is [(label, numeric?)]; rows are html.Tr. Sortable via table_sort.js."""
    table = dbc.Table([
        html.Thead(html.Tr([th(label, numeric) for label, numeric in columns])),
        html.Tbody(rows),
        html.Tfoot(footer) if footer is not None else None,
    ], className="data-table", hover=True, borderless=True, **({'id': table_id} if table_id else {}))
    return html.Div(table, className="table-box auto-height" if auto_height else "table-box")


# ── closed trades ─────────────────────────────────────────────────────────────

def _term_label(sale) -> str:
    """Short / Long / Mixed by the lots a sale used; retirement sales have no term."""
    if sale.get('Account Type') == 'retirement':
        return "Retirement"
    st, lt = abs(sale.get('Short-Term P/L', 0.0)), abs(sale.get('Long-Term P/L', 0.0))
    if lt < 0.005:
        return "Short"
    return "Long" if st < 0.005 else "Mixed"


def create_history_table(history_data):
    """Closed trades, newest first, with each sale's tax term and a total line."""
    if not history_data:
        return empty_state("No closed trades match.")

    rows_data = sorted(history_data, key=lambda r: r['Date'], reverse=True)
    taxable = [r for r in rows_data if r.get('Account Type') != 'retirement']
    total = sum(r['Realized P/L'] for r in rows_data)
    st = sum(r.get('Short-Term P/L', 0.0) for r in taxable)
    lt = sum(r.get('Long-Term P/L', 0.0) for r in taxable)

    columns = [("Date", False), ("Symbol", False), ("Term", False), ("Qty", True),
               ("Price", True), ("Cost", True), ("Proceeds", True), ("Realized P/L", True)]
    rows = [html.Tr([
        td(date(r['Date'])),
        td(r['Symbol'], cls="sym"),
        td(_term_label(r), cls="muted"),
        td(shares(r['Qty']), numeric=True),
        td(money(r['Sell Price'], cents=True), numeric=True),
        td(money(r['Cost Basis'], cents=True), numeric=True),
        td(money(r['Proceeds'], cents=True), numeric=True),
        pl_td(r['Realized P/L'], cents=True),
    ]) for r in rows_data]

    summary = html.Div([
        html.Span(["Realized ", html.Span(money(total, signed=True, cents=True),
                                          className=f"lead-num {sign_class(total)}")]),
        html.Span(f"Short-term {money(st, signed=True, cents=True)}"),
        html.Span(f"Long-term {money(lt, signed=True, cents=True)}"),
        html.Span(f"{len(rows_data)} sales"),
    ], className="table-summary")
    return html.Div([summary, data_table(columns, rows, table_id="history-table")])


# ── holdings by category ──────────────────────────────────────────────────────

def create_category_accordion_item(name: str, holdings_in_category: list, total_portfolio_value: float,
                                   deletable: bool = True, cash: float = 0.0) -> dbc.AccordionItem:
    show_cash = abs(cash) >= 0.01
    total_pl = sum(h.get('Unrealized P/L', 0) for h in holdings_in_category)
    total_cost = sum(h.get('Total Cost', 0) for h in holdings_in_category)
    total_value = sum(h.get('Market Value', 0) for h in holdings_in_category) + cash
    total_pl_pct = (total_pl / total_cost) if total_cost else 0

    title = html.Div([
        html.Span(name, className="name"),
        html.Span([
            html.Span(money(total_value, cents=True), className="text-2"),
            html.Span(money(total_pl, signed=True, cents=True), className=sign_class(total_pl)),
            html.Span(pct(total_pl_pct, digits=2), className=sign_class(total_pl)),
        ], className="figures"),
    ], className="accordion-title")

    if holdings_in_category or show_cash:
        columns = [("Symbol", False), ("Qty", True), ("Avg cost", True), ("Price", True),
                   ("Value", True), ("Weight", True), ("P/L", True), ("P/L %", True)]
        rows = []
        for h in sorted(holdings_in_category, key=lambda h: -h.get('Market Value', 0)):
            value = h.get('Market Value', 0)
            pl = h.get('Unrealized P/L', 0)
            rows.append(html.Tr([
                td(h['Symbol'], cls="sym"),
                td(shares(h['Quantity']), numeric=True),
                td(money(h.get('Avg Cost', 0), cents=True), numeric=True),
                td(money(h.get('Current Price', 0), cents=True), numeric=True),
                td(money(value, cents=True), numeric=True),
                td(pct(value / total_portfolio_value if total_portfolio_value else 0, signed=False),
                   numeric=True, cls="text-2"),
                pl_td(pl, cents=True),
                td(pct(h.get('P/L %', 0), digits=2) if sign_class(pl) != 'zero' else "—",
                   numeric=True, cls=sign_class(pl)),
            ]))
        if show_cash:
            rows.append(html.Tr([
                td("Cash", cls="sym"), td("—", True, "muted"), td("—", True, "muted"), td("—", True, "muted"),
                td(money(cash, cents=True), numeric=True),
                td(pct(cash / total_portfolio_value if total_portfolio_value else 0, signed=False),
                   numeric=True, cls="text-2"),
                td("—", True, "muted"), td("—", True, "muted"),
            ]))
        body = data_table(columns, rows, auto_height=True)
    else:
        body = empty_state("None of these stocks are held in this view.")

    footer = html.Div(
        dbc.Button("Delete category", id={'type': 'delete-category-btn', 'index': name},
                   size="sm", color="danger", outline=True, n_clicks=0),
        className="accordion-footer",
    ) if deletable else None

    return dbc.AccordionItem(children=html.Div([body, footer]), title=title, item_id=name)
