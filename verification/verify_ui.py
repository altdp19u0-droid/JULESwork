from playwright.sync_api import sync_playwright, expect
import time

def verify():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://localhost:8501")
        time.sleep(10)

        # Step 1: Force Year 2025 in Sidebar
        # We need to wait for App2 to load
        page.get_by_role("combobox", name="Navigation").click()
        time.sleep(2)
        page.get_by_text("Step 2", exact=False).click()
        time.sleep(10)

        # In Sidebar, set Year to 2025 (though it should be default now)
        # Try to find the number input for year
        try:
            page.get_by_label("Année de traitement").fill("2025")
            page.get_by_label("Année de traitement").press("Enter")
            time.sleep(5)
        except: pass

        # Click Audit Tab
        page.get_by_role("tab", name="Audit & Restauration").click()
        time.sleep(2)

        # Click Analyze
        page.get_by_role("button", name="Comparer avec le Sanctuaire").click()
        time.sleep(5)

        # Final Screenshot
        page.screenshot(path="verification/audit_final_2025.png")

        browser.close()

if __name__ == "__main__":
    verify()
