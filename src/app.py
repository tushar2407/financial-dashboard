import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output
import pandas as pd
from data_loader import load_and_clean_data, categorize_transactions, get_portfolio_history, fetch_price_data, calculate_portfolio_value, fetch_sector_data
from metrics import calculate_xirr, calculate_cagr, calculate_net_invested, calculate_cost_basis, calculate_net_invested_breakdown, get_daily_cash_flows, calculate_performance_metrics, calculate_yearly_returns
from components import create_card, create_portfolio_graph, create_stock_performance_chart, create_holdings_table, create_history_table, create_industry_allocation_chart, create_yearly_returns_chart

# Load Data Globally (to avoid reloading on every callback)
print("Loading data...")
global_df = load_and_clean_data()
global_df = categorize_transactions(global_df)

# Fetch prices for all symbols once
all_symbols = global_df['Symbol'].dropna().unique()
all_symbols = [s for s in all_symbols if isinstance(s, str) and s.strip() != '']
start_date = global_df['Run Date'].min().strftime('%Y-%m-%d')
global_prices = fetch_price_data(all_symbols, start_date, tx_df=global_df)
global_sectors = fetch_sector_data(all_symbols)

app = dash.Dash(__name__, 
                external_stylesheets=[dbc.themes.DARKLY],
                assets_folder='../assets',
                suppress_callback_exceptions=True)
server = app.server
app.title = "Financial Dashboard"

app.layout = html.Div([
    dbc.Container([
        # Centered Apple-style Header
        html.Div([
            html.H1("Financial Dashboard", className="text-center mb-2 text-white display-4", 
                    style={'fontWeight': '700', 'letterSpacing': '-0.04em'}),
            html.P("Portfolio Analytics & Performance", 
                   className="text-center text-muted mb-0 lead", 
                   style={'fontWeight': '400', 'letterSpacing': '-0.02em'}),
        ], className="dashboard-header mb-5"),
        
        dbc.Row([
            dbc.Col([
                dbc.Tabs(id='account-tabs', active_tab='individual', children=[
                    dbc.Tab(label='Individual + ESPP', tab_id='individual'),
                    dbc.Tab(label='401k', tab_id='401k'),
                    dbc.Tab(label='Combined', tab_id='combined'),
                ], className='justify-content-center mb-5'),
            ], width=12)
        ]),
        
        html.Div(id='dashboard-content'),
        
        # Allocation Section
        dbc.Row([
            dbc.Col([
                html.Div([
                    dbc.Tabs(id='allocation-tabs', active_tab='stock', children=[
                        dbc.Tab(label='Stock Allocation', tab_id='stock'),
                        dbc.Tab(label='Industry Allocation', tab_id='industry')
                    ], className='mb-4 d-inline-flex')
                ], className="text-center mt-5 mb-3")
            ], width=12)
        ]),
        
        dbc.Row([
            dbc.Col([
                html.Div(id='allocation-chart-container', className="glass-card mb-5 p-4")
            ], width=12)
        ])
    ], fluid=False, className="pb-5")
], style={'overflowX': 'hidden'})

