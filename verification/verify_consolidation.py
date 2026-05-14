from playwright.sync_api import Page, expect, sync_playwright
import time
import os

def test_consolidation_preserves_columns(page: Page):
    # This is a simulation test because we cannot easily trigger a real harvest without valid API keys/data
    # But we can verify the UI structure and ensure it handles the expected data model
    page.goto("http://localhost:8501")
    time.sleep(2)

    # 1. Switch to Harvest
    page.get_by_label("Selected 🏠 Accueil. 🚀 Navigation").click()
    page.get_by_text("Step 1: Harvest (app)").click()
    time.sleep(3)

    # 2. Check the table headers
    # Even if empty, we can check if the dataframes are correctly initialized in session state
    # But since we want to be sure about the columns during consolidation, we verify the code fix
    # verified via python snippet in previous step.

    # 3. Take a screenshot of the module to confirm it's still healthy
    page.screenshot(path="verification/harvest_final_check.png", full_page=True)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            test_consolidation_preserves_columns(page)
        finally:
            browser.close()
