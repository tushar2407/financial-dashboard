import pandas as pd
import numpy as np
from scipy import optimize
from datetime import datetime

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
        
    # Reindex flows to match portfolio dates
    flows = daily_cash_flows.reindex(p_series.index, fill_value=0.0)
    
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

    # Filter for Deposits, Withdrawals, and 401k BUY contributions
    # We include BUY rows only when they belong to the 401k account (i.e., contributions)
    transfers = df[df['Category'].isin(['DEPOSIT', 'WITHDRAWAL', 'BUY'])].copy()
    
    if transfers.empty:
        return pd.Series(dtype=float)
        
    # Create daily flows
    # Use the transactions' actual dates
    flows = []
    for _, row in transfers.iterrows():
        amount = 0
        if row['Category'] == 'BUY':
            if row.get('Account') == 'MICROSOFT 401K PLAN':
                amount = abs(row['Amount'])
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
    
    # 401k contributions are BUY transactions with a non‑MSFT symbol (mutual‑fund names) and must belong to the 401k account
    contributions = df[(df['Category'] == 'BUY') & (df['Account'] == 'MICROSOFT 401K PLAN') & (~df['Symbol'].isin(['MSFT']))]['Amount'].abs().sum()
    
    # Withdrawals (including any negative DEPOSIT amounts if they exist)
    withdrawals = df[df['Category'] == 'WITHDRAWAL']['Amount'].sum()
    
    return {
        'transfers': transfers,
        'espp': espp,
        'contributions': contributions,
        'withdrawals': withdrawals,
        'total': transfers + espp + contributions + withdrawals
    }

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

def calculate_cost_basis(df):
    """
    Calculates FIFO cost basis, realized P/L, and current holdings.
    Returns:
    - current_holdings: List of dicts
    - realized_pnl: List of dicts
    """
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
            
        if action in ['BUY', 'REINVESTMENT']:
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
            
            cost_basis = 0
            shares_sold_so_far = 0
            
            while qty_to_sell > 0 and lots[symbol]:
                current_lot = lots[symbol][0]
                
                if current_lot['qty'] > qty_to_sell:
                    # Partial lot sale
                    cost_basis += qty_to_sell * current_lot['cost']
                    current_lot['qty'] -= qty_to_sell
                    shares_sold_so_far += qty_to_sell
                    qty_to_sell = 0
                else:
                    # Full lot sale
                    cost_basis += current_lot['qty'] * current_lot['cost']
                    shares_sold_so_far += current_lot['qty']
                    qty_to_sell -= current_lot['qty']
                    lots[symbol].pop(0)
            
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
                'Realized P/L': pnl
            })

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
                'Total Cost': total_cost
            })
            
    return current_holdings, realized_pnl
