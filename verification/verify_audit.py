from playwright.sync_api import sync_playwright
import time
import os

def final_verification_audit():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1600})
        page = context.new_page()

        try:
            print("Navigating to app2 for Audit tab check...")
            page.goto("http://localhost:8501")
            time.sleep(3)
            page.get_by_label("🚀 Navigation").click()
            time.sleep(1)
            page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
            time.sleep(5)

            # Click Audit & Récupération tab
            print("Clicking Audit tab...")
            page.get_by_text("🔍 Audit & Récupération").click()
            time.sleep(2)

            # Click Launch analysis
            print("Launching comparative analysis...")
            page.get_by_text("🚀 Lancer l'analyse comparative").click()
            time.sleep(5)

            page.screenshot(path="verification/audit_tab_view.png")
            print("Screenshot saved to verification/audit_tab_view.png")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    final_verification_audit()
