# Portfolio

A self-hosted dashboard for Fidelity accounts. It downloads your transaction
history, rebuilds every position from it, and shows performance, allocation,
trading activity and tax figures in one place. Everything runs locally; your
data never leaves your machine.

![Portfolio overview (demo data)](assets/screenshot.png)

*Screenshot uses the bundled synthetic demo data.*

## What it shows

**Overview**
- Portfolio value, net invested and total P&L, split into realized,
  unrealized and dividends
- Personal return (XIRR) and portfolio return (TWR)
- Your portfolio against the same deposits invested in a benchmark (VOO by
  default), over 1D, 5D, 1M, 6M, 1Y, 5Y or all time
- Returns by calendar year

**Allocation**
- Cash against your target, concentration in the top five positions, and
  positions under 1%
- A sector map of your holdings
- Holdings table with your own categories

**Activity**
- Trades per month, new money per month, share of sales at a profit, and
  median holding period
- Biggest realized gains and losses by stock
- Closed trades, filterable by year and searchable

**Taxes**
- Short- and long-term gains, dividends and foreign tax withheld per tax year
  (taxable accounts only)
- Profit by stock, realized and unrealized, by holding period, with the last
  sale price, today's price, and when your next shares turn long-term

All accounts in the export are discovered automatically. Retirement accounts
(401k, IRA, BrokerageLink) are kept apart from taxable ones, and money moved
between your own accounts is not counted as new money.

## Setup

Requires Python 3.11+ and Google Chrome.

```bash
git clone https://github.com/tushar2407/financial-dashboard.git
cd financial-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Try it with demo data

```bash
python src/app.py --demo
```

Open http://127.0.0.1:8050. Demo mode reads only `data/demo/`, a synthetic
history for two made-up accounts (`scripts/make_demo_data.py` regenerates it),
and never contacts Fidelity.

## Use it with your Fidelity accounts

```bash
python src/app.py
```

If your data hasn't been fetched today, a Chrome window opens on Fidelity's
login page first. Sign in and complete MFA; the app downloads your activity
history into `data/` and then starts. Press Ctrl+C during the fetch to start
with the data you already have, or run `python src/app.py --no-fetch` to skip
it. `python fetch_data.py` runs the fetch on its own.

Optional settings live in `data/goals.json`:

```json
{ "cash_target": 0.10, "benchmark": "VOO" }
```

## Privacy

`data/` (your exports, settings and caches) and `.fidelity_session/` (the
saved browser login) are git-ignored. Only the synthetic files in
`data/demo/` are part of the repository.

## How the numbers are computed

- **Positions and cost basis** are rebuilt from the transaction history.
  Sales are matched to purchases first-in, first-out within each account,
  Fidelity's default.
- **Prices** come from Yahoo Finance. They are not split-adjusted, so they
  line up with the share counts Fidelity recorded at the time. If a holding
  has no recent market price, the app says so instead of silently valuing it
  at an old trade price.
- **XIRR** is the annualized return on your actual cash flows. **TWR** chains
  daily returns, so the size and timing of deposits doesn't affect it.
- **Tax figures** are estimates: no wash-sale adjustments, and ESPP cost basis
  is the purchase price. Your 1099 is authoritative.

## Development

```bash
for t in tests/test_*.py; do python "$t"; done
```

The code is in `src/`:
- **Data:** `data_loader.py` (parsing and prices), `metrics.py` (cost basis
  and returns), `insights.py` (derived facts)
- **UI:** `layout.py`, `views.py`, `components.py`, `charts.py`,
  `formatting.py`
- **App:** `app.py` (wiring and callbacks)
