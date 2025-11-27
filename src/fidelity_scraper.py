import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

# Configuration
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
FIDELITY_LOGIN_URL = "https://digital.fidelity.com/prgw/digital/login/full-page"
FIDELITY_ACTIVITY_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/activity"

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
            print("SUCCESS: Data downloaded.")
            
        except Exception as e:
            print(f"Error during download flow: {e}")
            print("If you downloaded it manually, please move it to the 'data' folder.")

        print("Closing browser in 5 seconds...")
        time.sleep(5)
        browser.close()

if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    run()
