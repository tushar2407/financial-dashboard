import os
import time
import glob
import pandas as pd
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# Configuration
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
FIDELITY_LOGIN_URL = "https://digital.fidelity.com/prgw/digital/login/full-page"
FIDELITY_ACTIVITY_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/activity"

def get_latest_transaction_date(data_dir):
    """
    Scans existing CSV files in data_dir to find the latest transaction date.
    Returns (latest_date, filename) or (None, None) if no data found.
    """
    print(f"Scanning for existing data in {data_dir}...")
    files = glob.glob(os.path.join(data_dir, "Accounts_History*.csv"))
    if not files:
        print("No existing data files found.")
        return None, None
        
    latest_date = None
    latest_file = None
    
    for f in files:
        try:
            # Fidelity CSVs usually have 2 header rows to skip
            # We only need the date columns to find the max date
            df = pd.read_csv(f, skiprows=2, usecols=['Run Date', 'Settlement Date'], parse_dates=['Run Date', 'Settlement Date'], on_bad_lines='skip')
            
            # Prefer Settlement Date, fallback to Run Date
            if 'Settlement Date' in df.columns:
                max_date = df['Settlement Date'].max()
            elif 'Run Date' in df.columns:
                max_date = df['Run Date'].max()
            else:
                continue
                
            if pd.notna(max_date):
                if latest_date is None or max_date > latest_date:
                    latest_date = max_date
                    latest_file = f
        except Exception as e:
            print(f"Error reading {f}: {e}")
            
    if latest_date:
        print(f"Latest transaction date found: {latest_date.strftime('%m/%d/%Y')} in {os.path.basename(latest_file)}")
    else:
        print("Could not determine latest date from existing files.")
        
    return latest_date, latest_file

