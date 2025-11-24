from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import yfinance as yf
import pandas as pd

def create_card(title, value, subtitle=None, color="primary"):
    # Map custom colors to Bootstrap colors if needed, or use style argument
    # Bootstrap colors: primary, secondary, success, danger, warning, info, light, dark
    
    # Adjust subtitle color based on context
    subtitle_color = "text-success" if "success" in color else "text-danger" if "danger" in color else "text-muted"
    if subtitle and ("+" in subtitle or "All Time" in subtitle):
        subtitle_color = "text-success" if "+" in subtitle or float(subtitle.split('%')[0].replace(',','')) >= 0 else "text-danger"
    
    return dbc.Card(
        dbc.CardBody([
            html.H6(title, className="card-subtitle mb-2 text-muted text-uppercase"),
            html.H2(value, className="card-title text-white"),
            html.P(subtitle, className=f"card-text {subtitle_color}") if subtitle else None
        ]),
        className="h-100 shadow-sm bg-dark border-secondary",
        id=title.lower().replace(" ", "-") + "-card" # Add ID for tooltip targeting
    )

def create_portfolio_graph(portfolio_value, net_invested):
    fig = go.Figure()
    
    if portfolio_value.empty and net_invested.empty:
        fig.update_layout(
            template='plotly_dark',
            title='Portfolio Performance (No Data)',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#a0a0a0')
        )
        return dcc.Graph(figure=fig, className="graph-container")

    # Calculate P/L series for the secondary axis
    pl_series = None
    if not portfolio_value.empty and not net_invested.empty:
        # Align both series on the same dates
        all_dates = portfolio_value.index.union(net_invested.index).sort_values()
        pv_aligned = portfolio_value.reindex(all_dates, method='ffill')
        ni_aligned = net_invested.reindex(all_dates, method='ffill')
        pl_series = pv_aligned - ni_aligned
    
    # Portfolio Value Area Chart (Primary Y-axis)
    if not portfolio_value.empty:
        # Calculate P/L for hover display
        if not net_invested.empty:
            pl_values = []
            for date in portfolio_value.index:
                pv = portfolio_value.loc[date]
                if not net_invested.empty and date >= net_invested.index[0]:
                    ni_subset = net_invested.loc[net_invested.index <= date]
                    ni = ni_subset.iloc[-1] if not ni_subset.empty else 0
                else:
                    ni = 0
                pl = pv - ni
                pl_values.append(pl)
            
            hover_text = [
                f'<b>Date:</b> {date.strftime("%Y-%m-%d")}<br>' +
                f'<b>Portfolio Value:</b> ${pv:,.2f}<br>' +
                f'<b>P/L:</b> <span style="color:{"#00d084" if pl >= 0 else "#ff4444"}">${pl:+,.2f}</span>'
                for date, pv, pl in zip(portfolio_value.index, portfolio_value.values, pl_values)
            ]
        else:
            hover_text = [
                f'<b>Date:</b> {date.strftime("%Y-%m-%d")}<br>' +
                f'<b>Portfolio Value:</b> ${pv:,.2f}'
                for date, pv in zip(portfolio_value.index, portfolio_value.values)
            ]
        
        fig.add_trace(go.Scatter(
            x=portfolio_value.index, 
            y=portfolio_value.values, 
            name='Portfolio Value', 
            fill='tozeroy',
            line=dict(color='#00d084', width=2),
            hovertext=hover_text,
            hoverinfo='text',
            hoverlabel=dict(
                bgcolor='#1e1e1e',
                font=dict(color='white', size=14),
                bordercolor='#00d084'
            ),
            yaxis='y'
        ))
    
    # Net Invested Line (Primary Y-axis)
    if not net_invested.empty:
        fig.add_trace(go.Scatter(
            x=net_invested.index, 
            y=net_invested.values, 
            name='Net Invested', 
            line=dict(dash='dash', color='#ffffff', width=2),
            hovertemplate='<b>Net Invested:</b> $%{y:,.2f}<extra></extra>',
            hoverlabel=dict(
                bgcolor='#1e1e1e',
                font=dict(color='white', size=14),
                bordercolor='#ffffff'
            ),
            yaxis='y'
        ))
    
    # P/L Line (Secondary Y-axis)
    if pl_series is not None and not pl_series.empty:
        fig.add_trace(go.Scatter(
            x=pl_series.index,
            y=pl_series.values,
            name='P/L',
            line=dict(color='#ffa500', width=2, dash='dot'),
            hovertemplate='<b>P/L:</b> $%{y:+,.2f}<extra></extra>',
            hoverlabel=dict(
                bgcolor='#1e1e1e',
                font=dict(color='white', size=14),
                bordercolor='#ffa500'
            ),
            yaxis='y2'
        ))
    
    fig.update_layout(
        template='plotly_dark',
        title=dict(text='Portfolio Performance', font=dict(size=20, color='white')),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        hovermode='closest',
        margin=dict(l=20, r=60, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color='white')),
        xaxis=dict(
            title='Date', 
            showgrid=False, 
            color='white',
            title_font=dict(size=14)
        ),
        yaxis=dict(
            title='Value ($)', 
            showgrid=True, 
            gridcolor='rgba(255,255,255,0.1)', 
            color='white',
            title_font=dict(size=14)
        ),
        yaxis2=dict(
            title='P/L ($)',
            overlaying='y',
            side='right',
            showgrid=False,
            color='#ffa500',
            title_font=dict(size=14)
        )
    )
    return dcc.Graph(figure=fig, className="graph-container")

