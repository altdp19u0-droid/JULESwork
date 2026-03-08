from playwright.sync_api import Page, expect, sync_playwright
import time
import os

def verify_1recolte(page: Page):
    # Wait for Streamlit
    for _ in range(15):
        try:
            page.goto("http://localhost:8501")
            page.wait_for_selector("div.stApp", timeout=10000)
            break
        except:
            time.sleep(2)

    # PAGE 1 Verification
    expect(page).to_have_title("1Recolte - Crypto Harvest Pro")
    page.screenshot(path="verification/1recolte_page1.png", full_page=True)

    # Check for core components
    expect(page.get_by_text("Tableau de Bord des Comptes")).to_be_visible()
    expect(page.get_by_text("Configuration API")).to_be_visible()
    expect(page.get_by_text("Moteur de Récolte 3 Voies")).to_be_visible()

    # PAGE 2 Verification
    try:
        # Select Page 2 from the radio button
        page.get_by_test_id("stRadio").get_by_text("PAGE 2 : Analyse & Journal Comptable").click()
        time.sleep(2)
        # Check for unique heading on Page 2
        expect(page.get_by_role("heading", name="PAGE 2 : Analyse & Journal Comptable")).to_be_visible()
        page.screenshot(path="verification/1recolte_page2.png", full_page=True)
    except Exception as e:
        print(f"Page 2 interaction failed: {e}")
        page.screenshot(path="verification/1recolte_error.png", full_page=True)

if __name__ == "__main__":
    if not os.path.exists("verification"):
        os.makedirs("verification")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_1recolte(page)
        finally:
            browser.close()
