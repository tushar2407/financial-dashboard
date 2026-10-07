import re

from dash import html
import dash_bootstrap_components as dbc

def create_info_icon(target_id, info):
    """Small circled 'i' that shows `info` (text or components) on hover."""
    return html.Span([
        html.Span("i", id=target_id, className="info-icon", tabIndex=0),
        dbc.Tooltip(info, target=target_id, placement="bottom", className="info-tooltip"),
    ])


def create_card(title, value, subtitle=None, color="primary", annotation=None, info=None):
    # Map custom colors to Bootstrap colors if needed, or use style argument
    # Bootstrap colors: primary, secondary, success, danger, warning, info, light, dark
    
    # Adjust subtitle color based on context
    subtitle_color = "text-success" if "success" in color else "text-danger" if "danger" in color else "text-muted"
    if subtitle and ("+" in subtitle or "All Time" in subtitle):
        subtitle_color = "text-success" if "+" in subtitle or float(subtitle.split('%')[0].replace(',','')) >= 0 else "text-danger"
    
    card_id = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') + "-card"
    return dbc.Card(
        dbc.CardBody([
            html.H6([
                title,
                create_info_icon(f"{card_id}-info", info) if info else None,
            ], className="card-subtitle mb-2 text-muted text-uppercase small font-weight-bold"),
            html.Div([
                html.H2(value, className="card-title text-white mb-1", style={'display': 'inline-block'}),
                html.Span(f" {annotation}", className="text-muted small", style={'marginLeft': '8px', 'fontSize': '14px'}) if annotation else None
            ]),
            html.P(subtitle, className=f"card-text {subtitle_color} small mb-0") if subtitle else None
        ], className="p-3"),
        className="glass-card h-100",
        id=card_id
    )

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
        return html.Div("No closed trades match.", className="text-muted")

    rows_data = sorted(history_data, key=lambda r: r['Date'], reverse=True)
    taxable = [r for r in rows_data if r.get('Account Type') != 'retirement']
    total = sum(r['Realized P/L'] for r in rows_data)
    st = sum(r.get('Short-Term P/L', 0.0) for r in taxable)
    lt = sum(r.get('Long-Term P/L', 0.0) for r in taxable)

    def money(v):
        return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"

    header = html.Thead(html.Tr([html.Th(c, style={'textAlign': a}) for c, a in (
        ("Date", 'left'), ("Symbol", 'left'), ("Term", 'left'), ("Qty", 'right'),
        ("Price", 'right'), ("Cost", 'right'), ("Proceeds", 'right'), ("Realized P/L", 'right'))]))
    rows = []
    for r in rows_data:
        pl = r['Realized P/L']
        rows.append(html.Tr([
            html.Td(f"{r['Date']:%Y-%m-%d}", style={'textAlign': 'left'}),
            html.Td(r['Symbol'], style={'textAlign': 'left', 'fontWeight': '600'}),
            html.Td(_term_label(r), style={'textAlign': 'left', 'color': '#c3c2b7'}),
            html.Td(f"{r['Qty']:,.2f}", style={'textAlign': 'right'}),
            html.Td(f"${r['Sell Price']:,.2f}", style={'textAlign': 'right'}),
            html.Td(f"${r['Cost Basis']:,.2f}", style={'textAlign': 'right'}),
            html.Td(f"${r['Proceeds']:,.2f}", style={'textAlign': 'right'}),
            html.Td(money(pl), style={'textAlign': 'right', 'fontWeight': '600',
                                      'color': "var(--apple-green)" if pl >= 0 else "var(--apple-red)"}),
        ]))

    return html.Div([
        html.Div([
            html.Span(f"Realized P/L: {money(total)}",
                      className=f"me-3 {'text-success' if total >= 0 else 'text-danger'}",
                      style={'fontWeight': '700', 'fontSize': '1.15rem'}),
            html.Span(f"short-term {money(st)} · long-term {money(lt)} · {len(rows_data)} sales",
                      className="text-muted small"),
        ], className="mb-3"),
        html.Div(dbc.Table([header, html.Tbody(rows)], id="history-table",
                           className="glass-table mb-0", hover=True, borderless=True),
                 className="sticky-table-box"),
    ])