def create_stock_performance_chart(holdings, prices):
    # Get latest values
    if holdings.empty or prices.empty:
        return html.Div("No data available", className="text-white")
    
    # Latest holdings
    latest_holdings = holdings.iloc[-1]
    latest_prices = prices.iloc[-1]
    
    # Calculate market values and group slices <2% into 'Other'
    raw_symbols = []
    raw_values = []
    for col in holdings.columns:
        if col in latest_prices and latest_holdings[col] > 0.01:
            market_value = latest_holdings[col] * latest_prices[col]
            if market_value > 1:  # Filter very small positions
                raw_symbols.append(col)
                raw_values.append(market_value)

    if not raw_symbols:
        return html.Div("No data available", className="text-white")

    total = sum(raw_values)
    # Separate those >=2% and those <2%
    symbols = []
    values = []
    other_total = 0.0
    for sym, val in zip(raw_symbols, raw_values):
        if val / total >= 0.02:
            symbols.append(sym)
            values.append(val)
        else:
            other_total += val
    # Append 'Other' if needed
    if other_total > 0:
        symbols.append('Other')
        values.append(other_total)    
    fig = go.Figure(data=[go.Pie(
        labels=symbols, 
        values=values,
        textposition='outside',
        textinfo='label+percent',
        hovertemplate='<b>%{label}</b><br>$%{value:,.2f}<br>%{percent}<extra></extra>',
        textfont=dict(size=14, color='white'),
        marker=dict(line=dict(color='rgba(0,0,0,0)', width=0)),  # No outline
        hoverlabel=dict(
            bgcolor='#1e1e1e',
            font=dict(color='white', size=16),
            bordercolor='white'
        )
    )])
    
    fig.update_layout(
        template='plotly_dark',
        title=dict(text='Stock Allocation', font=dict(size=22, color='white')),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=600,  # Increased to 600px
        width=800,   # Add explicit width
        margin=dict(l=80, r=80, t=80, b=80),  # Increased margins for labels
        showlegend=False
    )
    return dcc.Graph(figure=fig, className="graph-container", style={'height': '600px','width':'100%'} )


def create_industry_allocation_chart(holdings, prices):
    """
    Generate an industry‑wise allocation pie chart.
    Small sectors (<2% of total) are grouped into 'Other'.
    """
    if holdings.empty or prices.empty:
        return html.Div("No data available", className="text-white")

    latest_holdings = holdings.iloc[-1]
    latest_prices = prices.iloc[-1]

    # Compute market values per symbol
    symbol_values = {}
    for col in holdings.columns:
        if col in latest_prices and latest_holdings[col] > 0.01:
            mv = latest_holdings[col] * latest_prices[col]
            if mv > 1:
                symbol_values[col] = mv

    if not symbol_values:
        return html.Div("No data available", className="text-white")

    # Map symbols to sectors using yfinance
    sector_map = {}
    for sym in symbol_values:
        try:
            info = yf.Ticker(sym).info
            sector = info.get('sector', 'Unknown')
        except Exception:
            sector = 'Unknown'
        sector_map[sym] = sector

    # Aggregate values per sector
    sector_values = {}
    for sym, val in symbol_values.items():
        sector = sector_map.get(sym, 'Unknown')
        sector_values[sector] = sector_values.get(sector, 0) + val

    total = sum(sector_values.values())
    sectors = []
    values = []
    other_total = 0.0
    for sec, val in sector_values.items():
        if val / total >= 0.02:
            sectors.append(sec)
            values.append(val)
        else:
            other_total += val
    if other_total > 0:
        sectors.append('Other')
        values.append(other_total)

    fig = go.Figure(
        data=[go.Pie(
            labels=sectors,
            values=values,
            textposition='outside',
            textinfo='label+percent',
            hovertemplate='<b>%{label}</b><br>$%{value:,.2f}<br>%{percent}',
            textfont=dict(size=14, color='white'),
            marker=dict(line=dict(color='rgba(0,0,0,0)', width=0))
            )]
    )
    fig.update_layout(
        template='plotly_dark',
        title=dict(text='Industry Allocation', font=dict(size=22, color='white')),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=600,
        margin=dict(l=80, r=80, t=80, b=80),
        showlegend=False
    )
    return dcc.Graph(figure=fig, className="graph-container", style={'height': '600px','width':'100%'})

