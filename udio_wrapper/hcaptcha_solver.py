"""
hCaptcha auto-solver for UdioWrapper.

Auto-detects hCaptcha challenges from Udio's API (500 errors),
extracts the site key dynamically, and solves via:
  1. Capsolver  (CAPSOLVER_API_KEY env var)
  2. 2captcha    (CAPTCHA_API_KEY env var)
  3. Manual      (paste a token you solved in your browser)

Usage:
    from .hcaptcha_solver import solve_hcaptcha, get_sitekey, detect_hcaptcha
"""

import os
import re
import time
import requests

_cache = {"token": None, "token_ttl": 0, "sitekey": None, "sitekey_ttl": 0}
CACHE_TTL = 300
SITEKEY_URL = "https://www.udio.com/"


def _find_sitekey_in_html(html):
    patterns = [
        r'data-sitekey["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
        r'websiteKey["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
        r'sitekey["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
        r'hcaptcha.*?key["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
        r'["\']([a-f0-9-]{36})["\'].*?hcaptcha',
        r'hcaptcha.*?([a-f0-9-]{36})',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def get_sitekey():
    now = time.time()
    if _cache["sitekey"] and now < _cache["sitekey_ttl"]:
        return _cache["sitekey"]

    try:
        resp = requests.get(SITEKEY_URL, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        html = resp.text
        key = _find_sitekey_in_html(html)
        if key:
            _cache["sitekey"] = key
            _cache["sitekey_ttl"] = now + CACHE_TTL
            print(f"[hCaptcha] Site key found: {key}")
            return key
    except Exception as exc:
        print(f"[hCaptcha] Failed to fetch site key: {exc}")

    fallback = "a2b4c6d8-e5f7-4908-a123-b456c789d012"
    print(f"[hCaptcha] Using fallback site key: {fallback}")
    _cache["sitekey"] = fallback
    _cache["sitekey_ttl"] = now + CACHE_TTL
    return fallback


def detect_hcaptcha(response):
    if response.status_code in (403, 429, 503):
        return True
    if response.status_code == 500:
        text = (response.text or "").lower().strip()
        if not text or text in ("", "{}", "[]"):
            return True
        if any(k in text for k in ["captcha", "hcaptcha", "challenge", "blocked", "denied", "rate limit"]):
            return True
    return False


def solve_hcaptcha(site_key=None, page_url="https://www.udio.com"):
    now = time.time()
    if _cache["token"] and now < _cache["token_ttl"]:
        print("[hCaptcha] Using cached token")
        return _cache["token"]

    if site_key is None:
        site_key = get_sitekey()

    api_key = os.environ.get("CAPSOLVER_API_KEY") or os.environ.get("CAPTCHA_API_KEY")

    if api_key:
        token = None
        is_2captcha = bool(os.environ.get("CAPTCHA_API_KEY")) and not bool(os.environ.get("CAPSOLVER_API_KEY"))
        if is_2captcha:
            token = _solve_via_2captcha(site_key, page_url, api_key)
        else:
            token = _solve_via_capsolver(site_key, page_url, api_key)

        if token:
            _cache["token"] = token
            _cache["token_ttl"] = now + CACHE_TTL
            return token

    print()
    print("[hCaptcha] No CAPSOLVER_API_KEY or CAPTCHA_API_KEY set. To auto-solve, set the env var.")
    print("[hCaptcha] Manual: visit https://www.udio.com, solve the captcha,")
    print("          then copy the h-captcha-response token.")
    try:
        token = input("Paste hCaptcha token (or Enter to skip): ").strip()
        if token:
            _cache["token"] = token
            _cache["token_ttl"] = now + CACHE_TTL
            return token
    except (EOFError, KeyboardInterrupt):
        pass
    return None


def _solve_via_capsolver(site_key, page_url, api_key):
    create_url = "https://api.capsolver.com/createTask"
    result_url = "https://api.capsolver.com/getTaskResult"
    try:
        resp = requests.post(create_url, json={
            "clientKey": api_key,
            "task": {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": site_key
            }
        }, timeout=15)
        result = resp.json()
        task_id = result.get("taskId")
        if not task_id:
            print(f"[hCaptcha] Capsolver error: {result.get('errorDescription', resp.text[:200])}")
            return None

        # Poll result using getTaskResult
        for _ in range(45):
            time.sleep(2)
            poll = requests.post(result_url, json={"clientKey": api_key, "taskId": task_id}, timeout=10)
            status = poll.json()
            if status.get("status") == "ready":
                sol = status.get("solution", {})
                token = sol.get("gRecaptchaResponse") or sol.get("token")
                if token:
                    print("[hCaptcha] Solved via Capsolver")
                    return token
            if status.get("errorId", 0) != 0:
                print(f"[hCaptcha] Capsolver error: {status.get('errorDescription', status)}")
                return None
        print("[hCaptcha] Capsolver timed out")
    except Exception as exc:
        print(f"[hCaptcha] Capsolver error: {exc}")
    return None


def _solve_via_2captcha(site_key, page_url, api_key):
    try:
        submit = requests.post("https://2captcha.com/in.php", data={
            "key": api_key,
            "method": "hcaptcha",
            "sitekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }, timeout=15)
        sid = submit.json().get("request")
        if not sid or sid == "ERROR_NO_SLOT_AVAILABLE":
            print(f"[hCaptcha] 2captcha error: {submit.text[:200]}")
            return None

        for _ in range(60):
            time.sleep(5)
            poll = requests.get("https://2captcha.com/res.php", params={
                "key": api_key,
                "action": "get",
                "id": sid,
                "json": 1,
            }, timeout=10)
            data = poll.json()
            if data.get("status") == 1:
                token = data.get("request")
                if token:
                    print("[hCaptcha] Solved via 2captcha")
                    return token
            if data.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                print("[hCaptcha] 2captcha: unsolvable")
                return None
        print("[hCaptcha] 2captcha timed out")
    except Exception as exc:
        print(f"[hCaptcha] 2captcha error: {exc}")
    return None


def ensure_token(site_key=None):
    return solve_hcaptcha(site_key)


def clear_cache():
    _cache["token"] = None
    _cache["token_ttl"] = 0
    _cache["sitekey"] = None
    _cache["sitekey_ttl"] = 0
