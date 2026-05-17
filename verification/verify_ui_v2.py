from playwright.sync_api import sync_playwright
import time

def verify_app2_with_data():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1600})
        page = context.new_page()

        try:
            print("Navigating to Hub...")
            page.goto("http://localhost:8503")
            time.sleep(5)

            # Select Step 2: Qualification
            print("Switching to app2...")
            page.get_by_label("🚀 Navigation").click()
            time.sleep(1)
            page.get_by_text("⚖️ Step 2: Qualification (app2)").click()
            time.sleep(5)

            # Select Year 2023 (known to have data in sanctuarisation/2023)
            print("Selecting Year 2023...")
            year_input = page.get_by_label("Année de traitement d'activité")
            year_input.fill("2023")
            year_input.press("Enter")
            time.sleep(5)

            # Click Sync / Fusion
            print("Clicking Sync / Fusion...")
            page.get_by_text("Sync / Fusion").click()
            time.sleep(8)

            # Screenshot of Qualification table
            print("Capturing app2 view with data...")
            page.screenshot(path="verification/app2_2023_data.png")

            # Toggle Spams (scroll sidebar if needed)
            print("Checking Toggle Spams...")
            # Streamlit sidebar is usually a div with data-testid="stSidebar"
            sidebar = page.locator('[data-testid="stSidebar"]')
            toggle = page.get_by_text("Afficher les Spams")
            if toggle.is_visible():
                print("Toggle found, clicking...")
                toggle.click()
                time.sleep(3)
                page.screenshot(path="verification/app2_2023_with_spams.png")
            else:
                print("Toggle not visible, attempting to scroll sidebar...")
                sidebar.evaluate("el => el.scrollTop = 500")
                time.sleep(1)
                if toggle.is_visible():
                    toggle.click()
                    time.sleep(3)
                    page.screenshot(path="verification/app2_2023_with_spams.png")
                else:
                    print("Toggle still not found")

            # Check for delete popover button
            print("Checking deletion popover...")
            popover_btn = page.get_by_text("🗑️ Supprimer / Restaurer")
            if popover_btn.is_visible():
                popover_btn.click()
                time.sleep(2)
                page.screenshot(path="verification/app2_delete_popover_content.png")
            else:
                print("Popover button not found")

        except Exception as e:
            print(f"Error during verification: {e}")
            page.screenshot(path="verification/error_screenshot_v2.png")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_app2_with_data()
