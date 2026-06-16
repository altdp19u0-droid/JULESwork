from playwright.sync_api import sync_playwright
import time
import os

def verify_app2_fix(page):
    print("Verifying app2 fix...")
    # Navigate to app2 via Hub
    page.goto("http://localhost:8502")
    time.sleep(15) # Wait for Streamlit to load

    # Take screenshot of Hub
    page.screenshot(path="verification/hub_initial.png")

    # Select app2 from menu
    # Using more robust selection
    page.locator("[data-testid='stSidebar']").get_by_text("🚀 Navigation").click()
    time.sleep(2)
    page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
    time.sleep(15)

    # Check if app2 loaded correctly (No UnboundLocalError)
    if "UnboundLocalError" in page.content():
        print("❌ app2 still has UnboundLocalError")
    else:
        print("✅ app2 loaded without error")

    # Take screenshot of app2
    page.screenshot(path="verification/app2_loaded.png")

def verify_app0_fix(page):
    print("Verifying app0 fix...")
    page.goto("http://localhost:8502")
    time.sleep(10)

    # Select app0 from menu
    page.locator("[data-testid='stSidebar']").get_by_text("🚀 Navigation").click()
    time.sleep(2)
    page.get_by_text("🏦 Step 0: Registre Manuel (app0)").click()
    time.sleep(10)

    # Check if app0 loaded correctly
    print("✅ app0 loaded")

    # Take screenshot of app0
    page.screenshot(path="verification/app0_loaded.png")

def verify_appPropri_fix(page):
    print("Verifying appPropri fix...")
    page.goto("http://localhost:8502")
    time.sleep(10)

    # Select appPropri from menu
    page.locator("[data-testid='stSidebar']").get_by_text("🚀 Navigation").click()
    time.sleep(2)
    page.get_by_text("👤 Step 3b: Dashboard Patrimoine (appPropri)").click()
    time.sleep(10)

    # Check if appPropri loaded correctly
    print("✅ appPropri loaded")

    # Take screenshot of appPropri
    page.screenshot(path="verification/appPropri_loaded.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_app2_fix(page)
            verify_app0_fix(page)
            verify_appPropri_fix(page)
        except Exception as e:
            print(f"Error during verification: {e}")
            page.screenshot(path="verification/error_page.png")
        finally:
            browser.close()
