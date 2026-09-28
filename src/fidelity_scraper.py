from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os
import re
import pandas as pd
import glob
from datetime import datetime, timedelta
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
ACTIVITY_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/activity"
LOGIN_POLL_MS = 2000


def _build_date_chunks(start_date: datetime, end_date: datetime) -> list[tuple[datetime, datetime]]:
    """Splits a date range into chunks of at most MAX_CHUNK_DAYS days."""
    chunks = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=MAX_CHUNK_DAYS - 1), end_date)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


# NOTE: never use time.sleep() with the sync Playwright API. It blocks the event
# loop, so page.url and page state go stale (a login-wait loop never sees the
# redirect). Use page.wait_for_timeout() instead.
#
# Selectors below combine current and legacy Fidelity UI variants with .or_()
# so a single wait_for() waits for whichever one renders. Chaining
# `if not loc.is_visible()` fallbacks does not work: is_visible() never waits,
# so a slow render falls through to a selector that does not exist.

def _time_period_dropdown(page):
    return page.locator("button").filter(has_text=re.compile(r"Past", re.I)).first


def _custom_tab(page):
    return (
        page.locator("fds-segment[fds-value='custom']")
        .or_(page.locator("label[for='Custom']"))
        .or_(page.locator("apex-kit-segment[pvd-id='Custom']"))
        .or_(page.get_by_text("Custom", exact=True))
        .first
    )


def _date_input(page, input_id: str):
    return (
        page.locator(f"#{input_id}")
        .or_(page.locator(f"fds-input[fds-id='{input_id}'] input"))
        .first
    )


def _apply_button(page):
    return (
        page.locator("button[type='submit']").filter(has_text="Apply")
        .or_(page.locator("button:has-text('Apply')"))
        .first
    )


def _download_button(page):
    return (
        page.locator("button[aria-label='Download']")
        .or_(page.locator(".activity-list--header-icon-download"))
        .or_(page.locator("button:has(.icon-download)"))
        .first
    )


def _fill_date_field(page, input_id: str, date_value: datetime) -> None:
    field = _date_input(page, input_id)
    field.wait_for(state="visible", timeout=15000)
    # Native <input type="date"> requires ISO; masked text inputs expect mm/dd/yyyy
    is_native_date = field.get_attribute("type") == "date"
    field.fill(date_value.strftime('%Y-%m-%d' if is_native_date else '%m/%d/%Y'))
    field.evaluate("(el) => el.dispatchEvent(new Event('change', { bubbles: true }))")


def _download_chunk(page, chunk_start: datetime, chunk_end: datetime, first_chunk: bool) -> None:
    """Downloads a single date-range chunk from the already-open Fidelity activity page."""
    print(f"Fetching chunk: {chunk_start:%m/%d/%Y} to {chunk_end:%m/%d/%Y}")

    if not first_chunk:
        # Reload to reset the time-period button text back to "Past ..."
        page.goto(ACTIVITY_URL, wait_until="domcontentloaded")

    dropdown = _time_period_dropdown(page)
    dropdown.wait_for(state="visible", timeout=60000)
    dropdown.click()

    custom_tab = _custom_tab(page)
    custom_tab.wait_for(state="visible", timeout=15000)
    custom_tab.click()

    _fill_date_field(page, "input-from-date", chunk_start)
    _fill_date_field(page, "input-to-date", chunk_end)

    apply_btn = _apply_button(page)
    apply_btn.wait_for(state="visible", timeout=10000)
    apply_btn.click()
    page.wait_for_timeout(3000)

    download_btn = _download_button(page)
    download_btn.wait_for(state="visible", timeout=30000)
    download_btn.click()

    csv_option = page.locator("button, a").filter(has_text="Download as CSV").first
    csv_option.wait_for(state="visible", timeout=10000)
    with page.expect_download() as download_info:
        csv_option.click()

    download = download_info.value
    raw_filename = f"Accounts_History_{chunk_start:%Y%m%d}_{chunk_end:%Y%m%d}_raw.csv"
    temp_path = os.path.join(DATA_DIR, raw_filename)
    download.save_as(temp_path)

    final_filename = f"Accounts_History ({chunk_start:%m%d%Y} - {chunk_end:%m%d%Y}).csv"
    final_path = os.path.join(DATA_DIR, final_filename)
    clean_fidelity_csv(temp_path, final_path)
    os.remove(temp_path)
    print(f"Saved {final_path}")


def _url_path(page) -> str:
    # The signin URL carries the activity URL in its authredurl query param,
    # so only the path is meaningful.
    return page.url.lower().split("?")[0]


def _wait_for_login(page) -> None:
    """Blocks until the user is logged in and the activity page is usable."""
    page.goto(ACTIVITY_URL, wait_until="domcontentloaded")
    prompted = False
    while True:
        path = _url_path(page)
        if "portfolio" in path:
            if "portfolio/activity" not in path:
                page.goto(ACTIVITY_URL, wait_until="domcontentloaded")
            try:
                _time_period_dropdown(page).wait_for(state="visible", timeout=20000)
                return
            except PlaywrightTimeoutError:
                # Possibly bounced back to login (session expired); keep polling
                pass
        elif not prompted:
            print("\n" + "=" * 65)
            print("ACTION REQUIRED: Log in and complete MFA in the Chrome window.")
            print("The script will wait until you are fully logged in.")
            print("=" * 65 + "\n")
            prompted = True
        page.wait_for_timeout(LOGIN_POLL_MS)


def _save_debug_screenshot(page) -> None:
    path = os.path.join(DATA_DIR, f"scraper_failure_{datetime.now():%Y%m%d_%H%M%S}.png")
    try:
        page.screenshot(path=path, full_page=True)
        print(f"Saved failure screenshot to {path} (contains account data; delete when done)")
    except Exception as e:
        print(f"Could not save failure screenshot: {e}")


def run_scraper(start_date=None, end_date=None, reset_session=False):
    if reset_session and os.path.exists(USER_DATA_DIR):
        print(f"Resetting session directory: {USER_DATA_DIR}")
        shutil.rmtree(USER_DATA_DIR, ignore_errors=True)

    if not start_date:
        latest = get_latest_transaction_date()
        start_date = latest + timedelta(days=1)

    if not end_date:
        end_date = datetime.now()

    chunks = _build_date_chunks(start_date, end_date)
    if not chunks:
        print("Data is already up to date; nothing to fetch.")
        return
    print(f"Fetching data from {start_date:%m/%d/%Y} to {end_date:%m/%d/%Y} "
          f"({len(chunks)} chunk(s) of up to {MAX_CHUNK_DAYS} days each)")

    os.makedirs(DATA_DIR, exist_ok=True)

    launch_kwargs = {
        "headless": False,
        "slow_mo": 100,
        "accept_downloads": True,
        "ignore_default_args": ["--enable-automation"],
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if os.path.exists('/Applications/Google Chrome.app') or shutil.which('google-chrome') or shutil.which('chrome'):
        launch_kwargs["channel"] = "chrome"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, **launch_kwargs)
        # A persistent context opens with one blank tab already; reuse it
        page = context.pages[0] if context.pages else context.new_page()
        try:
            _wait_for_login(page)
            print("\nLogged in. Starting data download...")
            for i, (chunk_start, chunk_end) in enumerate(chunks):
                _download_chunk(page, chunk_start, chunk_end, first_chunk=(i == 0))
        except Exception:
            _save_debug_screenshot(page)
            raise
        finally:
            context.close()


if __name__ == "__main__":
    run_scraper()