def create_holdings_table(holdings_data):
    if not holdings_data:
        return html.Div("No holdings data available", className="text-muted")
        
    df = pd.DataFrame(holdings_data)
    
    # Format columns
    # Expected cols: Symbol, Quantity, Avg Cost, Total Cost, Current Price, Market Value, Unrealized P/L, P/L %
    
    columns = [
        {"name": "Symbol", "id": "Symbol"},
        {"name": "Qty", "id": "Quantity", "type": "numeric", "format": {"specifier": ".2f"}},
        {"name": "Avg Cost", "id": "Avg Cost", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "Current Price", "id": "Current Price", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "Market Value", "id": "Market Value", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "Unrealized P/L", "id": "Unrealized P/L", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "P/L %", "id": "P/L %", "type": "numeric", "format": {"specifier": ".2%"}},
    ]
    
    return dash_table.DataTable(
        data=df.to_dict('records'),
        columns=columns,
        sort_action="native",
        style_as_list_view=True,
        style_header={
            'backgroundColor': '#1e1e1e',
            'fontWeight': 'bold',
            'color': 'white',
            'border': '1px solid #333'
        },
        style_cell={
            'backgroundColor': '#121212',
            'color': '#e0e0e0',
            'border': '1px solid #333',
            'padding': '10px'
        },
        style_data_conditional=[
            {
                'if': {
                    'filter_query': '{Unrealized P/L} >= 0',
                    'column_id': 'Unrealized P/L'
                },
                'color': '#00d084'
            },
            {
                'if': {
                    'filter_query': '{Unrealized P/L} < 0',
                    'column_id': 'Unrealized P/L'
                },
                'color': '#cf2e2e'
            },
            {
                'if': {
                    'filter_query': '{P/L %} >= 0',
                    'column_id': 'P/L %'
                },
                'color': '#00d084'
            },
            {
                'if': {
                    'filter_query': '{P/L %} < 0',
                    'column_id': 'P/L %'
                },
                'color': '#cf2e2e'
            }
        ]
    )

def create_history_table(history_data):
    if not history_data:
        return html.Div("No transaction history available", className="text-muted")
        
    df = pd.DataFrame(history_data)
    
    # Add summary row
    total_pnl = df['Realized P/L'].sum()
    
    # Format columns
    columns = [
        {"name": "Date", "id": "Date", "type": "datetime"},
        {"name": "Symbol", "id": "Symbol"},
        {"name": "Qty Sold", "id": "Qty", "type": "numeric", "format": {"specifier": ".2f"}},
        {"name": "Sell Price", "id": "Sell Price", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "Cost Basis", "id": "Cost Basis", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "Proceeds", "id": "Proceeds", "type": "numeric", "format": {"specifier": "$,.2f"}},
        {"name": "Realized P/L", "id": "Realized P/L", "type": "numeric", "format": {"specifier": "$,.2f"}},
    ]
    
    return html.Div([
        html.H5(f"Total Realized P/L: ${total_pnl:,.2f}", className=f"mb-3 {'text-success' if total_pnl >= 0 else 'text-danger'}"),
        dash_table.DataTable(
            data=df.to_dict('records'),
            columns=columns,
            sort_action="native",
            page_size=10,
            style_as_list_view=True,
            style_header={
                'backgroundColor': '#1e1e1e',
                'fontWeight': 'bold',
                'color': 'white',
                'border': '1px solid #333'
            },
            style_cell={
                'backgroundColor': '#121212',
                'color': '#e0e0e0',
                'border': '1px solid #333',
                'padding': '10px'
            },
            style_data_conditional=[
                {
                    'if': {
                        'filter_query': '{Realized P/L} >= 0',
                        'column_id': 'Realized P/L'
                    },
                    'color': '#00d084'
                },
                {
                    'if': {
                        'filter_query': '{Realized P/L} < 0',
                        'column_id': 'Realized P/L'
                    },
                    'color': '#cf2e2e'
                }
            ]
        )
    ])
