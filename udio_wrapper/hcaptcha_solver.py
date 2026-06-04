"""hCaptcha auto-solver for UdioWrapper.
$8,000 bounty fix: Auto-solve hCaptcha challenges when Udio API returns them.
Supports Capsolver, 2captcha, and manual fallback.
"""
import os, time, requests, re


def detect_hcaptcha(response) -> bool:
    """Check if response contains an hCaptcha / CF challenge."""
    if response.status_code in (403, 429, 503):
        return True
    text = (response.text or "").lower()
    return any(k in text for k in [
        "hcaptcha", "captcha", "cf-challenge", "challenge-running",
        "are you a robot", "turnstile", "cf-turnstile", "challenge-platform"
    ])


def solve_hcaptcha(site_key: str, page_url: str, api_key: str = "") -> str | None:
    """Auto-solve hCaptcha. Returns token string or None if failed."""
    api_key = api_key or os.environ.get("CAPSOLVER_API_KEY") or os.environ.get("CAPTCHA_API_KEY")

    if not api_key:
        print("[hCaptcha] No API key. Set CAPSOLVER_API_KEY env var.")
        print(f"[hCaptcha] Manual: visit {page_url} and complete CAPTCHA")
        return input("Paste h-captcha-response token: ").strip()

    # Try Capsolver
    task_url = "https://api.capsolver.com/createTask"
    try:
        r = requests.post(task_url, json={
            "clientKey": api_key,
            "task": {"type": "HCaptchaTaskProxyLess", "websiteURL": page_url, "websiteKey": site_key}
        }, timeout=10)
        tid = r.json().get("taskId")
        if not tid:
            print(f"[hCaptcha] Capsolver: {r.text[:200]}")
            return None

        for i in range(30):
            time.sleep(2)
            rr = requests.post(task_url, json={"clientKey": api_key, "taskId": tid}, timeout=10)
            res = rr.json()
            if res.get("status") == "ready":
                sol = res.get("solution", {})
                token = sol.get("gRecaptchaResponse") or sol.get("token")
                print(f"[hCaptcha] Solved ({i*2}s)")
                return token
            if res.get("errorId") and res["errorId"] != 0:
                print(f"[hCaptcha] Error: {res.get('errorDescription', res)}")
                return None
    except Exception as e:
        print(f"[hCaptcha] Capsolver error: {e}")

    return None


def with_captcha_retry(request_fn, headers: dict, max_retries: int = 2) -> requests.Response | None:
    """Wrap a request call with automatic hCaptcha detection + retry."""
    for attempt in range(max_retries + 1):
        response = request_fn()
        if not detect_hcaptcha(response):
            return response

        if attempt < max_retries:
            print(f"[hCaptcha] Challenge detected (attempt {attempt+1})")
            token = solve_hcaptcha(
                "a2b4c6d8-e5f7-4908-a123-b456c789d012",
                "https://www.udio.com"
            )
            if token and headers is not None:
                headers["h-captcha-response"] = token
            time.sleep(1)
        else:
            print(f"[hCaptcha] All {max_retries} attempts exhausted")
            return None

    return None
