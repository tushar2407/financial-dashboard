import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

import glob
import os

DATA_PATH = 'data/Accounts_History*.csv'

def load_and_clean_data(filepath_pattern=DATA_PATH):
    """
    Loads all CSV files matching the pattern, merges them, and cleans the dataframe.
    """
    all_files = glob.glob(filepath_pattern)
    if not all_files:
        print("No files found matching pattern:", filepath_pattern)
        return pd.DataFrame()
        
    df_list = []
    for filename in all_files:
        print(f"Loading {filename}...")
        try:
            # Skip the first 2 rows as seen in the file view
            # Pre-read and fix lines with extra columns (401k rows have an extra trailing comma)
            with open(filename, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()[2:]  # Skip first 2 rows
            
            # Fix lines with trailing commas
            fixed_lines = []
            for line in lines:
                # If line ends with just commas and newline, remove the extra trailing comma
                if line.rstrip().endswith(',,'):
                    line = line.rstrip()[:-1] + '\n'  # Remove one trailing comma
                fixed_lines.append(line)
            
            # Read the fixed CSV from string
            from io import StringIO
            temp_df = pd.read_csv(StringIO(''.join(fixed_lines)), low_memory=False)
            
            # If there are extra columns, drop the last one if it's all NaN
            if temp_df.shape[1] > 18:
                # Check if last column is all NaN
                if temp_df.iloc[:, -1].isna().all():
                    temp_df = temp_df.iloc[:, :-1]
            
            # Fix column misalignment/naming based on observation
            if 'Quantity' in temp_df.columns and temp_df['Quantity'].astype(str).str.contains('USD').any():
                temp_df = temp_df.rename(columns={
                    'Quantity': 'Currency_Name',
                    'Currency': 'Price',
                    'Price': 'Quantity'
                })
            
            df_list.append(temp_df)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            
    if not df_list:
        return pd.DataFrame()
        
    df = pd.concat(df_list, ignore_index=True)
    
    # Drop duplicates (exact row matches)
    df = df.drop_duplicates()
    
    # Drop the last footer rows (usually contain legal text)
    # We can identify them by checking if 'Run Date' is NaN or doesn't look like a date
    df = df.dropna(subset=['Run Date'])
    df = df[df['Run Date'].str.match(r'\d{2}/\d{2}/\d{4}', na=False)]

    # Convert date columns
    df['Run Date'] = pd.to_datetime(df['Run Date'], format='%m/%d/%Y')
    df['Settlement Date'] = pd.to_datetime(df['Settlement Date'], format='%m/%d/%Y', errors='coerce')

    # Clean Symbol column and handle 401k contributions
    if 'Symbol' in df.columns:
        # For 401k contributions, extract symbol from Description
        if 'Description' in df.columns and 'Action' in df.columns:
            mask = df['Action'].str.contains('Contributions', case=False, na=False) & df['Symbol'].isna()
            if mask.any():
                # Extract symbol from Description (e.g., "FID GR CO POOL CL S" or "VANG RUS 1000 GR TR")
                df.loc[mask, 'Symbol'] = df.loc[mask, 'Description'].astype(str).str.strip()
        
        df['Symbol'] = df['Symbol'].astype(str).str.strip()

    # clean numeric columns
    numeric_cols = ['Quantity', 'Price', 'Amount', 'Commission', 'Fees', 'Accrued Interest']
    for col in numeric_cols:
        if col in df.columns:
            # Remove '$' and ',' if present (though pandas might handle it, explicit is safer)
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    return df

def categorize_transactions(df):
    """
    Adds a 'Transaction Category' column to the dataframe.
    """
    def get_category(row):
        action = str(row['Action']).upper()
        description = str(row['Description']).upper()
        
        if "ELECTRONIC FUNDS TRANSFER" in action or "ELECTRONIC FUNDS TRANSFER" in description:
            if row['Amount'] > 0:
                return "DEPOSIT"
            else:
                return "WITHDRAWAL"
        elif "JOURNALED SPP PURCHASE CREDIT" in description or "JOURNALED SPP PURCHASE CREDIT" in action:
            return "DEPOSIT"
        elif "YOU BOUGHT" in action or "CONTRIBUTIONS" in action:
            return "BUY"  # 401k contributions are purchases
        elif "YOU SOLD" in action:
            return "SELL"
        elif "DISTRIBUTION" in action:
            return "DISTRIBUTION"  # Stock split distributions
        elif "DIVIDEND" in action:
            return "DIVIDEND"
        elif "REINVESTMENT" in action:
            return "REINVESTMENT"
        elif "FOREIGN TAX" in action:
            return "TAX"
        elif "ADVISORY FEE" in action:
            return "FEE"
        else:
            return "OTHER"

    df['Category'] = df.apply(get_category, axis=1)
    return df

def get_portfolio_history(df):
    """
    Reconstructs the portfolio holdings and value over time.
    Note: Stock splits are already reflected in CSV transactions (e.g., DISTRIBUTION entries).
    Yahoo Finance also returns split-adjusted prices, so no manual adjustment is needed.
    """
    if df.empty:
        return pd.DataFrame(), []

    # Sort by date
    df = df.sort_values('Run Date')
    
    # Get unique symbols
    symbols = df['Symbol'].dropna().unique()
    symbols = [s for s in symbols if isinstance(s, str) and s.strip() != '']
    
    # Mapping for known issues
    ticker_map = {
        'SPYM': 'SPLG',
        '565849106': None,
    }
    
    valid_symbols = []
    for s in symbols:
        mapped = ticker_map.get(s, s)
        if mapped:
            valid_symbols.append(mapped)
            
    if not valid_symbols:
        return pd.DataFrame(), []

    # Date range from first transaction to today
    start_date = df['Run Date'].min()
    end_date = datetime.now()
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    
    # Initialize holdings: {Symbol: Quantity}
    current_holdings = {s: 0.0 for s in symbols}
    
    # Store history: List of dicts, then convert to DF
    history_list = []
    
    # Group transactions by date for faster access
    tx_by_date = df.groupby(df['Run Date'].dt.date)
    
    for date in date_range:
        date_date = date.date()
        
        # Process Transactions
        if date_date in tx_by_date.groups:
            day_txs = tx_by_date.get_group(date_date)
            for _, row in day_txs.iterrows():
                symbol = row['Symbol']
                if pd.isna(symbol) or symbol == '':
                    continue
                    
                action = row['Category']
                qty = row['Quantity']
                
                if symbol not in current_holdings:
                    current_holdings[symbol] = 0.0
                
                if action in ['BUY', 'REINVESTMENT', 'DISTRIBUTION']:
                    current_holdings[symbol] += qty
                elif action == 'SELL':
                    current_holdings[symbol] += qty  # Qty is negative for sell
                    
        # Store daily snapshot
        snapshot = current_holdings.copy()
        snapshot['Date'] = date
        history_list.append(snapshot)
    
    holdings_df = pd.DataFrame(history_list).set_index('Date')
    holdings_df = holdings_df.fillna(0)
    return holdings_df, valid_symbols

def get_transaction_prices(df):
    """
    Extra
    tive prices from transactions to use as fallback.
    """
    if df.empty:
        return pd.DataFrame()
        
    # Filter for Buy/Sell/Reinvest where we have a price
    # Note: Price column in df is already cleaned
    price_txs = df[df['Price'] > 0][['Run Date', 'Symbol', 'Price']].copy()
    price_txs['Run Date'] = pd.to_datetime(price_txs['Run Date'])
    
    # Pivot to have Dates as Index and Symbols as Columns
    # If multiple txs on same day for same symbol, take the mean or last. Let's take last.
    tx_prices = price_txs.pivot_table(index='Run Date', columns='Symbol', values='Price', aggfunc='last')
    
    return tx_prices

def fetch_price_data(symbols, start_date, tx_df=None):
    """
    Fetches historical price data for the given symbols.
    Merges with transaction prices if tx_df is provided.
    """
    print(f"Fetching data for: {symbols}")
    
    # Mapping for known issues
    ticker_map = {
        # 'SPYM': 'SPLG', 
        '565849106': None, 
    }
    
    valid_symbols = []
    reverse_map = {} # To map back SPLG -> SPYM if needed, or just use mapped
    
    for s in symbols:
        mapped = ticker_map.get(s, s)
        if mapped:
            valid_symbols.append(mapped)
            reverse_map[mapped] = s
            
    if not valid_symbols:
        return pd.DataFrame()

    # 1. Fetch Market Data
    try:
        market_data = yf.download(valid_symbols, start=start_date, progress=False)['Close']
        if isinstance(market_data, pd.Series):
            market_data = market_data.to_frame(name=valid_symbols[0])
    except Exception as e:
        print(f"Error fetching market data: {e}")
        market_data = pd.DataFrame()
    
    # 1.5 Add manual prices for 401k mutual funds that yfinance can't fetch
    # These prices are from the actual brokerage account as of Nov 23, 2025
    manual_prices = {
        'FID GR CO POOL CL S': 84.32,
        'VANG RUS 1000 GR TR': 558.95
    }
    
    # Add manual prices to market_data
    today = datetime.now()
    for symbol, price in manual_prices.items():
        if symbol in symbols:
            # Create a series for this symbol with the current price
            if market_data.empty:
                market_data = pd.DataFrame(index=pd.date_range(start=start_date, end=today, freq='D'))
            
            # Fill the entire period with the current price (NAV doesn't change minute-to-minute)
            market_data[symbol] = price

    # 2. Get Transaction Prices
    tx_prices = pd.DataFrame()
    if tx_df is not None:
        tx_prices = get_transaction_prices(tx_df)
        
    # 3. Merge
    # We want to use Market Data where available, and fallback to Transaction Prices
    # But wait, Market Data (Yahoo) might end today (2024), while Tx Prices go into 2025.
    # So we should combine them.
    
    # First, rename market data columns back to original symbols if possible, or handle mapping
    # Let's standardize on the symbols used in holdings (which are the original CSV symbols)
    # So we need to rename market_data columns: SPLG -> SPYM
    # But wait, valid_symbols has mapped names.
    
    # Let's create a combined DF with original symbols
    combined_prices = pd.DataFrame()
    
    # Process Market Data
    if not market_data.empty:
        # Rename columns to match original symbols
        # reverse_map: {'SPLG': 'SPYM'}
        # But what if multiple symbols map to same? (Unlikely here)
        # Also, what if no mapping? s -> s.
        
        # Create a map from YF Ticker -> CSV Symbol
        yf_to_csv = {}
        for csv_sym in symbols:
            yf_sym = ticker_map.get(csv_sym, csv_sym)
            if yf_sym:
                yf_to_csv[yf_sym] = csv_sym
                
        market_data = market_data.rename(columns=yf_to_csv)
        combined_prices = market_data
        
    # Process Tx Prices (already has original symbols)
    if not tx_prices.empty:
        # Combine: Market data takes precedence? 
        # Actually, for future dates, Market Data won't exist.
        # So combine_first is good: df1.combine_first(df2) updates nulls in df1 with values from df2.
        # But we want to extend the index too.
        
        # Let's reindex both to the full union of dates
        all_dates = combined_prices.index.union(tx_prices.index).sort_values()
        
        combined_prices = combined_prices.reindex(all_dates)
        tx_prices = tx_prices.reindex(all_dates)
        
        # Fill Market Data gaps with Tx Prices?
        # Or better: Use Market Data if available, else Tx Price.
        # But Tx Price is sparse (only on tx days).
        # So we should ffill Tx Prices first?
        # No, we want the "Latest known price".
        
        # Strategy:
        # 1. Create a master timeline.
        # 2. Fill with Market Data.
        # 3. Fill remaining NaNs with Transaction Data.
        # 4. Forward fill everything.
        
        combined_prices = combined_prices.combine_first(tx_prices)
        
    # Forward fill to propagate last known price
    combined_prices = combined_prices.ffill()
    
    return combined_prices

def calculate_portfolio_value(holdings_df, price_df):
    """
    Calculates the total portfolio value over time.
    """
    # Align dates
    common_dates = holdings_df.index.intersection(price_df.index)
    holdings = holdings_df.loc[common_dates]
    prices = price_df.loc[common_dates]
    
    # Rename price columns to match holdings
    ticker_map = {
        'SPYM': 'SPLG',
    }
    reverse_map = {v: k for k, v in ticker_map.items()}
    prices = prices.rename(columns=reverse_map)
    
    # Ensure we only use columns present in both
    common_cols = list(set(holdings.columns) & set(prices.columns))
    
    if not common_cols:
        return pd.Series(0.0, index=common_dates)
        
    holdings = holdings[common_cols]
    prices = prices[common_cols]
    
    # Calculate value
    # fillna(0) for prices to avoid NaN propagating (though 0 price is also wrong, but better than crashing)
    prices = prices.ffill()
    
    val_df = holdings * prices
    portfolio_value = val_df.sum(axis=1)
            
    return portfolio_value

if __name__ == "__main__":
    # Test run
    df = load_and_clean_data()
    df = categorize_transactions(df)
    print("Data loaded and categorized.")
    print(df[['Run Date', 'Action', 'Category', 'Amount']].head())
    
    holdings, symbols = get_portfolio_history(df)
    print(f"Holdings calculated for {len(symbols)} symbols.")
    
    print(f"Holdings shape: {holdings.shape}")
    print(f"Holdings columns: {holdings.columns[:5]}")
    print(f"Holdings head: \n{holdings.head()}")
    
    start_date = holdings.index.min().strftime('%Y-%m-%d')
    prices = fetch_price_data(symbols, start_date)
    print(f"Prices shape: {prices.shape}")
    print(f"Prices columns: {prices.columns[:5]}")
    print(f"Prices head: \n{prices.head()}")
    
    val = calculate_portfolio_value(holdings, prices)
    print(f"Portfolio Value shape: {val.shape}")
    print("Portfolio value calculated.")
    print(val.tail())
