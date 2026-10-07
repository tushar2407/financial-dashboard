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
}
ROTATION = ['VOO', 'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'COST']
# (date, symbol, fraction of shares held to sell)
SALES = [('2025-03-03', 'NVDA', 0.5), ('2025-11-03', 'AAPL', 0.4), ('2026-03-02', 'AMZN', 1.0),
         ('2026-08-03', 'MSFT', 0.3)]
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
    rows, held = [], {s: 0.0 for s in NAMES}
    months = pd.date_range(START, END, freq='BMS')
    for i, day in enumerate(months):
        rows.append(_row(day, BROKERAGE, "Electronic Funds Transfer Received (Cash)", amount=2000))
        rows.append(_row(day, ROTH, "Electronic Funds Transfer Received (Cash)", amount=500))
        buy_day = day + pd.offsets.BDay(2)
        symbol = ROTATION[i % len(ROTATION)]
        price = _close(prices, symbol, buy_day)
        qty = round(1900 / price, 3)
        held[symbol] += qty
        rows.append(_row(buy_day, BROKERAGE, f"YOU BOUGHT {NAMES[symbol]} ({symbol}) (Cash)",
                         symbol, price, qty, -qty * price))
        vti = _close(prices, 'VTI', buy_day)
        rows.append(_row(buy_day, ROTH, f"YOU BOUGHT {NAMES['VTI']} (VTI) (Cash)",
                         'VTI', vti, round(480 / vti, 3), -round(480 / vti, 3) * vti))
        if day.month in (3, 6, 9, 12) and held['VOO'] > 0:
            div_day = day + pd.offsets.BDay(20)
            rows.append(_row(div_day, BROKERAGE, f"DIVIDEND RECEIVED {NAMES['VOO']} (VOO) (Cash)",
                             'VOO', amount=held['VOO'] * 1.75))
        for sale_day, sym, fraction in SALES:
            if day.strftime('%Y-%m') == sale_day[:7] and held[sym] > 0:
                qty_sold = round(held[sym] * fraction, 3)
                held[sym] -= qty_sold
                price = _close(prices, sym, sale_day)
                rows.append(_row(sale_day, BROKERAGE, f"YOU SOLD {NAMES[sym]} ({sym}) (Cash)",
                                 sym, price, -qty_sold, qty_sold * price))
    rows.sort(key=lambda r: pd.Timestamp(r[0]), reverse=True)   # newest first, like Fidelity
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == '__main__':
    build()
