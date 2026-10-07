import pandas as pd
import numpy as np
from scipy import optimize
from datetime import datetime

def align_flows(daily_cash_flows, index):
    """Cash flows re-dated onto `index` (the dates the portfolio is valued).

    A flow on a date with no valuation (weekend, market holiday) counts on the
    next valued date, the first value that includes it; flows after the last
    valued date count on the last one. Without this, reindexing silently drops
    those flows and the deposit looks like investment return.
    """
    if daily_cash_flows.empty or len(index) == 0:
        return pd.Series(0.0, index=index)
    positions = index.searchsorted(pd.DatetimeIndex(daily_cash_flows.index)).clip(max=len(index) - 1)
    aligned = pd.Series(daily_cash_flows.values, index=index[positions])
    return aligned.groupby(level=0).sum().reindex(index, fill_value=0.0)


def calculate_twr(portfolio_series, daily_cash_flows):
    """
    Calculate the Time-Weighted Return (TWR).
    TWR = Product (Ending Value / (Beginning Value + Net Cash Flow)) - 1
    """
    if portfolio_series.empty or (portfolio_series <= 0).all():
        return None
        
    # Trim to start from first non-zero value
    first_idx = portfolio_series[portfolio_series > 0].index[0]
    p_series = portfolio_series[portfolio_series.index >= first_idx]
    
    if len(p_series) < 2:
        return None
        
    flows = align_flows(daily_cash_flows[daily_cash_flows.index >= first_idx], p_series.index)
    
    # Previous day's value
    prev_val = p_series.shift(1)
    
    # Daily returns
    denom = prev_val + flows
    
    # We only care about days where we actually have capital and a previous day value
    # AND where denom is not zero.
    mask = (denom > 0) & (p_series > 0) & (prev_val.notna())
    
    # Calculate returns for valid days
    day_rets = p_series[mask] / denom[mask]
    
    if day_rets.empty:
        return None
        
    # Geometrically link
    total_twr = day_rets.prod() - 1
    
    return total_twr

def xnpv(rate, values, dates):
    """
    Calculate the Net Present Value for a schedule of cash flows.
    """
    if rate <= -1.0:
        return float('inf')
    d0 = dates[0]
    return sum([vi / (1.0 + rate)**((di - d0).days / 365.0) for vi, di in zip(values, dates)])

def calculate_xirr(values, dates):
    """
    Calculate the Internal Rate of Return for a schedule of cash flows.
    """
    if len(values) < 2:
        return None
        
    # Check if we have both positive and negative values (required for IRR)
    if all(v >= 0 for v in values) or all(v <= 0 for v in values):
        return None

    try:
        # Try with a default guess
        return optimize.newton(lambda r: xnpv(r, values, dates), 0.1)
    except (RuntimeError, OverflowError):
        # Try with different guesses if it fails to converge
        for guess in [-0.1, 0.0, 0.2, 0.5]:
            try:
                return optimize.newton(lambda r: xnpv(r, values, dates), guess)
            except (RuntimeError, OverflowError):
                continue
        return None

def calculate_cagr(start_value, end_value, years):
    """
    Calculate Compound Annual Growth Rate.
    """
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return 0.0
    return (end_value / start_value) ** (1 / years) - 1

