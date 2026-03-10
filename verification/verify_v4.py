from playwright.sync_api import Page, expect, sync_playwright
import time

def verify_v4(page: Page):
    # Wait for Streamlit to be ready
    page.goto("http://localhost:8501")
    page.wait_for_selector("div.stApp", timeout=20000)

    # Check Sidebar title
    expect(page.get_by_test_id("stSidebar")).to_contain_text("Jules Crypto Pro V4")

    # Expand API Key section
    api_expander = page.get_by_text("Clé API Globale")
    api_expander.click()
    time.sleep(1)

    # Take screenshot of Harvest page with API expander open
    page.screenshot(path="verification/v4_harvest.png", full_page=True)

    # Go to Settings
    page.get_by_test_id("stSidebar").get_by_test_id("stSelectbox").click()
    page.get_by_text("Settings").first.click()
    time.sleep(2)

    # Take screenshot of Settings page (Label management)
    page.screenshot(path="verification/v4_settings.png", full_page=True)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_v4(page)
        finally:
            browser.close()
