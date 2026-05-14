from playwright.sync_api import Page, expect, sync_playwright
import time

def verify_ui_restoration(page: Page):
    page.goto("http://localhost:8501")
    time.sleep(2)

    # 1. Switch to Harvest
    page.get_by_label("Selected 🏠 Accueil. 🚀 Navigation").click()
    page.get_by_text("Step 1: Harvest (app)").click()
    time.sleep(3)

    # 2. Check for Portfolio section text (even if empty)
    expect(page.get_by_role("button", name="🚀 Lancer la Récolte Totale")).to_be_visible()

    # 3. Take screenshot
    page.screenshot(path="verification/harvest_v75_restored.png", full_page=True)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_ui_restoration(page)
        finally:
            browser.close()