def create_category_accordion_item(
    name: str,
    holdings_in_category: list,
    total_portfolio_value: float,
    deletable: bool = True,
    cash: float = 0.0,
) -> 'dbc.AccordionItem':
    show_cash = abs(cash) >= 0.01
    total_pl = sum(h.get('Unrealized P/L', 0) for h in holdings_in_category)
    total_cost = sum(h.get('Total Cost', 0) for h in holdings_in_category)
    total_value = sum(h.get('Market Value', 0) for h in holdings_in_category) + cash
    total_pl_pct = (total_pl / total_cost) if total_cost else 0
    pl_color = "var(--apple-green)" if total_pl >= 0 else "var(--apple-red)"

    title = html.Div([
        html.Span(name, style={'fontWeight': '600', 'fontSize': '1rem', 'color': 'white'}),
        html.Div([
            html.Span(f"${total_value:,.2f}",
                      style={'color': 'rgba(255,255,255,0.6)', 'fontWeight': '500',
                             'fontSize': '0.9rem', 'marginRight': '16px'}),
            html.Span(f"${total_pl:+,.2f}",
                      style={'color': pl_color, 'fontWeight': '700'}),
            html.Span(f" ({total_pl_pct:+.2%})",
                      style={'color': pl_color, 'fontWeight': '500', 'fontSize': '0.88rem',
                             'marginRight': '2rem'}),
        ], className="d-flex align-items-center"),
    ], className="d-flex justify-content-between align-items-center w-100")

    if holdings_in_category or show_cash:
        header_row = html.Thead(html.Tr([
            html.Th("Symbol", style={'textAlign': 'left'}),
            html.Th("Qty", style={'textAlign': 'right'}),
            html.Th("Avg Cost", style={'textAlign': 'right'}),
            html.Th("Price", style={'textAlign': 'right'}),
            html.Th("Value", style={'textAlign': 'right'}),
            html.Th("Portfolio %", style={'textAlign': 'right'}),
            html.Th("P/L", style={'textAlign': 'right'}),
            html.Th("P/L %", style={'textAlign': 'right'}),
        ]))
        rows = []
        for h in holdings_in_category:
            h_pl = h.get('Unrealized P/L', 0)
            h_pct = h.get('P/L %', 0)
            h_val = h.get('Market Value', 0)
            port_pct = (h_val / total_portfolio_value) if total_portfolio_value else 0
            c = "var(--apple-green)" if h_pl >= 0 else "var(--apple-red)"
            rows.append(html.Tr([
                html.Td(h['Symbol'], style={'textAlign': 'left', 'fontWeight': '600'}),
                html.Td(f"{h['Quantity']:,.2f}", style={'textAlign': 'right'}),
                html.Td(f"${h.get('Avg Cost', 0):,.2f}", style={'textAlign': 'right'}),
                html.Td(f"${h.get('Current Price', 0):,.2f}", style={'textAlign': 'right'}),
                html.Td(f"${h_val:,.2f}", style={'textAlign': 'right'}),
                html.Td(f"{port_pct:.1%}",
                        style={'textAlign': 'right', 'color': 'rgba(255,255,255,0.7)'}),
                html.Td(f"${h_pl:+,.2f}",
                        style={'textAlign': 'right', 'color': c, 'fontWeight': '600'}),
                html.Td(f"{h_pct:+.2%}",
                        style={'textAlign': 'right', 'color': c, 'fontWeight': '600'}),
            ]))
        if show_cash:
            cash_pct = (cash / total_portfolio_value) if total_portfolio_value else 0
            muted = {'textAlign': 'right', 'color': 'rgba(255,255,255,0.4)'}
            rows.append(html.Tr([
                html.Td("Cash", style={'textAlign': 'left', 'fontWeight': '600'}),
                html.Td("—", style=muted),
                html.Td("—", style=muted),
                html.Td("—", style=muted),
                html.Td(f"${cash:,.2f}", style={'textAlign': 'right'}),
                html.Td(f"{cash_pct:.1%}",
                        style={'textAlign': 'right', 'color': 'rgba(255,255,255,0.7)'}),
                html.Td("—", style=muted),
                html.Td("—", style=muted),
            ]))
        body_content = html.Div([
            dbc.Table(
                [header_row, html.Tbody(rows)],
                className="glass-table mb-0",
                responsive=True, hover=True, borderless=True, size="sm",
            )
        ], className="table-responsive")
    else:
        body_content = html.P(
            "None of these stocks are held in the selected account.",
            className="text-muted small mb-0"
        )

    footer = html.Div(
        dbc.Button("Delete category", id={'type': 'delete-category-btn', 'index': name},
                   size="sm", color="danger", outline=True, n_clicks=0, className="mt-3"),
        className="text-end"
    ) if deletable else None

    return dbc.AccordionItem(
        children=html.Div([body_content, footer] if footer else [body_content]),
        title=title,
        item_id=name,
    )
