"""Generate synthetic demo data in Fidelity's Accounts_History CSV format.

Two made-up accounts (a brokerage account and a Roth IRA) with monthly
deposits, purchases, a few sales and dividends. Trade prices are real
historical closes from Yahoo Finance so gains and losses look realistic, but
none of it is anyone's actual portfolio.

Usage:  venv/bin/python scripts/make_demo_data.py
Writes: data/demo/Accounts_History_demo.csv
"""
import csv
import os
import random
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from data_loader import unadjust_for_splits  # noqa: E402

OUT = os.path.join('data', 'demo', 'Accounts_History_demo.csv')
START, END = '2024-08-01', '2026-09-30'
BROKERAGE = ("Brokerage", "X00000001")
ROTH = ("Roth IRA", "X00000002")
NAMES = {
    'VOO': "VANGUARD S&P 500 ETF", 'AAPL': "APPLE INC", 'MSFT': "MICROSOFT CORP",
    'NVDA': "NVIDIA CORPORATION", 'GOOGL': "ALPHABET INC CLASS A", 'AMZN': "AMAZON.COM INC",
    'COST': "COSTCO WHOLESALE CORP", 'VTI': "VANGUARD TOTAL STOCK MARKET ETF",
    'AVGO': "BROADCOM INC", 'META': "META PLATFORMS INC CLASS A", 'JPM': "JPMORGAN CHASE & CO",
    'LLY': "ELI LILLY & CO", 'QQQM': "INVESCO NASDAQ 100 ETF", 'XOM': "EXXON MOBIL CORP",
}
STOCKS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'COST', 'AVGO', 'META', 'JPM', 'LLY', 'XOM']
ETFS = ['VOO', 'QQQM']
QUARTERLY_DIVIDEND = {'VOO': 1.75, 'QQQM': 0.30, 'JPM': 1.25, 'XOM': 0.95}
SEED = 7   # fixed so the demo data is reproducible
HEADER = ["Run Date", "Account", "Account Number", "Action", "Symbol", "Description", "Type",
          "Exchange Quantity", "Exchange Currency", "Currency", "Price", "Quantity", "Exchange Rate",
          "Commission", "Fees", "Accrued Interest", "Amount", "Settlement Date"]


def _prices():
    raw = yf.download(list(NAMES), start=START, end=END, progress=False, auto_adjust=False, actions=True)
    # Same convention as the app: prices as they were on the day (not split-adjusted)
    return unadjust_for_splits(raw['Close'], raw['Stock Splits']).ffill()


def _close(prices, symbol, day):
    series = prices[symbol].dropna()
    return float(series[series.index >= pd.Timestamp(day)].iloc[0])


def _row(day, account, action, symbol="", price=0.0, qty=0.0, amount=0.0):
    name = NAMES.get(symbol, "No Description")
    d = pd.Timestamp(day).strftime('%m/%d/%Y')
    return [d, account[0], account[1], action, symbol, name, "Cash", 0, "", "USD",
            round(price, 2) if price else "", round(qty, 3) if qty else "", 0, "", "", "",
            round(amount, 2), d]


def build():
    prices = _prices()
    rng = random.Random(SEED)
    rows, held = [], {s: 0.0 for s in NAMES}

    def buy(day, account, symbol, dollars):
        price = _close(prices, symbol, day)
        qty = round(dollars / price, 3)
        held[symbol] += qty if account is BROKERAGE else 0
        rows.append(_row(day, account, f"YOU BOUGHT {NAMES[symbol]} ({symbol}) (Cash)",
                         symbol, price, qty, -qty * price))

    def sell(day, symbol, fraction):
        qty = round(held[symbol] * fraction, 3)
        if qty <= 0:
            return
        held[symbol] -= qty
        price = _close(prices, symbol, day)
        rows.append(_row(day, BROKERAGE, f"YOU SOLD {NAMES[symbol]} ({symbol}) (Cash)",
                         symbol, price, -qty, qty * price))

    for day in pd.date_range(START, END, freq='BMS'):
        if rng.random() < 0.85:                       # most months, a varying deposit
            deposit = rng.choice([1500, 2000, 2500, 3000, 4000, 6000])
            rows.append(_row(day, BROKERAGE, "Electronic Funds Transfer Received (Cash)", amount=deposit))
            for k in range(rng.randint(1, 4)):        # spread it over a few purchases
                when = day + pd.offsets.BDay(rng.randint(1, 15))
                symbol = rng.choice(STOCKS + ETFS + ETFS)
                buy(when, BROKERAGE, symbol, deposit * 0.9 / (k + 2))
        rows.append(_row(day, ROTH, "Electronic Funds Transfer Received (Cash)", amount=583))
        buy(day + pd.offsets.BDay(2), ROTH, 'VTI', 575)
        if rng.random() < 0.55:                       # occasional trim or exit
            candidates = [s for s in STOCKS if held[s] > 0]
            if candidates:
                sell(day + pd.offsets.BDay(rng.randint(3, 18)), rng.choice(candidates),
                     rng.choice([0.25, 0.5, 1.0]))
        if day.month in (3, 6, 9, 12):
            for symbol, per_share in QUARTERLY_DIVIDEND.items():
                if held[symbol] > 0:
                    rows.append(_row(day + pd.offsets.BDay(18), BROKERAGE,
                                     f"DIVIDEND RECEIVED {NAMES[symbol]} ({symbol}) (Cash)",
                                     symbol, amount=held[symbol] * per_share))
    rows.sort(key=lambda r: pd.Timestamp(r[0]), reverse=True)   # newest first, like Fidelity
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == '__main__':
    build()
