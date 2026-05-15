
from playwright.sync_api import sync_playwright, expect
import time

def verify_cp_filter_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://localhost:8501")
        time.sleep(10)

        # Click on the Filtres expander
        # Using a more specific locator based on how Streamlit renders expanders
        page.get_by_text("Filtres").click()
        time.sleep(2)

        # Now check for Counterparty multiselect
        expect(page.get_by_text("Counterparty")).to_be_visible()

        # Take screenshot
        page.screenshot(path="/home/jules/verification/app2_cp_filter_expanded.png", full_page=True)
        print("Screenshot taken.")

        browser.close()

if __name__ == "__main__":
    verify_cp_filter_ui()
