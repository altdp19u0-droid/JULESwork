from playwright.sync_api import sync_playwright
import time

def verify_app2_visibility():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()

        try:
            print("Navigating to Hub...")
            page.goto("http://localhost:8503")
            time.sleep(5)

            # Select Step 2: Qualification
            print("Switching to app2...")
            # Streamlit selectbox is a combobox
            page.get_by_label("🚀 Navigation").click()
            time.sleep(1)
            page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
            time.sleep(10)

            # Screenshot of Qualification table
            print("Capturing app2 view...")
            page.screenshot(path="verification/app2_visibility.png")

            # Check for Toggle Spams
            print("Checking Toggle Spams...")
            toggle = page.get_by_text("Afficher les Spams")
            if toggle.is_visible():
                toggle.click()
                time.sleep(3)
                page.screenshot(path="verification/app2_with_spams.png")
            else:
                print("Toggle not found")

            # Check for delete popover button
            print("Checking deletion popover...")
            popover_btn = page.get_by_text("🗑️ Supprimer / Restaurer")
            if popover_btn.is_visible():
                popover_btn.click()
                time.sleep(2)
                page.screenshot(path="verification/app2_delete_popover.png")
            else:
                print("Popover button not found")

        except Exception as e:
            print(f"Error during verification: {e}")
            page.screenshot(path="verification/error_screenshot.png")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_app2_visibility()
