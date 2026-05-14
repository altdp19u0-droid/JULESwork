from playwright.sync_api import sync_playwright
import time

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto("http://localhost:8502", timeout=60000)
            time.sleep(5)
            page.screenshot(path="verification/standalone_app.png")
        finally:
            browser.close()

if __name__ == "__main__":
    run_verification()
