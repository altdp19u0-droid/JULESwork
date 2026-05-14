from playwright.sync_api import Page, expect, sync_playwright
import time

def verify_harvest_ui(page: Page):
    # 1. Navigate to the Hub
    page.goto("http://localhost:8501")
    time.sleep(2)

    # 2. Open the selectbox by clicking
    page.get_by_label("Selected 🏠 Accueil. 🚀 Navigation").click()
    time.sleep(1)

    # 3. Select Harvest module by text
    page.get_by_text("Step 1: Harvest (app)").click()
    time.sleep(3)

    # 4. Check for the new warning message about V2 Pure in the sidebar
    # We need to ensure the sidebar is visible or scroll it
    sidebar = page.locator("[data-testid='stSidebar']")
    expect(sidebar.get_by_text("Etherscan V2 Pure")).to_be_visible()

    # 5. Screenshot of sidebar
    sidebar.screenshot(path="verification/harvest_v2_sidebar.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_harvest_ui(page)
        finally:
            browser.close()