def merge_and_rename_data(new_file_path, data_dir, target_file=None):
    """
    Merges new data into target_file (if provided) and renames based on date range.
    """
    print(f"Processing downloaded file: {new_file_path}")
    
    try:
        # Load new data with robust parsing (similar to data_loader.py)
        # 1. Read lines to handle trailing commas
        with open(new_file_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
            
        # Skip first 2 rows if they are empty/header junk (Fidelity standard)
        if len(lines) > 2:
            lines = lines[2:]
            
        # Fix lines with trailing commas and remove footer lines
        fixed_lines = []
        for line in lines:
            # Skip footer lines (e.g., "Date downloaded 12/07/2025 7:28 pm")
            if line.strip().startswith('Date downloaded'):
                continue
            if line.rstrip().endswith(',,'):
                line = line.rstrip()[:-1] + '\n'
            fixed_lines.append(line)
            
        from io import StringIO
        new_df = pd.read_csv(StringIO(''.join(fixed_lines)), low_memory=False, on_bad_lines='skip')

        
        combined_df = new_df
        
        if target_file and os.path.exists(target_file):
            print(f"Merging into existing file: {target_file}")
            # Load target file with robust parsing too
            with open(target_file, 'r', encoding='utf-8-sig') as f:
                t_lines = f.readlines()
            if len(t_lines) > 2:
                t_lines = t_lines[2:]
            
            t_fixed_lines = []
            for line in t_lines:
                # Skip footer lines
                if line.strip().startswith('Date downloaded'):
                    continue
                if line.rstrip().endswith(',,'):
                    line = line.rstrip()[:-1] + '\n'
                t_fixed_lines.append(line)
                
            target_df = pd.read_csv(StringIO(''.join(t_fixed_lines)), low_memory=False, on_bad_lines='skip')
            
            # Concatenate
            combined_df = pd.concat([target_df, new_df], ignore_index=True)
            
            # Drop duplicates
            before_count = len(combined_df)
            combined_df = combined_df.drop_duplicates()
            print(f"Dropped {before_count - len(combined_df)} duplicate rows.")
            
        # Determine Date Range for Filename
        # We need to parse dates again to be sure
        # Assuming 'Settlement Date' or 'Run Date' exists
        date_col = 'Settlement Date' if 'Settlement Date' in combined_df.columns else 'Run Date'
        
        if date_col in combined_df.columns:
            # Convert to datetime if not already
            combined_df[date_col] = pd.to_datetime(combined_df[date_col], errors='coerce')
            
            min_date = combined_df[date_col].min()
            max_date = combined_df[date_col].max()
            
            if pd.notna(min_date) and pd.notna(max_date):
                min_str = min_date.strftime('%m%d%Y')
                max_str = max_date.strftime('%m%d%Y')
                new_filename = f"Accounts_History ({min_str}-{max_str}).csv"
            else:
                print("Could not determine date range. Using timestamp.")
                new_filename = f"Accounts_History ({datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}).csv"
        else:
             print("Date column not found. Using timestamp.")
             new_filename = f"Accounts_History ({datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}).csv"

        save_path = os.path.join(data_dir, new_filename)
        
        # Save combined data
        # Note: Fidelity CSVs have a specific header format we might be losing if we just dump to CSV.
        # But for data_loader.py, standard CSV is fine.
        # If we want to preserve the exact Fidelity format (empty rows at top), we should write them.
        
        with open(save_path, 'w') as f:
            f.write("\n\n") # Write 2 empty lines to match Fidelity format (approx)
            combined_df.to_csv(f, index=False)
            
        print(f"Saved merged data to: {save_path}")
        
        # Cleanup
        if os.path.exists(new_file_path):
            os.remove(new_file_path)
            
        if target_file and target_file != save_path and os.path.exists(target_file):
            print(f"Removing old file: {target_file}")
            os.remove(target_file)
            
        return save_path

    except Exception as e:
        print(f"Error merging data: {e}")
        return new_file_path # Return original if failed


def set_time_period(page, period_type='Recent', recent_option='Year to date', start_date=None, end_date=None):
    """
    Sets the time period filter on the Activity page.
    period_type: 'Recent' or 'Custom'
    recent_option: 'Year to date', 'Past 90 days', etc. (only if period_type='Recent')
    start_date: 'MM/DD/YYYY' (only if period_type='Custom')
    end_date: 'MM/DD/YYYY' (only if period_type='Custom')
    """
    print(f"Setting time period to: {period_type} - {recent_option if period_type == 'Recent' else f'{start_date} to {end_date}'}")
    
    try:
        # 1. Open Dropdown
        print("Waiting for time period dropdown...")
        try:
            # Wait for the button to be visible
            page.wait_for_selector("button:has-text('Past 30 days')", state="visible", timeout=10000)
            # Click the dropdown button - it shows current selection like "Past 30 days"
            dropdown_btn = page.locator("button:has-text('days')").first
            dropdown_btn.scroll_into_view_if_needed()
            dropdown_btn.click()
            print("Clicked dropdown button.")
            
            # Wait for the dropdown panel to appear
            print("Waiting for dropdown panel...")
            time.sleep(1)
            
        except Exception as e:
            print(f"Error opening dropdown: {e}")
            return False
            
        # 2. Select Tab (Recent vs Custom)
        # The tabs are radio buttons with labels, not buttons
        
        if period_type == 'Custom':
            # Click Custom label (it's a radio button label, not a button)
            print("Selecting Custom tab...")
            try:
                page.locator("label[for='Custom']").click()
                time.sleep(0.5)
            except Exception as e:
                print(f"Custom tab may already be selected: {e}")
            
            # Fill Dates
            if start_date and end_date:
                print(f"Filling custom dates: {start_date} - {end_date}")
                
                try:
                    # Fill the date fields using their IDs
                    page.locator("#customized-timeperiod-from-date").fill(start_date)
                    page.locator("#customized-timeperiod-to-date").fill(end_date)
                    time.sleep(0.5)  # Wait for Apply button to enable
                except Exception as e:
                    print(f"Error filling custom dates: {e}")
                    return False
                    
        else: # Recent
            # Click Recent label
            print("Selecting Recent tab...")
            try:
                page.locator("label[for='Recent']").click()
                time.sleep(0.5)
            except Exception as e:
                print(f"Recent tab may already be selected: {e}")
            
            # Select specific option
            # The HTML shows IDs like 'Year to date', '90', '30'
            # We can try to click the label for the radio button
            
            # Map friendly names to IDs/Values if needed, or just try text matching
            # The HTML has <label ...> ... Year to date ... </label>
            
            print(f"Selecting recent option: {recent_option}")
            try:
                # Click the radio button for the option
                # Options are like "Past 10 days", "Past 30 days", "Year to date", etc.
                page.locator(f"label:has-text('{recent_option}')").click()
            except Exception as e:
                print(f"Could not find option '{recent_option}': {e}")
                return False

        # 3. Click Apply button
        print("Clicking Apply button...")
        try:
            # The green Apply button is visible in both Recent and Custom tabs
            apply_btn = page.locator("button:has-text('Apply')").first
            apply_btn.click()
        except Exception as e:
            print(f"Error clicking Apply: {e}")
            return False
        
        # 4. Wait for reload
        print("Waiting for data to reload...")
        time.sleep(3) # Simple wait, ideally wait for a spinner to disappear
        return True

    except Exception as e:
        print(f"Error setting time period: {e}")
        return False


def run():
    with sync_playwright() as p:
        # Launch browser
        print("Launching browser...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # 1. Login
        print(f"Navigating to Login...")
        page.goto(FIDELITY_LOGIN_URL)
        
        print("\n" + "="*50)
        print("PLEASE LOG IN TO FIDELITY MANUALLY IN THE BROWSER WINDOW.")
        print("The script is waiting for you to complete the login process...")
        print("="*50 + "\n")

        # Wait for user to be logged in
        print("Waiting for login to complete...")
        try:
            page.wait_for_url("**/portfolio/**", timeout=300000)
            print("Login detected!")
        except Exception:
            print("Timed out waiting for login. Please ensure you are logged in.")

        # 2. Go to Activity Page
        print(f"Navigating to Activity Page: {FIDELITY_ACTIVITY_URL}")
        page.goto(FIDELITY_ACTIVITY_URL)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(5) 
        
        # 2.5 Set Time Period
        # Smart Fetching Logic
        latest_date, latest_file = get_latest_transaction_date(DOWNLOAD_DIR)
        
        if latest_date:
            # Calculate start date (latest + 1 day)
            start_date_obj = latest_date + timedelta(days=1)
            start_date_str = start_date_obj.strftime('%m/%d/%Y')
            end_date_str = datetime.now().strftime('%m/%d/%Y')
            
            if start_date_obj > datetime.now():
                print("Data is already up to date!")
                # Optional: return or ask user if they want to force download
                # For now, we'll just proceed with a default small range or exit?
                # Let's default to "Year to date" just in case, or maybe "Past 10 days"
                print("Defaulting to 'Year to date' to be safe.")
                set_time_period(page, period_type='Recent', recent_option='Year to date')
            else:
                print(f"Fetching missing data from {start_date_str} to {end_date_str}")
                set_time_period(page, period_type='Custom', start_date=start_date_str, end_date=end_date_str)
        else:
            print("No existing data found. Defaulting to 'Year to date'.")
            set_time_period(page, period_type='Recent', recent_option='Year to date')

        # 3. Find and Click Initial Download Button
        print("Looking for Download button...")
        download_button = None
        
        try:
            download_button = page.locator("[aria-label*='Download']").first
            if not download_button.is_visible():
                download_button = page.get_by_text("Download", exact=False).last
        except: pass

        if download_button and download_button.is_visible():
            print("Found Download button. Clicking to open options...")
            download_button.click()
            time.sleep(2) # Wait for pop-up
        else:
            print("Could not auto-click Download button. Please click it manually.")

        # 4. Handle Pop-up and Download
        print("Attempting to automate pop-up selection...")
        
        try:
            # Try to select a time range. 
            # Common labels: "Past 90 days", "Year to Date", "All available history"
            # We'll try "Year to Date" first, then "90 days" as fallback.
            
            # Look for radio buttons or labels
            range_selected = False
            for label in ["Year to Date", "Past 90 days", "All available history"]:
                try:
                    option = page.get_by_text(label, exact=False).first
                    if option.is_visible():
                        print(f"Selecting '{label}'...")
                        option.click()
                        range_selected = True
                        break
                except: pass
            
            if not range_selected:
                print("Could not find specific time range option. Using default selection.")

            # Click the final Download button in the pop-up
            # It usually says "Download" or "Download as CSV"
            # We need to be careful not to click the *first* download button again if it's still visible.
            # The pop-up button is likely the last one or inside a modal.
            
            print("Clicking final Download button...")
            
            # Setup download listener BEFORE clicking
            with page.expect_download(timeout=30000) as download_info:
                # Try to find the button inside the modal/pop-up
                # Often it's a button with type='submit' or class containing 'primary'
                # Or just text "Download" again.
                
                # We'll try clicking the last visible "Download" button that is NOT the one we clicked before?
                # Or just "Download as CSV" if that text exists.
                
                clicked = False
                try:
                    # Specific text often used in Fidelity pop-ups
                    confirm_btn = page.get_by_role("button", name="Download as CSV")
                    if confirm_btn.is_visible():
                        confirm_btn.click()
                        clicked = True
                except: pass
                
                if not clicked:
                    try:
                        # Try generic "Download" button that is visible
                        # We might need to scope it to the dialog if possible.
                        # page.locator("dialog").get_by_text("Download").click()
                        
                        # Fallback: Click the last visible button with text "Download"
                        btns = page.get_by_text("Download", exact=True).all()
                        if btns:
                            btns[-1].click()
                            clicked = True
                    except: pass
                
                if not clicked:
                    print("Could not auto-click final button. Please click 'Download' in the pop-up manually.")

            download = download_info.value
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"Accounts_History_{timestamp}.csv"
            save_path = os.path.join(DOWNLOAD_DIR, filename)
            
            print(f"Saving to {save_path}...")
            download.save_as(save_path)
            print("Download complete.")
            
            # 5. Merge and Rename
            merge_and_rename_data(save_path, DOWNLOAD_DIR, target_file=latest_file)
            print("SUCCESS: Data downloaded and processed.")
            
        except Exception as e:
            print(f"Error during download flow: {e}")
            print("If you downloaded it manually, please move it to the 'data' folder.")

        print("Closing browser in 5 seconds...")
        time.sleep(5)
        browser.close()

if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    run()