def get_daily_cash_flows(df):
    """
    Extracts daily cash flows from the transactions dataframe.
    """
    if df.empty:
        return pd.Series(dtype=float)

    # Filter for Deposits, Withdrawals, retirement contributions, and internal transfers
    transfers = df[df['Category'].isin(['DEPOSIT', 'WITHDRAWAL', 'CONTRIBUTION',
                                        'INTERNAL_TRANSFER', 'PLAN_TRANSFER_OUT'])].copy()
    
    if transfers.empty:
        return pd.Series(dtype=float)
        
    # Create daily flows
    # Use the transactions' actual dates
    flows = []
    for _, row in transfers.iterrows():
        amount = 0
        if row['Category'] == 'CONTRIBUTION':
            # Contributions are capital inflows
            amount = abs(row['Amount'])
        elif row['Category'] in ('INTERNAL_TRANSFER', 'PLAN_TRANSFER_OUT'):
            # Internal transfers are capital inflows/outflows for individual account views.
            # In combined views (where both sides are present), they net to $0.
            amount = row['Amount']
        else:
            amount = row['Amount']
        
        if amount != 0:
            flows.append({'Date': row['Run Date'], 'Amount': amount})
            
    if not flows:
        return pd.Series(dtype=float)
        
    flow_df = pd.DataFrame(flows)
    daily_flow = flow_df.groupby('Date')['Amount'].sum()
    
    return daily_flow

def calculate_net_invested(df):
    """
    Calculates the cumulative net invested capital (Deposits - Withdrawals) over time.
    """
    daily_flow = get_daily_cash_flows(df)
    if daily_flow.empty:
        return pd.Series(dtype=float)
        
    # Reindex to full date range to match portfolio history
    start_date = df['Run Date'].min()
    end_date = datetime.now()
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    
    daily_flow_full = daily_flow.reindex(date_range, fill_value=0.0)
    net_invested = daily_flow_full.cumsum()
    
    return net_invested

def calculate_net_invested_breakdown(df):
    """
    Calculates the breakdown of Net Invested:
    - Electronic Transfers (Deposits)
    - ESPP Credits (Deposits)
    - Withdrawals
    """
    if df.empty:
        return {'transfers': 0, 'espp': 0, 'contributions': 0, 'withdrawals': 0, 'total': 0}
        
    # Electronic fund transfers (deposits)
    transfers = df[
        (df['Category'] == 'DEPOSIT') & (
            df['Description'].str.contains('ELECTRONIC FUNDS TRANSFER', case=False, na=False) |
            df['Action'].str.contains('ELECTRONIC FUNDS TRANSFER', case=False, na=False)
        )
    ]['Amount'].sum()
    
    # ESPP contributions (MSFT BUY)
    espp = df[
        (df['Category'] == 'BUY') & (df['Symbol'] == 'MSFT') & (
            df['Description'].str.contains('ESPP', case=False, na=False) |
            df['Action'].str.contains('ESPP', case=False, na=False)
        )
    ]['Amount'].abs().sum()
    
    # Retirement plan contributions (e.g. 401k payroll deductions)
    contributions = df[df['Category'] == 'CONTRIBUTION']['Amount'].abs().sum()
    
    # Withdrawals (including any negative DEPOSIT amounts if they exist)
    withdrawals = df[df['Category'] == 'WITHDRAWAL']['Amount'].sum()

    # Internal transfers between brokerage accounts
    internal_transfers = df[df['Category'].isin(['INTERNAL_TRANSFER', 'PLAN_TRANSFER_OUT'])]['Amount'].sum()
    
    return {
        'transfers': transfers,
        'espp': espp,
        'contributions': contributions,
        'withdrawals': withdrawals,
        'internal_transfers': internal_transfers,
        'total': transfers + espp + contributions + withdrawals + internal_transfers
    }

def calculate_dividend_income(df) -> float:
    """Dividends received, net of foreign tax withheld and fees.

    This is the part of Total P&L that Realized and Unrealized P/L miss:
    reinvested dividends become lots at their own cost, so they add no
    unrealized gain.
    """
    if df.empty:
        return 0.0
    income = df[df['Category'].isin(['DIVIDEND', 'TAX', 'FEE'])]['Amount'].sum()
    return float(income)