@app.callback(
    Output('dashboard-content', 'children'),
    [Input('account-tabs', 'active_tab')]
)
def update_dashboard(tab):
    # Filter Data
    if tab == 'individual':
        df = global_df[global_df['Account'] == 'Individual'].copy()
    elif tab == '401k':
        df = global_df[global_df['Account'] == 'MICROSOFT 401K PLAN'].copy()
    else: # combined
        df = global_df.copy()
        
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
    
    # Enrich Holdings with Current Price
    if not prices.empty:
        latest_prices = prices.iloc[-1]
        for item in current_holdings_data:
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

    # Calculate realized and unrealized P/L
    total_realized_pl = sum(pnl['Realized P/L'] for pnl in realized_pnl_data)
    total_unrealized_pl = sum(item.get('Unrealized P/L', 0) for item in current_holdings_data)

    # Annual Performance
    yearly_data = calculate_yearly_returns(portfolio_value, daily_flows)
    
    # Extract Previous Year (2025) for Summary Cards
    prev_year_metrics = next((y for y in yearly_data if y['Year'] == 2025), {'XIRR': 0, 'TWR': 0})
    py_xirr = prev_year_metrics['XIRR'] * 100
    py_twr = prev_year_metrics['TWR'] * 100

    # Dates for tooltips
    data_start = df['Run Date'].min().strftime('%b %d, %Y')
    data_end = df['Run Date'].max().strftime('%b %d, %Y')
    y1_start = (df['Run Date'].max() - pd.Timedelta(days=365)).strftime('%b %d, %Y')

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
                            # Transfers
                            html.Div([
                                html.Span("Transfers", className="text-muted small"),
                                html.Span(f"${net_invested_breakdown['transfers']:,.2f}", className="float-end text-white small")
                            ], className="d-flex justify-content-between mb-1"),
                            # ESPP
                            html.Div([
                                html.Span("ESPP", className="text-muted small"),
                                html.Span(f"${net_invested_breakdown['espp']:,.2f}", className="float-end text-white small")
                            ], className="d-flex justify-content-between mb-1"),
                            # Contributions – only for 401k tab
                            *(
                                [
                                    html.Div([
                                        html.Span("Contributions", className="text-muted small"),
                                        html.Span(f"${net_invested_breakdown['contributions']:,.2f}", className="float-end text-white small")
                                    ], className="d-flex justify-content-between mb-1")
                                ] if tab == '401k' else []
                            ),
                            # Withdrawals
                            html.Div([
                                html.Span("Withdrawals", className="text-muted small"),
                                html.Span(f"${net_invested_breakdown['withdrawals']:,.2f}", className="float-end text-white small")
                            ], className="d-flex justify-content-between")
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
                            ], className="d-flex justify-content-between")
                        ])
                    ], className="p-3")
                ], className="glass-card h-100")
            ], width=12, md=6, lg=3, className="mb-4"),
            dbc.Col(
                create_card("Personal Return (XIRR)", f"{cagr:.2f}%", f"{yoy_xirr:+.2f}% 1Y", "info", annotation="till date"),
                width=12, md=6, lg=3, className="mb-4"
            ),
            dbc.Col(
                create_card("Portfolio Return (TWR)", f"{lifetime_twr:.2f}%", f"{yoy_twr:+.2f}% 1Y", "success", annotation="till date"),
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
        
        # Allocation Tab (Stock vs Industry) - MOVED TO STATIC LAYOUT
        # We removed it from here to avoid callback ID errors
        
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H4("Current Holdings", className="text-white mb-4"),
                    create_holdings_table(current_holdings_data)
                ], className="glass-card p-4")
            ], width=12, className="mb-5")
        ]),

        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H4("Transaction History (Realized P/L)", className="text-white mb-4"),
                    create_history_table(realized_pnl_data)
                ], className="glass-card p-4")
            ], width=12, className="mb-5")
        ])
    ])

# Helper to get holdings (moved from update_dashboard)
def get_current_holdings(df):
    holdings_dict = {}
    for _, row in df.iterrows():
        if row['Category'] == 'BUY':
            sym = row['Symbol']
            qty = row['Quantity']
            holdings_dict[sym] = holdings_dict.get(sym, 0) + qty
        elif row['Category'] == 'SELL':
            sym = row['Symbol']
            qty = abs(row['Quantity'])
            holdings_dict[sym] = max(0, holdings_dict.get(sym, 0) - qty)
        elif row['Category'] == 'Split':
            sym = row['Symbol']
            ratio = row['Quantity']
            if sym in holdings_dict:
                holdings_dict[sym] = holdings_dict[sym] * ratio
                
    holdings_df = pd.DataFrame([holdings_dict])
    return holdings_df

@app.callback(
    Output('allocation-chart-container', 'children'),
    [Input('allocation-tabs', 'active_tab'), Input('account-tabs', 'active_tab')]
)
def update_allocation_chart(allocation_tab, account_tab):
    # Filter Data (Same logic as main callback)
    if account_tab == 'individual':
        df = global_df[global_df['Account'] == 'Individual'].copy()
    elif account_tab == '401k':
        df = global_df[global_df['Account'] == 'MICROSOFT 401K PLAN'].copy()
    elif account_tab == 'combined':
        df = global_df.copy()
    else:
        df = global_df[global_df['Account'] == 'Individual'].copy()

    # Get Holdings
    if df.empty:
        return html.Div("No data available", className="text-white")

    # Sort by date
    df = df.sort_values('Run Date')
    
    holdings = get_current_holdings(df)
    
    # Render
    title = "Stock Allocation" if (allocation_tab or 'stock') == 'stock' else "Industry Allocation"
    chart = create_stock_performance_chart(holdings, global_prices) if (allocation_tab or 'stock') == 'stock' else create_industry_allocation_chart(holdings, global_prices, global_sectors)
    
    return html.Div([
        chart
    ])

if __name__ == '__main__':
    app.run(debug=True, port=8050)
