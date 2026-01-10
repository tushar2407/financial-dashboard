import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

# Add src to path
sys.path.append(os.path.abspath('src'))

from data_loader import load_and_clean_data, categorize_transactions, get_portfolio_history, fetch_price_data, calculate_portfolio_value
from metrics import get_daily_cash_flows

def debug_twr():
    df = load_and_clean_data()
    df = categorize_transactions(df)
    
    # Individual account seems to be the one with -44%
    target_df = df[df['Account'] == 'Individual']
    
    holdings, symbols = get_portfolio_history(target_df)
    start_date = target_df['Run Date'].min().strftime('%Y-%m-%d')
    prices = fetch_price_data(symbols, start_date, tx_df=target_df)
    portfolio_value = calculate_portfolio_value(holdings, prices)
    daily_flows = get_daily_cash_flows(target_df)
    
    # Calculate geometric components
    p_series = portfolio_value[portfolio_value > 0]
    if p_series.empty:
        print("No non-zero portfolio value found.")
        return
        
    first_idx = p_series.index[0]
    p_series = portfolio_value[portfolio_value.index >= first_idx]
    
    flows = daily_flows.reindex(p_series.index, fill_value=0.0)
    prev_val = p_series.shift(1)
    denom = prev_val + flows
    
    mask = (denom > 0) & (p_series > 0) & (prev_val.notna())
    day_rets = p_series[mask] / denom[mask]
    
    linked_rets = day_rets.cumprod() - 1
    
    # Create a debug DF
    debug_df = pd.DataFrame({
        'Value': p_series,
        'Flow': flows,
        'Prev_Value': prev_val,
        'Denom': denom,
        'Day_Ret': day_rets,
        'Total_TWR': linked_rets
    })
    
    # Find the largest drops
    print("Largest Daily Drops in TWR:")
    print(debug_df.sort_values('Day_Ret').head(10))
    
    print("\nTimeline of Total TWR (Every 30 days):")
    print(debug_df['Total_TWR'].iloc[::30])
    
    print(f"\nFinal TWR: {debug_df['Total_TWR'].iloc[-1]*100:.2f}%")

if __name__ == "__main__":
    debug_twr()
