import pandas as pd
import sys
import os
import numpy as np
from datetime import datetime

# Add src to path
sys.path.append(os.path.abspath('src'))

from data_loader import load_and_clean_data, categorize_transactions, get_portfolio_history, fetch_price_data, calculate_portfolio_value
from metrics import get_daily_cash_flows, calculate_performance_metrics

def diagnose():
    print("Loading data...")
    df = load_and_clean_data()
    df = categorize_transactions(df)
    
    if df.empty:
        print("No data found!")
        return

    print(f"Data range: {df['Run Date'].min()} to {df['Run Date'].max()}")
    
    for account in ['Combined', 'Individual', 'MICROSOFT 401K PLAN']:
        print(f"\n--- Calculations for {account} ---")
        if account == 'Combined':
            target_df = df
        else:
            target_df = df[df['Account'] == account]
            
        if target_df.empty:
            print("No data for this account.")
            continue
            
        holdings, symbols = get_portfolio_history(target_df)
        start_date = df['Run Date'].min().strftime('%Y-%m-%d')
        prices = fetch_price_data(symbols, start_date, tx_df=target_df)
        portfolio_value = calculate_portfolio_value(holdings, prices)
        daily_flows = get_daily_cash_flows(target_df)
        
        metrics = calculate_performance_metrics(portfolio_value, daily_flows)
        
        current_val = portfolio_value.iloc[-1]
        total_invested = daily_flows.sum()
        
        print(f"Current Value: ${current_val:,.2f}")
        print(f"Total Invested: ${total_invested:,.2f}")
        
        # We check both XIRR and TWR
        if metrics.get('1Y_XIRR') is not None:
            print(f"1Y - XIRR: {metrics['1Y_XIRR']*100:.2f}%")
            print(f"1Y - TWR:  {metrics['1Y_TWR']*100:.2f}%")
        else:
            print("1Y Metrics: N/A")
            
        if metrics.get('Lifetime_XIRR') is not None:
            print(f"Lifetime - XIRR: {metrics['Lifetime_XIRR']*100:.2f}%")
            print(f"Lifetime - TWR:  {metrics['Lifetime_TWR']*100:.2f}%")

if __name__ == "__main__":
    diagnose()
