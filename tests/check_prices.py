import pandas as pd
import sys
import os

# Add src to path
sys.path.append(os.path.abspath('src'))

from data_loader import load_and_clean_data, categorize_transactions

def check_prices():
    df = load_and_clean_data()
    df = categorize_transactions(df)
    
    symbols = ['FID GR CO POOL CL S', 'VANG RUS 1000 GR TR']
    for sym in symbols:
        print(f"\nPrices for {sym}:")
        sym_df = df[df['Symbol'] == sym].sort_values('Run Date')
        if sym_df.empty:
            # Try finding in description
            sym_df = df[df['Description'].str.contains(sym, na=False)].sort_values('Run Date')
            
        if not sym_df.empty:
            # Print a few samples across time
            print(sym_df[['Run Date', 'Price', 'Quantity', 'Amount']])
            
            # Check price variation
            prices = sym_df['Price'].unique()
            print(f"Unique prices found: {len(prices)}")
            if len(prices) > 1:
                print(f"Price range: {min(prices)} to {max(prices)}")
        else:
            print("No transactions found for this symbol.")

if __name__ == "__main__":
    check_prices()
