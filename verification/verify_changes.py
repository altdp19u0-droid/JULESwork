from playwright.sync_api import Page, expect, sync_playwright
import time

def test_hub_and_app2(page: Page):
    # 1. Access Hub
    page.goto("http://localhost:8502")
    time.sleep(15)

    # 2. Take screenshot of Hub Home
    page.screenshot(path="verification/hub_home.png")

    # 3. Use search to find App 2 in the selectbox
    nav = page.get_by_label("🚀 Navigation")
    nav.click()
    time.sleep(2)
    page.keyboard.type("⚖️ Step 2")
    page.keyboard.press("Enter")
    time.sleep(15)

    # 4. Take screenshot of App 2
    page.screenshot(path="verification/app2_view.png")

    # 5. Check for "Année active"
    expect(page.get_by_text("Année active")).to_be_visible()

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            test_hub_and_app2(page)
        finally:
            browser.close()