def calculate_performance_metrics(portfolio_series, daily_cash_flows):
    """
    Calculates performance metrics (XIRR) for different periods.
    """
    if portfolio_series.empty:
        return {}
        
    current_val = portfolio_series.iloc[-1]
    current_date = portfolio_series.index[-1]
    
    metrics = {}
    
    # 1. Lifetime XIRR
    all_dates = list(daily_cash_flows.index)
    all_values = [-v for v in daily_cash_flows.values] # Deposits are negative out-flows for IRR
    
    # Add current value as a positive in-flow at the end
    all_dates.append(current_date)
    all_values.append(current_val)
    
    metrics['Lifetime_XIRR'] = calculate_xirr(all_values, all_dates)
    metrics['Lifetime_TWR'] = calculate_twr(portfolio_series, daily_cash_flows)
    
    # 2. Periodic Metrics (1Y, YTD, etc.)
    periods = {
        '1Y': pd.Timedelta(days=365),
        'YTD': None
    }
    
    for label, delta in periods.items():
        if label == 'YTD':
            start_date = pd.Timestamp(year=current_date.year, month=1, day=1)
        else:
            start_date = current_date - delta
            
        # Find portfolio value at start_date
        idx = portfolio_series.index.searchsorted(start_date)
        if idx < len(portfolio_series):
            actual_start_date = portfolio_series.index[idx]
            
            # Period data
            p_series = portfolio_series[portfolio_series.index >= actual_start_date]
            p_flows = daily_cash_flows[daily_cash_flows.index >= actual_start_date].copy()
            
            # For XIRR, the "start value" is treated as the first deposit
            p_xirr_values = [-p_series.iloc[0]]
            p_xirr_dates = [actual_start_date]
            
            # Intermediate flows (exclude the very first day's flow if it's already in p_series.iloc[0])
            # Wait, daily_cash_flows already has the external flow. 
            # If we start "as of" start_date, the flow *on* that day is usually included in start_val.
            # So we only include flows *after* start_date.
            sub_flows = daily_cash_flows[daily_cash_flows.index > actual_start_date]
            for d, v in sub_flows.items():
                p_xirr_values.append(-v)
                p_xirr_dates.append(d)
                
            p_xirr_values.append(current_val)
            p_xirr_dates.append(current_date)
            
            metrics[f'{label}_XIRR'] = calculate_xirr(p_xirr_values, p_xirr_dates)
            
            # For TWR, we just use the subset
            # But the very first flow in p_flows is technically external to the sub-period's return
            # TWR sub-period starts at the *end* of the first day.
            metrics[f'{label}_TWR'] = calculate_twr(p_series, sub_flows)
        else:
            metrics[f'{label}_XIRR'] = None
            metrics[f'{label}_TWR'] = None
            
    return metrics

def calculate_yearly_returns(portfolio_series, daily_cash_flows):
    """
    Calculates XIRR and TWR for each calendar year in the data.
    """
    if portfolio_series.empty:
        return []
        
    start_year = portfolio_series.index.year.min()
    current_year = datetime.now().year
    
    yearly_metrics = []
    
    # Exclude current year as it's partial/non-representative for annual comparison
    for year in range(start_year, current_year):
        year_start = pd.Timestamp(year=year, month=1, day=1)
        year_end = pd.Timestamp(year=year, month=12, day=31)
        
        # Adjust start/end to data range
        calc_start = max(year_start, portfolio_series.index.min())
        calc_end = min(year_end, portfolio_series.index.max())
        
        if calc_start >= calc_end:
             continue
             
        # Find portfolio value at calc_start
        # If calc_start is absolute min, start_val is 0
        if calc_start == portfolio_series.index.min():
            start_val = 0
        else:
            # Value at the end of the day BEFORE calc_start
            idx = portfolio_series.index.searchsorted(calc_start)
            if idx > 0:
                start_val = portfolio_series.iloc[idx-1]
            else:
                start_val = portfolio_series.iloc[0]
            
        # End val
        idx_end = portfolio_series.index.searchsorted(calc_end)
        end_val = portfolio_series.iloc[idx_end] if idx_end < len(portfolio_series) else portfolio_series.iloc[-1]
        
        # Flows within the year
        year_flows = daily_cash_flows[(daily_cash_flows.index >= calc_start) & (daily_cash_flows.index <= calc_end)]
        
        # XIRR
        xirr_values = []
        xirr_dates = []
        
        if start_val > 0:
            xirr_values.append(-start_val)
            xirr_dates.append(calc_start)
        
        # Intermediate flows
        for d, v in year_flows.items():
            # If we already have a start_val on this date, we don't want to double count
            # Actually, the start_val is at the BEGINNING of calc_start (end of prev day)
            # and year_flows are the flows ON calc_start. So we should include them.
            xirr_values.append(-v)
            xirr_dates.append(d)
            
        xirr_values.append(end_val)
        xirr_dates.append(calc_end)
        
        year_xirr = calculate_xirr(xirr_values, xirr_dates)
        
        # TWR
        # Portfolio subset
        p_sub = portfolio_series[(portfolio_series.index >= calc_start) & (portfolio_series.index <= calc_end)]
        # TWR needs the flow on the same day as the portfolio value change
        year_twr = calculate_twr(p_sub, year_flows)
        
        yearly_metrics.append({
            'Year': year,
            'XIRR': year_xirr if year_xirr is not None else 0,
            'TWR': year_twr if year_twr is not None else 0
        })
        
    return yearly_metrics

