import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

import glob
import os
import json
import time

DATA_PATH = 'data/Accounts_History*.csv'
CACHE_PATH = 'data/sector_cache.json'

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
            # Read lines and find where the header actually starts
            with open(filename, 'r', encoding='utf-8-sig') as f:
                raw_lines = f.readlines()
            
            # Find the header row (contains 'Run Date')
            header_idx = 0
            for i, line in enumerate(raw_lines):
                if 'Run Date' in line:
                    header_idx = i
                    break
            
            lines = raw_lines[header_idx:]
            
            # Fix lines with trailing commas (common in 401k rows)
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
            # Remove '$' and ',' if present
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Calculate implicit price for transactions where it's missing (common in 401k)
    mask = (df['Price'] == 0) & (df['Quantity'] != 0) & (df['Amount'] != 0)
    if mask.any():
        df.loc[mask, 'Price'] = (df.loc[mask, 'Amount'] / df.loc[mask, 'Quantity']).abs()

    return df

def categorize_transactions(df):
    """
    Adds a 'Transaction Category' column to the dataframe.
    """
    def get_category(row):
        action = str(row['Action']).upper()
        description = str(row['Description']).upper()
        
        # Inter-account transfers (between Fidelity brokerage accounts)
        if "TRANSFERRED TO" in action or "TRANSFERRED FROM" in action:
            return "INTERNAL_TRANSFER"
        elif "ELECTRONIC FUNDS TRANSFER" in action or "ELECTRONIC FUNDS TRANSFER" in description:
            if row['Amount'] > 0:
                return "DEPOSIT"
            else:
                return "WITHDRAWAL"
        elif "JOURNALED SPP PURCHASE CREDIT" in description or "JOURNALED SPP PURCHASE CREDIT" in action:
            return "DEPOSIT"
        elif "CONTRIBUTIONS" in action:
            return "CONTRIBUTION"  # New money (e.g. payroll) buying fund shares in a 401k
        elif "YOU BOUGHT" in action:
            return "BUY"
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
        elif "ADVISORY FEE" in action or "FEE CHARGED" in action:
            return "FEE"
        else:
            return "OTHER"

    categorized = df.assign(Category=df.apply(get_category, axis=1))
    return _add_plan_transfer_outs(_mark_round_trip_transfers(categorized))


# Fidelity 401k -> BrokerageLink flow: contributions first buy a placeholder
# "BROKERAGELINK" position (at $1/unit) inside the plan account, then a few days
# later the cash lands in the BrokerageLink account as a transfer. The export
# never reduces the placeholder, so without a correction the same dollars are
# counted in both accounts.
BROKERAGELINK_PLACEHOLDER = 'BROKERAGELINK'
BROKERAGELINK_ARRIVAL_ACTION = 'BROKERAGE OPTION'


def _add_plan_transfer_outs(df):
    """Adds a derived PLAN_TRANSFER_OUT row to the plan account for every
    BrokerageLink arrival, draining the placeholder by the same amount.

    The derived row moves no cash, reduces placeholder units, and is a capital
    outflow for the plan, so it nets to zero against the BrokerageLink
    INTERNAL_TRANSFER in combined views.
    """
    placeholder_rows = df[(df['Category'] == 'CONTRIBUTION') &
                          (df['Symbol'] == BROKERAGELINK_PLACEHOLDER)]
    plan_accounts = placeholder_rows['Account'].unique()
    if len(plan_accounts) != 1:
        return df

    arrivals = df[(df['Category'] == 'INTERNAL_TRANSFER') &
                  (df['Amount'] > 0) &
                  df['Action'].astype(str).str.upper().str.contains(BROKERAGELINK_ARRIVAL_ACTION)]
    if arrivals.empty:
        return df

    template = placeholder_rows.iloc[0]
    derived = pd.DataFrame([
        {
            **template.to_dict(),
            'Run Date': row['Run Date'],
            'Action': "Moved to BrokerageLink (derived)",
            'Description': "Derived from BrokerageLink transfer",
            'Category': 'PLAN_TRANSFER_OUT',
            'Quantity': -row['Amount'],
            'Price': 1.0,
            'Amount': -row['Amount'],
        }
        for _, row in arrivals.iterrows()
    ])
    return pd.concat([df, derived], ignore_index=True)


