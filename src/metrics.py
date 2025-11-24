import pandas as pd
import numpy as np
from scipy import optimize
from datetime import datetime

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
    try:
        return optimize.newton(lambda r: xnpv(r, values, dates), 0.1)
    except RuntimeError:
        return None

def calculate_cagr(start_value, end_value, years):
    """
    Calculate Compound Annual Growth Rate.
    """
    if start_value <= 0 or years <= 0:
        return 0.0
    return (end_value / start_value) ** (1 / years) - 1

def calculate_period_returns(portfolio_series):
    """
    Calculates MoM, WoW, YoY returns based on the portfolio value series.
    Returns a dictionary of percentage changes.
    """
    if portfolio_series.empty:
        return {}
        
    current_val = portfolio_series.iloc[-1]
    current_date = portfolio_series.index[-1]
    
    returns = {}
    
    # Define periods
    periods = {
        '1W': pd.Timedelta(weeks=1),
        '1M': pd.Timedelta(days=30),
        '3M': pd.Timedelta(days=90),
        '6M': pd.Timedelta(days=180),
        '1Y': pd.Timedelta(days=365),
        'YTD': None # Special case
    }
    
    for label, delta in periods.items():
        if label == 'YTD':
            start_of_year = pd.Timestamp(year=current_date.year, month=1, day=1)
            # Find closest date
            idx = portfolio_series.index.searchsorted(start_of_year)
            if idx < len(portfolio_series):
                prev_val = portfolio_series.iloc[idx]
                returns[label] = (current_val - prev_val) / prev_val if prev_val != 0 else 0
        else:
            target_date = current_date - delta
            # Find closest date
            idx = portfolio_series.index.searchsorted(target_date)
            if idx < len(portfolio_series):
                # Check if the date is reasonably close (e.g. within a few days)
                # If the history is short, searchsorted might return 0
                prev_val = portfolio_series.iloc[idx]
                returns[label] = (current_val - prev_val) / prev_val if prev_val != 0 else 0
            else:
                returns[label] = None # Not enough history
                
    return returns

def calculate_net_invested(df):
    """
    Calculates the cumulative net invested capital (Deposits - Withdrawals) over time.
    For 401k, BUY transactions are contributions and should count as deposits.
    """
    if df.empty:
        return pd.Series(dtype=float)

    # Filter for Deposits, Withdrawals, and 401k BUY contributions only
    # We include BUY rows only when they belong to the 401k account (i.e., contributions)
    transfers = df[df['Category'].isin(['DEPOSIT', 'WITHDRAWAL', 'BUY'])].copy()
    
    # Create a daily series
    start_date = df['Run Date'].min()
    end_date = datetime.now()
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    
    daily_flow = pd.Series(0.0, index=date_range)
    
    for _, row in transfers.iterrows():
        date = row['Run Date']
        if row['Category'] == 'BUY':
            # Only count BUY as a cash inflow when it is a 401k contribution (Account is 401k)
            if row.get('Account') == 'MICROSOFT 401K PLAN':
                daily_flow[date] += abs(row['Amount'])
        else:
            # DEPOSIT is positive, WITHDRAWAL is negative
            daily_flow[date] += row['Amount']
    
    # Cumulative sum to get total invested over time
    net_invested = daily_flow.cumsum()
    
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
