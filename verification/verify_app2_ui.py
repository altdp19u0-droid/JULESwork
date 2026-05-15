
from playwright.sync_api import sync_playwright, expect
import time

def verify_app2_standalone():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://localhost:8501")
        time.sleep(5)

        # Check for "Année de traitement" label in sidebar
        expect(page.get_by_text("Année de traitement")).to_be_visible()
        expect(page.get_by_text("Année de début d'activité")).to_be_visible()

        # Take screenshot
        page.screenshot(path="/home/jules/verification/app2_year_config_standalone.png", full_page=True)
        print("Screenshot taken.")

        browser.close()

if __name__ == "__main__":
    verify_app2_standalone()
