import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Add src to path
sys.path.append(os.path.abspath('src'))

from metrics import calculate_xirr, calculate_performance_metrics

def test_simple_xirr():
    print("Running test_simple_xirr...")
    # $1000 invested, grows to $1100 in 1 year
    dates = [datetime(2023, 1, 1), datetime(2024, 1, 1)]
    values = [-1000, 1100]
    xirr = calculate_xirr(values, dates)
    print(f"XIRR: {xirr:.4f}")
    assert abs(xirr - 0.1) < 0.0001
    print("test_simple_xirr passed!")

def test_periodic_xirr():
    print("\nRunning test_periodic_xirr...")
    # Timeline:
    # 2023-01-01: Deposit 1000 (Value 1000)
    # 2023-07-01: Deposit 500 (Value 1500 + profit/loss)
    # 2024-01-01: Final Value 2000
    
    dates = pd.date_range('2023-01-01', '2024-01-01', freq='D')
    portfolio_series = pd.Series(index=dates, dtype=float)
    
    # Simple linear growth for testing
    for i, date in enumerate(dates):
        # Base value grows 10% annually
        val = 1000 * (1 + 0.1 * (i / 365))
        if date >= pd.Timestamp('2023-07-01'):
            val += 500 * (1 + 0.1 * ((date - pd.Timestamp('2023-07-01')).days / 365))
        portfolio_series[date] = val
        
    daily_cash_flows = pd.Series({
        pd.Timestamp('2023-01-01'): 1000.0,
        pd.Timestamp('2023-07-01'): 500.0
    })
    
    metrics = calculate_performance_metrics(portfolio_series, daily_cash_flows)
    print(f"Metrics: {metrics}")
    
    # Lifetime should be around 10%
    if metrics['Lifetime']:
        print(f"Lifetime XIRR: {metrics['Lifetime']:.4f}")
        assert abs(metrics['Lifetime'] - 0.1) < 0.01
        
    # 1Y should also be around 10%
    if metrics['1Y']:
        print(f"1Y XIRR: {metrics['1Y']:.4f}")
        assert abs(metrics['1Y'] - 0.1) < 0.01

    print("test_periodic_xirr passed!")

if __name__ == "__main__":
    try:
        test_simple_xirr()
        test_periodic_xirr()
        print("\nAll tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
