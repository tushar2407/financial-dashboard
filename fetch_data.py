import sys
import os

# Add src to path
sys.path.append(os.path.abspath('src'))

from fidelity_scraper import run_scraper, get_latest_transaction_date
from datetime import datetime, timedelta

def main():
    print("=== Fidelity Data Fetcher ===")
    
    # Check current state
    latest_date = get_latest_transaction_date()
    start_date = latest_date + timedelta(days=1)
    end_date = datetime.now()
    
    print(f"Latest transaction in database: {latest_date.strftime('%m/%d/%Y')}")
    print(f"I will fetch data from {start_date.strftime('%m/%d/%Y')} to {end_date.strftime('%m/%d/%Y')}")
    
    confirm = input("Proceed? (y/n): ")
    if confirm.lower() == 'y':
        try:
            run_scraper(start_date, end_date)
            print("\nFetch complete!")
            print("You can now refresh the dashboard.")
        except Exception as e:
            print(f"\nAn error occurred during fetching: {e}")
    else:
        print("Cancelled.")

if __name__ == "__main__":
    main()
