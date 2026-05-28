import time
import json
from playwright.sync_api import sync_playwright

def run():
    try:
        with open("session.json", "r") as f:
            session_data = json.load(f)
            cookies_dict = session_data.get("cookies", {})
    except Exception as e:
        print("Could not load session.json:", e)
        return

    playwright_cookies = []
    for k, v in cookies_dict.items():
        playwright_cookies.append({
            "name": k,
            "value": v,
            "domain": ".instagram.com",
            "path": "/"
        })

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        context.add_cookies(playwright_cookies)
        page = context.new_page()

        print("Navigating to Close Friends settings...")
        page.goto("https://www.instagram.com/accounts/close_friends/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # The Close Friends UI is typically a modal. Let's look for the search input.
        try:
            print("Looking for search input...")
            search_input = page.locator('input[placeholder*="Search"], input[placeholder*="Pesquisar"]').first
            search_input.wait_for(state="visible", timeout=10000)
            
            # Test adding a user
            test_user = "instagram"
            search_input.fill(test_user)
            page.wait_for_timeout(2000)
            
            # Now we look for a checkbox or "Add" button
            # Instagram often uses a row with a generic role="button" containing the user name
            # Or an input type=checkbox
            checkboxes = page.locator('input[type="checkbox"]').all()
            if checkboxes:
                checkboxes[0].click(force=True)
                print("Clicked checkbox!")
            else:
                print("No checkbox found, trying to find 'Add' or 'Circle' button...")
                # It might be a div acting as a toggle
                # Usually it has a title or something. We can search for the user row.
                row = page.locator(f'div[role="button"]:has-text("{test_user}")').first
                if row.is_visible():
                    row.click()
                    print(f"Clicked row for {test_user}")
                else:
                    # Let's take a screenshot
                    page.screenshot(path="debug_search.png")
                    print("Screenshot taken as debug_search.png")
                    
            page.wait_for_timeout(2000)
            
            # Click "Save" or "Done" or "Concluir"
            save_btn = page.locator('div[role="button"]:has-text("Save"), div[role="button"]:has-text("Done"), div[role="button"]:has-text("Concluir"), div[role="button"]:has-text("Salvar")').first
            if save_btn.is_visible():
                save_btn.click()
                print("Clicked Save/Done!")
            else:
                page.screenshot(path="debug_save.png")
                print("Save button not found, screenshot debug_save.png")
                
            page.wait_for_timeout(3000)

        except Exception as e:
            print(f"Error interacting with UI: {e}")
            page.screenshot(path="debug_error.png")

        browser.close()

if __name__ == "__main__":
    run()