def is_long_term(purchase_date, sale_date) -> bool:
    """US tax rule: a gain is long-term when the shares were held more than one year."""
    return sale_date > purchase_date + pd.DateOffset(years=1)


def _consume_lots_fifo(symbol_lots: list, qty: float) -> list:
    """Removes `qty` shares from the oldest lots first (mutates `symbol_lots`).

    Returns the pieces taken, oldest first, as dicts with the lot's
    'date' and 'cost' (per share) and the 'qty' taken from it.
    """
    remaining = qty
    pieces = []
    while remaining > 0 and symbol_lots:
        lot = symbol_lots[0]
        take = min(lot['qty'], remaining)
        pieces.append({'date': lot['date'], 'cost': lot['cost'], 'qty': take})
        remaining -= take
        if lot['qty'] > take:
            lot['qty'] -= take
        else:
            symbol_lots.pop(0)
    return pieces


def calculate_cost_basis(df):
    """
    Calculates FIFO cost basis, realized P/L, and current holdings.

    Lots are matched within each account (as Fidelity does), then holdings of
    the same stock are merged into one row.
    Returns:
    - current_holdings: List of dicts
    - realized_pnl: List of dicts
    """
    if df.empty or 'Account' not in df.columns or df['Account'].nunique() <= 1:
        return _cost_basis_single_account(df)

    merged, realized = {}, []
    for _, acct_df in df.groupby('Account', sort=False):
        holdings, acct_realized = _cost_basis_single_account(acct_df)
        realized.extend(acct_realized)
        for h in holdings:
            m = merged.setdefault(h['Symbol'], {'Symbol': h['Symbol'], 'Quantity': 0.0,
                                                'Total Cost': 0.0, 'Lots': []})
            m['Quantity'] += h['Quantity']
            m['Total Cost'] += h['Total Cost']
            m['Lots'].extend(h['Lots'])
    for m in merged.values():
        m['Avg Cost'] = m['Total Cost'] / m['Quantity']
        m['Lots'].sort(key=lambda lot: lot['date'])
    realized.sort(key=lambda r: r['Date'])
    return list(merged.values()), realized


