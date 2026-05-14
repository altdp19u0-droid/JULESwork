from playwright.sync_api import sync_playwright
import time
import os

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        modules = {
            "Step 1: Harvest": "harvest",
            "Step 0: Registre Manuel": "manual",
            "Step 2: Qualification": "qual",
            "Step 3a: Calcul VGP": "vgp",
            "Step 3c: Fiscalité": "fiscal"
        }

        try:
            page.goto("http://localhost:8501", timeout=60000)
            time.sleep(5)

            for label, filename in modules.items():
                print(f"Testing {label}...")
                # Select the FIRST selectbox in the sidebar which is the Navigation
                page.get_by_test_id("stSidebar").get_by_test_id("stSelectbox").first.click()
                time.sleep(1)
                page.get_by_text(label).first.click()
                time.sleep(8)
                page.screenshot(path=f"verification/module_{filename}.png")

                # Check for errors in the page
                content = page.content()
                if "Error" in content or "Exception" in content:
                    print(f"Potential error detected in {label}")

        finally:
            browser.close()

if __name__ == "__main__":
    run_verification()
