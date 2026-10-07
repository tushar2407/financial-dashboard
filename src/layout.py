"""App shell: left sidebar navigation, top bar with the account filter, and the
routed content area. Each view has its own URL so a refresh keeps your place."""
from dash import dcc, html
import dash_bootstrap_components as dbc

from formatting import date

# path -> (title, icon)
PAGES = {
    '/overview': ("Overview", "◧"),
    '/allocation': ("Allocation", "▦"),
    '/activity': ("Activity", "⇅"),
    '/taxes': ("Taxes", "§"),
}
DEFAULT_PATH = '/overview'


def page_for(pathname: str) -> str:
    return pathname if pathname in PAGES else DEFAULT_PATH


def _nav_links(class_name: str):
    return dbc.Nav([
        dbc.NavLink([html.Span(icon, className="nav-icon"), html.Span(title, className="nav-text")],
                    href=path, active='exact')
        for path, (title, icon) in PAGES.items()
    ], vertical=class_name == "side-nav", className=class_name)


def _sidebar(last_fetch, stale_symbols: list, demo: bool):
    status = (html.Div([html.Span(className="status-dot warn"),
                        html.Span(f"{len(stale_symbols)} prices out of date", className="footer-text")])
              if stale_symbols else
              html.Div([html.Span(className="status-dot"), html.Span("Prices current", className="footer-text")]))
    return html.Aside([
        html.Div([html.Span("P", className="brand-mark"), html.Span("Portfolio", className="brand-name")],
                 className="brand"),
        _nav_links("side-nav"),
        html.Div([
            status,
            html.Div("Demo data (synthetic accounts)" if demo else
                     f"Data as of {date(last_fetch)}" if last_fetch else "No data fetched yet",
                     className="footer-text"),
            None if demo else html.Div("Restart the app to fetch new data", className="footer-text"),
        ], className="sidebar-footer"),
    ], className="sidebar")


def _stale_notice(stale_symbols: list):
    if not stale_symbols:
        return None
    return html.Div([
        html.Strong("Prices out of date."),
        html.Span(f"No recent market price for {', '.join(stale_symbols)}; valued at the last trade "
                  "price. Upgrade yfinance or start the app with venv/bin/python."),
    ], className="notice")


def app_layout(account_options: list, categories: dict, last_fetch, stale_symbols: list,
               demo: bool = False):
    account_select = dcc.Dropdown(
        id='account-select', options=account_options,
        value=account_options[0]['value'] if account_options else 'combined',
        clearable=False, searchable=False, className="select-sm",
    )
    return html.Div([
        dcc.Location(id='url'),
        dcc.Store(id='categories-store', data=categories),
        _sidebar(last_fetch, stale_symbols, demo),
        html.Main([
            html.Header([html.H1(id='page-title', className="page-title"), account_select],
                        className="topbar"),
            _nav_links("mobile-nav"),
            _stale_notice(stale_symbols),
            # Spinner only when the whole view is rebuilt (page/account change),
            # not when a callback updates something inside it (search, filters)
            dcc.Loading(html.Div(id='view-content', className="content"), type='circle',
                        color='#3987e5', target_components={'view-content': 'children'}),
        ], className="main"),
    ], className="app-shell")