def _cost_basis_single_account(df):
    """FIFO cost basis for transactions from one account."""
    if df.empty:
        return [], []

    # Sort by date and reset index so iterrows() processes in correct order
    # Preserve original CSV order for transactions on the same day by using original index as tiebreaker
    df = df.reset_index(drop=False).rename(columns={'index': 'original_index'})
    df = df.sort_values(['Run Date', 'original_index']).reset_index(drop=True)
    
    # Track lots for each symbol: list of (date, qty, price_per_share)
    lots = {} 
    realized_pnl = []
    
    for _, row in df.iterrows():
        symbol = row['Symbol']
        if pd.isna(symbol) or symbol == '':
            continue
            
        action = row['Category']
        qty = row['Quantity']
        amount = row['Amount'] # Total amount (negative for buy, positive for sell usually)
        date = row['Run Date']
        
        if symbol not in lots:
            lots[symbol] = []
            
        if action in ['BUY', 'CONTRIBUTION', 'REINVESTMENT']:
            # Add a new lot
            # Cost per share = abs(amount) / qty
            # Note: Amount is negative for buys.
            cost_per_share = abs(amount) / qty if qty != 0 else 0
            lots[symbol].append({'date': date, 'qty': qty, 'cost': cost_per_share})
            
        elif action == 'DISTRIBUTION':
            # Stock split distribution - shares received at $0 cost
            # These are free shares from stock splits
            lots[symbol].append({'date': date, 'qty': qty, 'cost': 0})
            
        elif action == 'SELL':
            # FIFO matching
            qty_to_sell = abs(qty) # Sell qty is negative in CSV? 
            # In data_loader, we didn't check sign of qty for SELL. 
            # Usually in these CSVs, sell qty is negative. Let's assume abs().
            
            sell_price = amount / qty_to_sell if qty_to_sell != 0 else 0
            # Wait, if amount is positive for sell, and qty is negative, price is negative?
            # Let's check CSV. Line 8: "YOU SOLD ... -19 ... 1525.96".
            # So Qty is negative, Amount is positive.
            # Sell Price = 1525.96 / 19 = 80.31.
            sell_price = abs(amount / qty)
            
            pieces = _consume_lots_fifo(lots[symbol], qty_to_sell)
            cost_basis = sum(p['qty'] * p['cost'] for p in pieces)
            shares_sold_so_far = sum(p['qty'] for p in pieces)
            share_days = sum(p['qty'] * (date - p['date']).days for p in pieces)
            long_term = sum(p['qty'] * (sell_price - p['cost']) for p in pieces
                            if is_long_term(p['date'], date))

            # Record Realized P/L
            # Proceeds = shares_sold_so_far * sell_price
            # P/L = Proceeds - Cost Basis
            proceeds = shares_sold_so_far * sell_price
            pnl = proceeds - cost_basis
            
            realized_pnl.append({
                'Symbol': symbol,
                'Date': date,
                'Qty': shares_sold_so_far,
                'Sell Price': sell_price,
                'Cost Basis': cost_basis,
                'Proceeds': proceeds,
                'Realized P/L': pnl,
                'Holding Days': round(share_days / shares_sold_so_far) if shares_sold_so_far else 0,
                'Long-Term P/L': long_term,
                'Short-Term P/L': pnl - long_term,
                'Account': row.get('Account', ''),
                'Account Type': row.get('Account Type', 'brokerage'),
            })

        elif action == 'PLAN_TRANSFER_OUT':
            # Money moved out of the plan at cost: not a sale, no realized P/L
            _consume_lots_fifo(lots[symbol], abs(qty))

    # Construct Current Holdings from remaining lots
    current_holdings = []
    for symbol, remaining_lots in lots.items():
        total_qty = sum(lot['qty'] for lot in remaining_lots)
        if total_qty > 0.01: # Filter out dust (increased threshold to handle rounding errors)
            total_cost = sum(lot['qty'] * lot['cost'] for lot in remaining_lots)
            avg_cost = total_cost / total_qty
            current_holdings.append({
                'Symbol': symbol,
                'Quantity': total_qty,
                'Avg Cost': avg_cost,
                'Total Cost': total_cost,
                'Lots': [dict(lot) for lot in remaining_lots],
            })
            
    return current_holdings, realized_pnl
