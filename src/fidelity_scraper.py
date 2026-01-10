from playwright.sync_api import sync_playwright
import os
import re
import pandas as pd
import glob
from datetime import datetime, timedelta
import time
import shutil

# Paths
DATA_DIR = os.path.join(os.getcwd(), 'data')
USER_DATA_DIR = os.path.join(os.getcwd(), '.fidelity_session')

def get_latest_transaction_date():
    """Finds the latest transaction date from existing CSVs in the data directory."""
    files = glob.glob(os.path.join(DATA_DIR, 'Accounts_History*.csv'))
    if not files:
        return datetime(2024, 1, 1) # Default start date if no data exists
    
    dates = []
    for f in files:
        try:
            # We only need the first few rows to check 'Run Date'
            df = pd.read_csv(f, skiprows=2, usecols=['Run Date'])
            df['Run Date'] = pd.to_datetime(df['Run Date'], format='%m/%d/%Y', errors='coerce')
            max_date = df['Run Date'].max()
            if pd.notnull(max_date):
                dates.append(max_date)
        except Exception as e:
            print(f"Error reading {f}: {e}")
            
    return max(dates) if dates else datetime(2024, 1, 1)

def clean_fidelity_csv(input_path, output_path):
    """Removes the footer from the Fidelity CSV and saves it."""
    with open(input_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
    
    # Fidelity CSVs usually have 2 header lines, then the data, then a footer
    # The data usually ends when a line starts with "The data and information..." or similar
    # Or just keep lines that look like CSV data (start with a date)
    
    cleaned_lines = []
    for line in lines:
        if line.strip() == "":
            continue
        # If it starts with a date-like pattern or is part of the header
        if line.startswith('\ufeffRun Date') or line.startswith('Run Date') or line.startswith(',') or \
           (len(line) > 10 and line[2] == '/' and line[5] == '/'):
            # Check for footer signals
            if "The data and information in this report" in line or "Date downloaded" in line:
                break
            cleaned_lines.append(line)
        else:
            # If we already have some data and hit a line that doesn't fit, it might be the footer
            if cleaned_lines and len(cleaned_lines) > 5:
                # Basic heuristic: if it doesn't look like CSV rows anymore
                if ',' not in line:
                    break
            cleaned_lines.append(line)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(cleaned_lines)

def run_scraper(start_date=None, end_date=None):
    if not start_date:
        latest = get_latest_transaction_date()
        start_date = latest + timedelta(days=1)
    
    if not end_date:
        end_date = datetime.now()
        
    start_str = start_date.strftime('%m/%d/%Y')
    end_str = end_date.strftime('%m/%d/%Y')
    
    print(f"Fetching data from {start_str} to {end_str}")

    with sync_playwright() as p:
        # Using persistent context to save login state
        context = p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            slow_mo=500
        )
        page = context.new_page()
        
        # 1. Navigate to Activity & Orders
        page.goto("https://digital.fidelity.com/ftgw/digital/portfolio/activity")
        
        # Check if we need to login
        if "login" in page.url.lower() or page.locator("input#userId").is_visible():
            print("Please log in and complete MFA in the browser window...")
            page.wait_for_url("**/portfolio/activity**", timeout=0)
        
        print("Logged in. Navigating to Activity filters...")
        
        # 2. Click time period dropdown
        print("Waiting for time period dropdown...")
        # The button usually has "Past" (e.g., "Past 30 days")
        dropdown = page.locator("button").filter(has_text=re.compile(r"Past", re.I)).first
        dropdown.wait_for(state="visible", timeout=30000)
        dropdown.click()
        
        # 3. Click Custom tab
        print("Switching to Custom tab...")
        # Based on DOM: <label class="pvd-segment__label" for="Custom">
        custom_tab = page.locator("label[for='Custom']").first
        if not custom_tab.is_visible():
            # Fallback to the ID on the apex-kit-segment
            custom_tab = page.locator("apex-kit-segment[pvd-id='Custom']").first
            
        custom_tab.wait_for(state="visible")
        custom_tab.click()
        
        # 4. Fill dates
        print(f"Entering date range: {start_str} to {end_str}")
        
        # Format for native input[type=date] is YYYY-MM-DD
        start_native = start_date.strftime('%Y-%m-%d')
        end_native = end_date.strftime('%Y-%m-%d')
        
        def fill_date_field(input_id, date_value_native):
            print(f"Locating field: #{input_id}")
            field = page.locator(f"#{input_id}")
            field.wait_for(state="visible", timeout=15000)
            print(f"Found {input_id}. Entering value {date_value_native}...")
            
            # For type="date", .fill("YYYY-MM-DD") is the most reliable way in Playwright
            field.fill(date_value_native)
            # Sometimes click/blur helps register the change
            field.evaluate("(el) => el.dispatchEvent(new Event('change', { bubbles: true }))")

        try:
            # Using the IDs provided by the user
            fill_date_field("customized-timeperiod-from-date", start_native)
            fill_date_field("customized-timeperiod-to-date", end_native)
        except Exception as e:
            print(f"Error filling date fields: {e}")
            raise e
        
        # 5. Click Apply
        print("Applying filters...")
        apply_btn = page.locator("button:has-text('Apply')").first
        apply_btn.wait_for(state="visible")
        apply_btn.click()
        
        # Wait for the results to refresh
        time.sleep(3) 
        
        # 6. Click Download icon
        print("Opening Download menu...")
        # The icon is often an SVG inside a button
        download_btn = page.locator("button[aria-label='Download']").first
        if not download_btn.is_visible():
            # Try finding the icon class seen in some Fidelity versions
            download_btn = page.locator(".activity-list--header-icon-download").first
            
        if not download_btn.is_visible():
            # Last resort: find by proximity to print icon
            download_btn = page.locator("button:has(.icon-download)").first

        download_btn.wait_for(state="visible")
        download_btn.click()
        
        # 7. Click Download as CSV
        print("Starting CSV download...")
        with page.expect_download() as download_info:
            page.locator("button, a").filter(has_text="Download as CSV").first.click()
        
        download = download_info.value
        filename = f"Accounts_History_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_raw.csv"
        temp_path = os.path.join(DATA_DIR, filename)
        download.save_as(temp_path)
        
        print(f"Downloaded raw CSV to {temp_path}")
        
        # 8. Clean CSV
        final_filename = f"Accounts_History ({start_date.strftime('%m%d%Y')} - {end_date.strftime('%m%d%Y')}).csv"
        final_path = os.path.join(DATA_DIR, final_filename)
        clean_fidelity_csv(temp_path, final_path)
        
        # Remove raw file
        os.remove(temp_path)
        
        print(f"Cleaned and saved to {final_path}")
        
        context.close()

if __name__ == "__main__":
    run_scraper()
