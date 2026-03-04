from playwright.sync_api import Page, expect, sync_playwright
import time

def verify_crypto_tracker(page: Page):
    # Wait for Streamlit to be ready
    for _ in range(15):
        try:
            res = page.goto("http://localhost:8501")
            page.wait_for_selector("div.stApp", timeout=10000)
            break
        except:
            time.sleep(2)

    # Expect the title
    expect(page).to_have_title("Jules Crypto Tracker Harvest Pro")

    # Capture Screenshot of Dashboard (Harvest)
    page.screenshot(path="verification/dashboard.png", full_page=True)

    # Try to find the selectbox by its label and click it, then find the option
    # Streamlit uses div for selectboxes usually
    try:
        # Click the selectbox
        page.get_by_text("Harvest").first.click()
        time.sleep(1)
        # Select Consultation
        page.get_by_text("Consultation").first.click()
        time.sleep(2)
        page.screenshot(path="verification/consultation.png", full_page=True)

        # Select Frais & Fiscalité
        page.get_by_text("Consultation").first.click()
        time.sleep(1)
        page.get_by_text("Frais & Fiscalité").first.click()
        time.sleep(2)
        page.screenshot(path="verification/fiscalite.png", full_page=True)
    except Exception as e:
        print(f"UI interaction failed: {e}")
        # Take a screenshot anyway to see where we are
        page.screenshot(path="verification/error_state.png", full_page=True)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_crypto_tracker(page)
        finally:
            browser.close()