# A withdrawal returned to the same account in full within this many days is
# money that never really left the portfolio (e.g. a reversed or re-deposited
# bank transfer), so neither leg counts as a withdrawal or deposit.
ROUND_TRIP_MAX_DAYS = 10


def _mark_round_trip_transfers(df):
    """Recategorizes matched WITHDRAWAL -> DEPOSIT pairs as ROUND_TRIP_TRANSFER.

    A pair matches when the deposit is in the same account, for the same
    absolute amount, and lands 0..ROUND_TRIP_MAX_DAYS days after the
    withdrawal. Each deposit matches at most one withdrawal. Pairs sum to
    zero, so net invested is unchanged; only the gross totals shrink.
    """
    withdrawals = df[df['Category'] == 'WITHDRAWAL'].sort_values('Run Date')
    deposits = df[df['Category'] == 'DEPOSIT'].sort_values('Run Date')
    if withdrawals.empty or deposits.empty:
        return df

    max_gap = pd.Timedelta(days=ROUND_TRIP_MAX_DAYS)
    matched = set()
    for w_idx, w in withdrawals.iterrows():
        candidates = deposits[
            (deposits['Account'] == w['Account'])
            & (deposits['Amount'] == -w['Amount'])
            & (deposits['Run Date'] >= w['Run Date'])
            & (deposits['Run Date'] - w['Run Date'] <= max_gap)
            & ~deposits.index.isin(matched)
        ]
        if not candidates.empty:
            matched |= {w_idx, candidates.index[0]}

    if not matched:
        return df
    is_round_trip = df.index.isin(matched)
    return df.assign(Category=df['Category'].where(~is_round_trip, 'ROUND_TRIP_TRANSFER'))


# ── Retirement account keywords ───────────────────────────────────────────────
# BROKERAGELINK is Fidelity's self-directed window inside a 401k; the money is
# locked up like the rest of the plan.
_RETIREMENT_KEYWORDS = ['401K', '401(K)', 'IRA', 'ROTH', 'RETIREMENT', 'PENSION', 'BROKERAGELINK']


def _classify_account_type(account_name: str) -> str:
    """Classify an account as 'brokerage' or 'retirement' based on its name."""
    upper = account_name.upper()
    for kw in _RETIREMENT_KEYWORDS:
        if kw in upper:
            return 'retirement'
    return 'brokerage'


def discover_accounts(df) -> dict:
    """
    Discovers all accounts present in the dataframe and classifies them.

    Returns a dict with:
      - accounts: list of dicts with name, number, type, row_count
      - brokerage_accounts: list of brokerage account names
      - retirement_accounts: list of retirement account names
    """
    if df.empty:
        return {'accounts': [], 'brokerage_accounts': [], 'retirement_accounts': []}

    accounts = []
    for acct_name in df['Account'].dropna().unique():
        acct_df = df[df['Account'] == acct_name]
        acct_num = ''
        if 'Account Number' in df.columns:
            nums = acct_df['Account Number'].dropna().unique()
            acct_num = str(nums[0]) if len(nums) > 0 else ''

        accounts.append({
            'name': acct_name,
            'number': acct_num,
            'type': _classify_account_type(acct_name),
            'row_count': len(acct_df),
        })

    # Sort: brokerage first (by row count desc), then retirement
    accounts.sort(key=lambda a: (0 if a['type'] == 'brokerage' else 1, -a['row_count']))

    brokerage = [a['name'] for a in accounts if a['type'] == 'brokerage']
    retirement = [a['name'] for a in accounts if a['type'] == 'retirement']

    return {
        'accounts': accounts,
        'brokerage_accounts': brokerage,
        'retirement_accounts': retirement,
    }


def tag_account_types(df, account_meta: dict) -> pd.DataFrame:
    """Adds an 'Account Type' column ('brokerage' or 'retirement') to the df."""
    type_map = {a['name']: a['type'] for a in account_meta['accounts']}
    df['Account Type'] = df['Account'].map(type_map).fillna('brokerage')
    return df


