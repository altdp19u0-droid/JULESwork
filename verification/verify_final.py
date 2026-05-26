from playwright.sync_api import sync_playwright
import time
import os

def verify_app2_fix(page):
    print("Verifying app2 fix...")
    page.goto("http://localhost:8501")
    time.sleep(15)

    # Navigation Hub
    page.locator("[data-testid='stSidebar']").get_by_text("🚀 Navigation").click()
    time.sleep(2)
    # Search for app2 specifically in the menu
    page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
    time.sleep(15)

    if "UnboundLocalError" in page.content():
        print("❌ app2 still has UnboundLocalError")
    else:
        print("✅ app2 loaded without error")
    page.screenshot(path="verification/app2_loaded_final.png")

def verify_app0_fix(page):
    print("Verifying app0 fix...")
    page.goto("http://localhost:8501")
    time.sleep(10)
    page.locator("[data-testid='stSidebar']").get_by_text("🚀 Navigation").click()
    time.sleep(2)
    page.get_by_text("🏦 Step 0: Registre Manuel (app0)").click()
    time.sleep(10)
    print("✅ app0 loaded")
    page.screenshot(path="verification/app0_loaded_final.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_app2_fix(page)
            verify_app0_fix(page)
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()
