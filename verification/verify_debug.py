from playwright.sync_api import sync_playwright
import time
import os

def verify_all(page):
    print("Direct verification...")
    page.goto("http://localhost:8501")
    time.sleep(20)

    # Take screenshot of Hub to see labels
    page.screenshot(path="verification/hub_debug.png")

    # Try clicking the nav selectbox by testid
    page.locator("[data-testid='stSelectbox']").first.click()
    time.sleep(2)
    page.screenshot(path="verification/hub_menu_open.png")

    # Attempt to click based on what we see in the screenshot
    # Or just check page content for error strings directly in the Hub if we can force navigation

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_all(page)
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()
