import os
import json
from playwright.sync_api import sync_playwright

def find_close_friends_endpoint():
    # Load cookies from session.json
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
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(playwright_cookies)
        page = context.new_page()

        # Intercept network requests
        def handle_request(route, request):
            if "graphql" in request.url or "api" in request.url:
                if request.method == "POST":
                    print(f"POST {request.url}")
                    print(f"Headers: {request.headers}")
                    print(f"PostData: {request.post_data}")
                    print("-" * 40)
            route.continue_()

        page.route("**/*", handle_request)

        print("Navigating to Instagram Close Friends settings...")
        page.goto("https://www.instagram.com/accounts/close_friends/")
        page.wait_for_timeout(5000)

        # Let's search for someone and add them
        print("Trying to type in search box...")
        try:
            page.fill("input[placeholder='Search']", "zuck")
            page.wait_for_timeout(3000)
            print("Clicking first result checkbox...")
            page.click("input[type='checkbox']")
            page.wait_for_timeout(1000)
            print("Clicking Done/Save...")
            page.click("div[role='button']:has-text('Done')")
            page.wait_for_timeout(4000)
        except Exception as e:
            print("UI interaction failed:", e)

        browser.close()

if __name__ == "__main__":
    find_close_friends_endpoint()
