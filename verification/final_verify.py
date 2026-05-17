from playwright.sync_api import sync_playwright
import time
import os

def final_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1600})
        page = context.new_page()

        try:
            print("Navigating to app2 for sanctuarization...")
            page.goto("http://localhost:8503")
            time.sleep(3)
            page.get_by_label("🚀 Navigation").click()
            time.sleep(1)
            page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
            time.sleep(5)

            # Select 2023
            print("Selecting Year 2023...")
            year_input = page.get_by_label("Année de traitement d'activité")
            year_input.fill("2023")
            year_input.press("Enter")
            time.sleep(5)

            # Sync
            print("Clicking Sync...")
            page.get_by_text("Sync / Fusion").click()
            time.sleep(8)

            # Sanctuarize & Generate CLEAN
            print("Clicking Sanctuarize & Generate CLEAN...")
            btn = page.get_by_text("💾 Sanctuariser & Générer Journal Propre (CLEAN)")
            if btn.is_visible():
                btn.click()
                time.sleep(5)
                page.screenshot(path="verification/final_app2_sanctuary.png")
            else:
                print("Sanctuarization button not found!")
                page.screenshot(path="verification/error_final.png")

            # Verify file creation on disk
            clean_file = "sanctuarisation/2023/qualified_journal_CLEAN_2023.csv"
            if os.path.exists(clean_file):
                print(f"✅ Success: {clean_file} generated.")
            else:
                print(f"❌ Error: {clean_file} not found.")

            # Test Downstream: Switch to Dashboard (appPropri)
            print("Switching to Dashboard (appPropri)...")
            page.get_by_label("🚀 Navigation").click()
            time.sleep(1)
            page.get_by_text("👤 Step 3b: Dashboard Patrimoine (appPropri)").click()
            time.sleep(8)
            page.screenshot(path="verification/final_dashboard_view.png")

        except Exception as e:
            print(f"Error during final verification: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    final_verification()
