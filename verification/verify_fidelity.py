from playwright.sync_api import Page, expect, sync_playwright
import time

def verify_harvest_fidelity(page: Page):
    page.goto("http://localhost:8501")
    time.sleep(2)

    # Switch to Harvest
    page.get_by_label("Selected 🏠 Accueil. 🚀 Navigation").click()
    page.get_by_text("Step 1: Harvest (app)").click()
    time.sleep(3)

    # Check the "Pure V2" indicator and general health
    expect(page.get_by_text("Etherscan V2 Pure")).to_be_visible()

    # Take screenshot
    page.screenshot(path="verification/harvest_fidelity_v2.png", full_page=True)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_harvest_fidelity(page)
        finally:
            browser.close()
