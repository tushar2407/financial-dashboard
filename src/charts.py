"""Figures for the Overview, Allocation, Activity and Taxes views.

Charts carry no titles of their own: the surrounding panel header names them.

Colors come from the dataviz reference palette's dark column, validated against
the card surface (#0d0d0d): series 1 blue for the portfolio, series 2 orange for
the benchmark, and the blue/red diverging pair for gains/losses. Every chart uses
a single y-axis.
"""
import pandas as pd
import plotly.graph_objects as go
from dash import dcc

from formatting import money, pct

SERIES_1 = '#3987e5'      # portfolio / single-series bars
SERIES_2 = '#d95926'      # benchmark
SERIES_3 = '#199e70'      # third categorical slot (dividends)
GAIN = '#3987e5'          # diverging pole: positive
LOSS = '#e66767'          # diverging pole: negative
REFERENCE = '#c3c2b7'     # neutral reference line (net invested)
TEXT_PRIMARY = '#ededef'
TEXT_SECONDARY = '#a1a1aa'
GRID = '#26262b'
TREEMAP_LEAF = '#1f4f86'     # muted series-1 blue so labels stay readable
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
CASH_TILE = '#383835'     # diverging-neutral gray: cash is not a sector


def _base_layout(title: str, height: int = 360, **extra) -> dict:
    """`title` is unused (the panel header shows it); kept so call sites read clearly."""
    return dict(
        template='plotly_dark',
        title=None,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family=FONT, color=TEXT_SECONDARY, size=12),
        height=height,
        margin=dict(l=4, r=4, t=8, b=4),
        hoverlabel=dict(bgcolor='#17171a', bordercolor='#34343a',
                        font=dict(family=FONT, color=TEXT_PRIMARY, size=12)),
        xaxis=dict(showgrid=False, color=TEXT_SECONDARY, linecolor=GRID),
        yaxis=dict(showgrid=True, gridcolor=GRID, zeroline=False, color=TEXT_SECONDARY),
        **extra,
    )


def _signed_money(v: float) -> str:
    return money(v, signed=True, zero_dash=False)


def _graph(fig: go.Figure) -> dcc.Graph:
    return dcc.Graph(figure=fig, config={'displayModeBar': False}, className="graph-container")


def _empty(title: str, message: str) -> dcc.Graph:
    fig = go.Figure()
    fig.update_layout(**_base_layout(title, height=220))
    fig.add_annotation(text=message, showarrow=False, font=dict(color=TEXT_SECONDARY, size=13))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _graph(fig)


def growth_vs_benchmark(window: dict, benchmark_name: str) -> dcc.Graph:
    """Portfolio vs. the benchmark over a window (see insights.compare_window),
    with the money put in as the reference. All three share one dollar axis."""
    title = f"Your portfolio vs. {benchmark_name}"
    portfolio = window['portfolio']
    if portfolio.empty:
        return _empty(title, "No portfolio history yet")

    invested_name = 'Net invested' if window['range'] == 'ALL' else 'Starting value + deposits'
    series = [
        ('Your portfolio', portfolio, SERIES_1, 'solid', 2),
        (f'Same money in {benchmark_name}', window['benchmark'], SERIES_2, 'solid', 2),
        (invested_name, window['invested'], REFERENCE, 'dash', 1.5),
    ]
    short = len(portfolio) <= 8     # 1D / 5D: show the individual closes
    fig = go.Figure()
    for name, s, color, dash, width in series:
        if s is None or s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, name=name, mode='lines+markers' if short else 'lines',
            line=dict(color=color, width=width, dash=dash), marker=dict(size=8),
            hovertemplate=f'{name}: $%{{y:,.0f}}<extra></extra>',
        ))
        # Direct label at the line end so identity is not color-alone
        fig.add_annotation(x=s.index[-1], y=s.values[-1], text=f"${s.values[-1]:,.0f}",
                           showarrow=False, xanchor='left', xshift=8,
                           font=dict(color=TEXT_PRIMARY, size=12))

    fig.update_layout(**_base_layout(
        title, height=400, hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='left', x=0,
                    font=dict(color=TEXT_SECONDARY, size=12)),
    ))
    fig.update_layout(margin=dict(l=4, r=76, t=28, b=4))
    fig.update_yaxes(tickprefix='$', tickformat=',.0f')
    fig.update_xaxes(showspikes=True, spikemode='across', spikethickness=1,
                     spikecolor='#45454c', spikedash='solid')
    if short:
        fig.update_xaxes(tickformat='%b %d', dtick=86400000)
    return _graph(fig)


def allocation_treemap(positions: list, cash: float) -> dcc.Graph:
    """Sector -> holding treemap sized by market value. One hue: sectors are
    identified by their labels, not by color (there are more than 8)."""
    title = "Where your money is"
    if not positions and not cash:
        return _empty(title, "No holdings")

    total = sum(p['Value'] for p in positions) + cash
    ids, labels, parents, values, colors, text = [], [], [], [], [], []
    sectors = {}
    for p in positions:
        sectors.setdefault(p['Sector'], []).append(p)
    for sector, members in sorted(sectors.items(), key=lambda kv: -sum(m['Value'] for m in kv[1])):
        sector_value = sum(m['Value'] for m in members)
        ids.append(f"s:{sector}"); labels.append(sector); parents.append("")
        values.append(sector_value); colors.append('#17171a')
        text.append(f"{sector_value / total:.1%}")
        for m in members:
            ids.append(f"p:{m['Symbol']}"); labels.append(m['Symbol']); parents.append(f"s:{sector}")
            values.append(m['Value']); colors.append(TREEMAP_LEAF); text.append(f"{m['Weight']:.1%}")
    if cash:
        ids.append("cash"); labels.append("Cash"); parents.append("")
        values.append(cash); colors.append(CASH_TILE); text.append(f"{cash / total:.1%}")

    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, text=text,
        branchvalues='total',
        marker=dict(colors=colors, line=dict(color='#121214', width=2)),
        textinfo='label+text',
        textfont=dict(family=FONT, color=TEXT_PRIMARY),
        hovertemplate='<b>%{label}</b><br>$%{value:,.0f} · %{text}<extra></extra>',
        pathbar=dict(visible=False),
    ))
    fig.update_layout(**_base_layout(title, height=480))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    return _graph(fig)


