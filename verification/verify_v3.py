from playwright.sync_api import sync_playwright, expect
import time

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://localhost:8501", timeout=60000)

        # Sélection de l'onglet Harvest via la sidebar
        page.get_by_test_id("stSidebar").get_by_test_id("stSelectbox").click()
        page.get_by_text("Harvest").first.click()

        # Attente et capture
        time.sleep(2)
        page.screenshot(path="verification/harvest_v3_form.png")

        browser.close()

if __name__ == "__main__":
    run_verification()
