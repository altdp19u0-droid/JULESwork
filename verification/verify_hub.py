from playwright.sync_api import sync_playwright
import time

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto("http://localhost:8501", timeout=60000)
            time.sleep(5)
            page.screenshot(path="verification/hub_home.png")

            # Click on navigation
            page.get_by_test_id("stSidebar").get_by_test_id("stSelectbox").click()
            time.sleep(1)

            # Select Harvest
            page.get_by_text("Step 1: Harvest").first.click()
            time.sleep(5)
            page.screenshot(path="verification/hub_harvest.png")

            # Try to run app.py standalone
            # First kill streamlit
        finally:
            browser.close()

if __name__ == "__main__":
    run_verification()