def monthly_bars(series: pd.Series, title: str, value_label: str, money: bool = False) -> dcc.Graph:
    """Single-series monthly bar chart (e.g. trades per month, deposits)."""
    if series.empty:
        return _empty(title, "No data")
    x = [p.to_timestamp() for p in series.index]
    fmt = '$%{y:,.0f}' if money else '%{y:,.0f}'
    fig = go.Figure(go.Bar(
        x=x, y=series.values, marker=dict(color=SERIES_1),
        hovertemplate=f'%{{x|%b %Y}}<br>{value_label}: {fmt}<extra></extra>',
    ))
    fig.update_layout(**_base_layout(title, height=300, bargap=0.25, barcornerradius=4))
    if money:
        fig.update_yaxes(tickprefix='$', tickformat=',.0f')
    return _graph(fig)


def realized_by_symbol_chart(by_symbol: pd.Series, n: int = 8) -> dcc.Graph:
    """Biggest realized losses and gains by stock, on a shared zero baseline."""
    title = "Biggest realized gains and losses"
    if by_symbol.empty:
        return _empty(title, "No closed trades yet")
    worst = by_symbol[by_symbol < 0].head(n)
    best = by_symbol[by_symbol > 0].tail(n)
    shown = pd.concat([worst, best])
    fig = go.Figure(go.Bar(
        x=shown.values, y=shown.index, orientation='h',
        marker=dict(color=[GAIN if v >= 0 else LOSS for v in shown.values]),
        text=[_signed_money(v) for v in shown.values], textposition='outside',
        textfont=dict(color=TEXT_PRIMARY, size=11), cliponaxis=False,
        customdata=[_signed_money(v) for v in shown.values],
        hovertemplate='<b>%{y}</b><br>Realized: %{customdata}<extra></extra>',
    ))
    fig.update_layout(**_base_layout(title, height=max(300, 26 * len(shown) + 80), barcornerradius=4))
    fig.update_layout(margin=dict(l=4, r=56, t=8, b=4))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor='#45454c',
                     tickprefix='$', tickformat=',.0f')
    fig.update_yaxes(showgrid=False, autorange='reversed')
    return _graph(fig)


def yearly_returns_chart(yearly: list) -> dcc.Graph:
    """XIRR and TWR per calendar year, grouped, on one percent axis."""
    title = "Returns by year"
    if not yearly:
        return _empty(title, "Not enough history for a full year")
    years = [str(y['Year']) for y in yearly]
    fig = go.Figure()
    for key, name, color in (('XIRR', 'Personal return (XIRR)', SERIES_1),
                             ('TWR', 'Portfolio return (TWR)', SERIES_2)):
        values = [y[key] * 100 for y in yearly]
        fig.add_trace(go.Bar(
            x=years, y=values, name=name, marker=dict(color=color),
            text=[pct(v / 100) for v in values], textposition='outside',
            textfont=dict(color=TEXT_PRIMARY, size=12), cliponaxis=False,
            hovertemplate=f'%{{x}}<br>{name}: %{{y:+.1f}}%<extra></extra>',
        ))
    fig.update_layout(**_base_layout(
        title, height=340, barmode='group', bargap=0.35, bargroupgap=0.08, barcornerradius=4,
        legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='left', x=0,
                    font=dict(color=TEXT_SECONDARY, size=12)),
    ))
    fig.update_layout(margin=dict(l=4, r=4, t=28, b=4))
    fig.update_yaxes(ticksuffix='%', zeroline=True, zerolinecolor='#45454c')
    return _graph(fig)


def tax_years_chart(summary: pd.DataFrame) -> dcc.Graph:
    """Short-term gains, long-term gains and dividends per year (taxable accounts)."""
    title = "Gains and dividends by tax year"
    if summary.empty:
        return _empty(title, "No taxable gains or dividends")
    current = pd.Timestamp.now().year
    years = [f"{y} (to date)" if y == current else str(y) for y in summary.index]
    fig = go.Figure()
    for column, name, color in (('realized_st', 'Short-term gains', SERIES_1),
                                ('realized_lt', 'Long-term gains', SERIES_2),
                                ('dividends', 'Dividends', SERIES_3)):
        values = summary[column].tolist()
        fig.add_trace(go.Bar(
            x=years, y=values, name=name, marker=dict(color=color),
            text=[_signed_money(v) if abs(v) >= 0.5 else '' for v in values], textposition='outside',
            textfont=dict(color=TEXT_PRIMARY, size=11), cliponaxis=False,
            customdata=[_signed_money(v) for v in values],
            hovertemplate=f'%{{x}}<br>{name}: %{{customdata}}<extra></extra>',
        ))
    fig.update_layout(**_base_layout(
        title, height=360, barmode='group', bargap=0.3, bargroupgap=0.08, barcornerradius=4,
        legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='left', x=0,
                    font=dict(color=TEXT_SECONDARY, size=12)),
    ))
    fig.update_layout(margin=dict(l=4, r=4, t=28, b=4))
    fig.update_yaxes(tickprefix='$', tickformat=',.0f', zeroline=True,
                     zerolinecolor='#45454c')
    return _graph(fig)
