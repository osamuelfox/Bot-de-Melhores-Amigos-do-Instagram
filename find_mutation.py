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
        browser = p.chromium.launch(headless=False) # Headless=False so we can see what's happening
        context = browser.new_context()
        context.add_cookies(playwright_cookies)
        page = context.new_page()

        def handle_request(route, request):
            if "graphql" in request.url or "api" in request.url:
                if request.method == "POST":
                    post_data = request.post_data
                    if post_data and "besties" in post_data.lower() or "close" in post_data.lower() or "friend" in post_data.lower():
                        print(f"\n[MUTATION FOUND]")
                        print(f"URL: {request.url}")
                        print(f"Headers: {request.headers}")
                        print(f"PostData: {post_data}")
                        print("-" * 40)
            route.continue_()

        page.route("**/*", handle_request)

        print("Navigating to Close Friends settings...")
        page.goto("https://www.instagram.com/accounts/close_friends/")
        page.wait_for_timeout(5000)
        
        # Let's take a screenshot to see where we are
        page.screenshot(path="debug1.png")
        print("Taking debug1.png")

        try:
            print("Finding search input...")
            # On Instagram web settings, Close friends might be a modal or a page.
            # Usually there is an input placeholder="Search"
            page.fill("input", "a") 
            page.wait_for_timeout(3000)
            
            page.screenshot(path="debug2.png")
            print("Taking debug2.png")
            
            # Click the first checkbox or toggle that appears
            # Instagram web uses circular checkboxes (divs or svg or input)
            elements = page.locator("input[type='checkbox']").all()
            if elements:
                elements[0].click(force=True)
                print("Clicked checkbox!")
            else:
                # Try clicking any 'Add' button or circle
                buttons = page.locator("div[role='button']:has-text('Clear'), div[role='button'] circle").all()
                if buttons:
                    buttons[0].click(force=True)
                    print("Clicked a button!")
            
            page.wait_for_timeout(2000)
            
            # Click Save/Done if it exists
            done = page.locator("div[role='button']:has-text('Done'), div[role='button']:has-text('Save')").all()
            if done:
                done[0].click(force=True)
                print("Clicked Done/Save!")
                
            page.wait_for_timeout(4000)
        except Exception as e:
            print("UI Error:", e)

        browser.close()

if __name__ == "__main__":
    run()
