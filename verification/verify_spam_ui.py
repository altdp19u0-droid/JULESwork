from playwright.sync_api import sync_playwright
import time

def verify_app2_spam_behavior(page):
    page.goto("http://localhost:8501")
    time.sleep(10)

    # 1. Switch to app2
    try:
        page.get_by_label("🚀 Navigation").click()
        time.sleep(2)
        page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
        time.sleep(10)
        page.screenshot(path="verification/app2_initial.png")

        # 2. Add an asset to Spam Blacklist
        page.get_by_text("🛑 Blacklist Spams").click()
        time.sleep(2)
        # Use a more specific locator for the input
        page.get_by_label("Ajouter Spam (Asset/CP)").fill("TESTSPAM")
        # Use exact name for the button
        page.get_by_role("button", name="Ajouter", exact=True).click()
        time.sleep(10)
        page.screenshot(path="verification/app2_after_blacklist_add.png")

        # 3. Toggle "Afficher les Spams"
        page.get_by_text("Afficher les Spams").click()
        time.sleep(5)
        page.screenshot(path="verification/app2_spams_toggled.png")

    except Exception as e:
        print(f"Verification error: {e}")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_app2_spam_behavior(page)
        finally:
            browser.close()
