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
            # Original Fidelity exports have 2 metadata rows before the header;
            # cleaned files written by this scraper have the header on row 0.
            # Try both so either format works.
            df = pd.read_csv(f, usecols=['Run Date'])
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

MAX_CHUNK_DAYS = 90


def _build_date_chunks(start_date: datetime, end_date: datetime) -> list[tuple[datetime, datetime]]:
    """Splits a date range into chunks of at most MAX_CHUNK_DAYS days."""
    chunks = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=MAX_CHUNK_DAYS - 1), end_date)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def _download_chunk(page, chunk_start: datetime, chunk_end: datetime, first_chunk: bool) -> None:
    """Downloads a single date-range chunk from the already-open Fidelity activity page."""
    start_str = chunk_start.strftime('%m/%d/%Y')
    end_str = chunk_end.strftime('%m/%d/%Y')
    print(f"Fetching chunk: {start_str} to {end_str}")

    if not first_chunk:
        # Navigate back to reset the page UI state between chunks
        print("Navigating back to activity page for next chunk...")
        page.goto("https://digital.fidelity.com/ftgw/digital/portfolio/activity")
        time.sleep(2)

    print("Waiting for time period dropdown...")
    dropdown = page.locator("button").filter(has_text=re.compile(r"Past", re.I)).first
    dropdown.wait_for(state="visible", timeout=60000)
    dropdown.click()

    print("Switching to Custom tab...")
    custom_tab = page.locator("label[for='Custom']").first
    if not custom_tab.is_visible():
        custom_tab = page.locator("apex-kit-segment[pvd-id='Custom']").first
    custom_tab.wait_for(state="visible")
    custom_tab.click()

    def fill_date_field(input_id: str, date_value_native: str) -> None:
        field = page.locator(f"#{input_id}")
        field.wait_for(state="visible", timeout=15000)
        field.fill(date_value_native)
        field.evaluate("(el) => el.dispatchEvent(new Event('change', { bubbles: true }))")

    fill_date_field("customized-timeperiod-from-date", chunk_start.strftime('%Y-%m-%d'))
    fill_date_field("customized-timeperiod-to-date", chunk_end.strftime('%Y-%m-%d'))

    print("Applying filters...")
    apply_btn = page.locator("button:has-text('Apply')").first
    apply_btn.wait_for(state="visible")
    apply_btn.click()
    time.sleep(3)

    print("Opening Download menu...")
    download_btn = page.locator("button[aria-label='Download']").first
    if not download_btn.is_visible():
        download_btn = page.locator(".activity-list--header-icon-download").first
    if not download_btn.is_visible():
        download_btn = page.locator("button:has(.icon-download)").first
    download_btn.wait_for(state="visible")
    download_btn.click()

    print("Starting CSV download...")
    with page.expect_download() as download_info:
        page.locator("button, a").filter(has_text="Download as CSV").first.click()

    download = download_info.value
    raw_filename = f"Accounts_History_{chunk_start.strftime('%Y%m%d')}_{chunk_end.strftime('%Y%m%d')}_raw.csv"
    temp_path = os.path.join(DATA_DIR, raw_filename)
    download.save_as(temp_path)
    print(f"Downloaded raw CSV to {temp_path}")

    final_filename = f"Accounts_History ({chunk_start.strftime('%m%d%Y')} - {chunk_end.strftime('%m%d%Y')}).csv"
    final_path = os.path.join(DATA_DIR, final_filename)
    clean_fidelity_csv(temp_path, final_path)
    os.remove(temp_path)
    print(f"Cleaned and saved to {final_path}")


def run_scraper(start_date=None, end_date=None):
    if not start_date:
        latest = get_latest_transaction_date()
        start_date = latest + timedelta(days=1)

    if not end_date:
        end_date = datetime.now()

    chunks = _build_date_chunks(start_date, end_date)
    print(f"Fetching data from {start_date.strftime('%m/%d/%Y')} to {end_date.strftime('%m/%d/%Y')} "
          f"({len(chunks)} chunk(s) of up to {MAX_CHUNK_DAYS} days each)")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            slow_mo=500
        )
        page = context.new_page()

        page.goto("https://digital.fidelity.com/ftgw/digital/portfolio/activity")

        if "login" in page.url.lower() or page.locator("input#userId").is_visible():
            print("Please log in and complete MFA in the browser window...")
            page.wait_for_url("**/portfolio/activity**", timeout=0)

        print("Logged in. Starting chunk downloads...")

        for i, (chunk_start, chunk_end) in enumerate(chunks):
            _download_chunk(page, chunk_start, chunk_end, first_chunk=(i == 0))

        context.close()

if __name__ == "__main__":
    run_scraper()