# Categories whose Amount moves cash in or out of the account. A reinvested
# dividend appears as DIVIDEND (+) and REINVESTMENT (-) on the same day, so
# both must be counted or the dividend is double-counted as cash and shares.
CASH_CATEGORIES = {'DEPOSIT', 'WITHDRAWAL', 'SELL', 'BUY', 'DIVIDEND', 'REINVESTMENT',
                   'TAX', 'FEE', 'INTERNAL_TRANSFER'}
# CONTRIBUTION is absent from CASH_CATEGORIES: the money goes straight into
# fund shares and never sits in the account as cash.
SHARE_CHANGING_CATEGORIES = {'BUY', 'CONTRIBUTION', 'SELL', 'REINVESTMENT', 'DISTRIBUTION',
                             'PLAN_TRANSFER_OUT'}


def _cash_delta(row) -> float:
    """Change in uninvested cash caused by one categorized transaction."""
    category = row['Category']
    if category not in CASH_CATEGORIES:
        return 0.0
    return row['Amount']


def get_current_cash(df) -> float:
    """Current uninvested cash balance implied by the transactions."""
    if df.empty:
        return 0.0
    return float(sum(_cash_delta(row) for _, row in df.iterrows()))


def get_portfolio_history(df):
    """
    Reconstructs the portfolio holdings and value over time.
    Note: share counts are as recorded at the time (splits arrive as DISTRIBUTION
    entries), so prices must not be split-adjusted; fetch_price_data undoes
    Yahoo's split adjustment.
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
    
    # Initialize holdings and cash
    current_holdings = {s: 0.0 for s in symbols}
    cash_balance = 0.0
    
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
                action = row['Category']
                qty = row['Quantity']
                cash_balance += _cash_delta(row)

                # Share quantity changes
                if action in SHARE_CHANGING_CATEGORIES:
                    if symbol not in current_holdings:
                        current_holdings[symbol] = 0.0
                    current_holdings[symbol] += qty  # qty is negative for SELL
                    
        # Store daily snapshot
        snapshot = current_holdings.copy()
        snapshot['Cash'] = cash_balance
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

def fetch_sector_data(symbols, retry_unknown=()):
    """
    Fetches sector information for the given symbols with caching.

    Symbols cached as 'Unknown' are normally not re-fetched; those listed in
    `retry_unknown` (e.g. current holdings) are, since 'Unknown' is also what a
    failed download leaves behind.
    """
    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)
    
    # Load cache
    cache = {}
    updated = False
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                cache = json.load(f)
        except Exception as e:
            print(f"Error loading sector cache: {e}")
            
    # Identify missing symbols
    # Symbols already in cache (even if Unknown) should NOT be re-fetched every time
    # Also ignore 'nan' or empty strings
    retry = set(retry_unknown)
    missing_symbols = [s for s in symbols if s and str(s).lower() != 'nan'
                       and (s not in cache or (s in retry and cache[s] == 'Unknown'))]
    
    # Manual Mapping for ETFs and common symbols that yfinance fails on
    ETF_SECTORS = {
        'VOOG': 'ETF - Growth',
        'SCHG': 'ETF - Growth',
        'VTI' : 'ETF - Broad Market',
        'QQQM': 'ETF - Technology/Nasdaq',
        'IBIT': 'ETF - Crypto',
        'NLR' : 'ETF - Energy/Uranium',
        'SMH' : 'ETF - Semiconductors',
        'GLDM': 'ETF - Gold',
        'SPYM': 'ETF - S&P 500',
        'ARKK': 'ETF - Innovation',
        'SPLG': 'ETF - S&P 500',
        'SPAXX': 'Cash (Money Market)',
        'FIG' : 'Technology', # Figma
        'FID GR CO POOL CL S': '401k - Growth',
        'VANG RUS 1000 GR TR': '401k - Growth',
        'VOO': 'ETF - S&P 500',
        'BTCI': 'ETF - Crypto',
        'VCX': 'Fund - Private Companies',
        BROKERAGELINK_PLACEHOLDER: 'Cash (Money Market)',
    }
    
    # Manual mapping wins over a missing or 'Unknown' cache entry
    for sym in symbols:
        if sym in ETF_SECTORS and cache.get(sym, 'Unknown') == 'Unknown':
            cache[sym] = ETF_SECTORS[sym]
            updated = True
            
    # Re-check missing after manual mapping
    missing_symbols = [s for s in missing_symbols if cache.get(s, 'Unknown') == 'Unknown']
    
    if not missing_symbols:
        # One-time cleanup: remove 'nan' if it exists in cache
        if "nan" in cache:
            del cache["nan"]
            updated = True
        if updated:
             with open(CACHE_PATH, 'w') as f:
                json.dump(cache, f, indent=4)
        return cache
        
    print(f"Fetching sector data for {len(missing_symbols)} symbols...")
    
    # Fetch missing data
    for i, sym in enumerate(missing_symbols):
        try:
            print(f"Fetching sector for {sym} ({i+1}/{len(missing_symbols)})...")
            ticker = yf.Ticker(sym)
            info = ticker.info
            sector = info.get('sector', 'Unknown')
            cache[sym] = sector
            updated = True
            
            # Sleep to avoid rate limits
            time.sleep(2)
            
        except Exception as e:
            print(f"Error fetching sector for {sym}: {e}")
            cache[sym] = 'Unknown' # Mark as Unknown so we don't retry forever
            updated = True
            # Back off more aggressively on errors (likely 429)
            time.sleep(5)
            
    # Save cache if updated
    if updated:
        try:
            # Final cleanup of invalid keys before saving
            cache = {k: v for k, v in cache.items() if k and str(k).lower() != 'nan'}
            with open(CACHE_PATH, 'w') as f:
                json.dump(cache, f, indent=4)
        except Exception as e:
            print(f"Error saving sector cache: {e}")
            
    return cache

# A market price older than this (in days) means the download failed for that
# symbol; 5 days covers weekends and market holidays.
MAX_PRICE_AGE_DAYS = 5


def find_stale_price_symbols(market_data, symbols, today=None, max_age_days=MAX_PRICE_AGE_DAYS):
    """Symbols whose downloaded market price is missing or older than max_age_days.

    Such symbols silently fall back to their last transaction price, which can be
    months old, so callers should warn about them.
    """
    cutoff = pd.Timestamp(today or datetime.now()).normalize() - pd.Timedelta(days=max_age_days)
    stale = []
    for s in symbols:
        series = market_data[s].dropna() if s in market_data.columns else pd.Series(dtype=float)
        if series.empty or series.index[-1] < cutoff:
            stale.append(s)
    return stale


def unadjust_for_splits(prices, splits):
    """Undo Yahoo's split adjustment so prices match the share counts recorded
    at the time (Fidelity history is not split-adjusted; the split itself shows
    up later as a DISTRIBUTION of extra shares).

    A split of ratio r on day d multiplies every earlier price by r; the close on
    d is already post-split. Returns a new frame.
    """
    out = prices.copy()
    for sym in splits.columns.intersection(out.columns):
        events = splits[sym].fillna(0)
        events = events[events > 0]
        for split_date, ratio in events.items():
            out.loc[out.index < split_date, sym] *= ratio
    return out


def fetch_price_data(symbols, start_date, tx_df=None):
    """
    Fetches historical price data for the given symbols.
    Merges with transaction prices if tx_df is provided.
    """
    print(f"Fetching data for: {symbols}")
    
    # Mapping for known issues / renames
    ticker_map = {
        # 'SPYM': 'SPLG', 
        '565849106': None, 
    }

    # Symbols that can't be fetched from Yahoo (money markets, 401k mutual funds, etc.)
    _SKIP_SYMBOLS = {'SPAXX', BROKERAGELINK_PLACEHOLDER, 'nan', 'NAN', ''}

    valid_symbols = []
    reverse_map = {}  # To map back SPLG -> SPYM if needed
    
    for s in symbols:
        # Skip known unfetchable symbols
        if s in _SKIP_SYMBOLS:
            continue
        # Skip symbols with spaces (mutual fund names like 'FID GR CO POOL CL S')
        if ' ' in str(s):
            continue
        # Skip pure numeric CUSIPs
        if str(s).isdigit():
            continue

        mapped = ticker_map.get(s, s)
        if mapped:
            valid_symbols.append(mapped)
            reverse_map[mapped] = s
            
    if not valid_symbols:
        return pd.DataFrame()

    # 1. Fetch Market Data in batches to avoid Yahoo rate limits
    BATCH_SIZE = 20
    market_data = pd.DataFrame()
    split_data = pd.DataFrame()
    for batch_start in range(0, len(valid_symbols), BATCH_SIZE):
        batch = valid_symbols[batch_start:batch_start + BATCH_SIZE]
        print(f"  Fetching price batch {batch_start // BATCH_SIZE + 1}"
              f"/{(len(valid_symbols) + BATCH_SIZE - 1) // BATCH_SIZE}"
              f" ({len(batch)} symbols)...")

        for attempt in range(3):  # Retry up to 3 times per batch
            try:
                # auto_adjust=False: Close is split-adjusted only (not for
                # dividends); splits are undone below using 'Stock Splits'.
                raw = yf.download(batch, start=start_date, progress=False,
                                  auto_adjust=False, actions=True)
                batch_data = raw['Close']
                batch_splits = raw['Stock Splits'] if 'Stock Splits' in raw else pd.DataFrame()
                if isinstance(batch_data, pd.Series):
                    batch_data = batch_data.to_frame(name=batch[0])
                if isinstance(batch_splits, pd.Series):
                    batch_splits = batch_splits.to_frame(name=batch[0])
                market_data = batch_data if market_data.empty else market_data.join(batch_data, how='outer')
                split_data = batch_splits if split_data.empty else split_data.join(batch_splits, how='outer')
                break  # Success — move to next batch
            except Exception as e:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s backoff
                print(f"  Batch failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)

        # Sleep between batches to stay under rate limits
        if batch_start + BATCH_SIZE < len(valid_symbols):
            time.sleep(2)
    
    # 1.5 Add manual prices for 401k mutual funds that yfinance can't fetch
    # These prices are from the actual brokerage account as of Nov 23, 2025
    manual_prices = {
        'FID GR CO POOL CL S': 84.32,
        'VANG RUS 1000 GR TR': 558.95
    }
    
    # Initialize market_data if empty
    today = datetime.now()
    if market_data.empty:
        market_data = pd.DataFrame(index=pd.date_range(start=start_date, end=today, freq='D'))

    # Only fill the LATEST price as a benchmark if the symbol is missing from YF
    for symbol, price in manual_prices.items():
        if symbol in symbols and symbol not in market_data.columns:
            market_data[symbol] = np.nan
            # Set only the last date with the manual price
            market_data.iloc[-1, market_data.columns.get_loc(symbol)] = price

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
        if not split_data.empty:
            market_data = unadjust_for_splits(market_data, split_data.rename(columns=yf_to_csv))
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

    requested = [reverse_map.get(s, s) for s in valid_symbols]
    combined_prices.attrs['stale_symbols'] = find_stale_price_symbols(market_data, requested)
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
    
    # Ensure we only use columns present in both for security value calculation
    ticker_cols = list(set(holdings.columns) & set(prices.columns))
    ticker_cols = [c for c in ticker_cols if c != 'Cash']
    
    if not ticker_cols and 'Cash' not in holdings.columns:
        return pd.Series(0.0, index=common_dates)
        
    prices = prices.ffill()
    
    # Value of securities
    if ticker_cols:
        val_df = holdings[ticker_cols] * prices[ticker_cols]
        securities_value = val_df.sum(axis=1)
    else:
        securities_value = pd.Series(0.0, index=common_dates)
    
    # Add cash (use original holdings_df where Cash is guaranteed to exist if tracked)
    if 'Cash' in holdings_df.columns:
        portfolio_value = securities_value + holdings_df.loc[common_dates, 'Cash']
    else:
        portfolio_value = securities_value
            
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
