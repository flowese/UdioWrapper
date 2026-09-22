"""
hCaptcha auto-solver for UdioWrapper.

Solves issue #7 - 500 Server Error caused by hCaptcha challenges.

Automatically detects hCaptcha failures from Udio's API,
extracts the site key dynamically, and solves via:
1. Capsolver (CAPSOLVER_API_KEY env var)
2. 2captcha (CAPTCHA_API_KEY env var)
3. Manual (paste token from browser)

Usage:
from .hcaptcha_solver import HCaptchaSolver
solver = HCaptchaSolver()
token = solver.get_token()
"""

import os
import re
import time
import requests


class HCaptchaSolver:
    """
    Handles hCaptcha solving for Udio API requests.
    Caches tokens and site keys to minimize API calls.
    """

    UDIO_URL = "https://www.udio.com"
    # Known Udio hCaptcha sitekey (fallback)
    FALLBACK_SITEKEY = "4c672d35-0701-42b2-88c3-78380b0db560"

    def __init__(self):
        self._token_cache = None
        self._token_ttl = 0
        self._sitekey_cache = None
        self._sitekey_ttl = 0
        self._cache_ttl = 110  # hCaptcha tokens usually last ~120s

    def _is_cached(self, cache_val, ttl):
        """Check if a cached value is still valid."""
        return cache_val is not None and time.time() < ttl

    def get_sitekey(self):
        """Get the hCaptcha sitekey from Udio's homepage or cache."""
        if self._is_cached(self._sitekey_cache, self._sitekey_ttl):
            return self._sitekey_cache

        try:
            resp = requests.get(
                self.UDIO_URL,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                },
            )
            key = self._extract_sitekey(resp.text)
            if key:
                self._sitekey_cache = key
                self._sitekey_ttl = time.time() + 3600  # Cache for 1 hour
                print(f"[hCaptcha] Site key found: {key}")
                return key
        except Exception as e:
            print(f"[hCaptcha] Failed to fetch site key: {e}")

        # Use fallback
        print(f"[hCaptcha] Using fallback site key: {self.FALLBACK_SITEKEY}")
        self._sitekey_cache = self.FALLBACK_SITEKEY
        self._sitekey_ttl = time.time() + 3600
        return self.FALLBACK_SITEKEY

    def _extract_sitekey(self, html):
        """Extract hCaptcha sitekey from HTML using regex patterns."""
        patterns = [
            r'data-sitekey["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
            r'websiteKey["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
            r'sitekey["\']?\s*[:=]\s*["\']([a-f0-9-]{20,})["\']',
            r'hcaptcha.*?["\']([a-f0-9-]{36})["\']',
            r'["\']([a-f0-9-]{36})["\'].*?hcaptcha',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def get_token(self, force_refresh=False):
        """
        Get a valid hCaptcha token. Returns None if solving fails.
        Uses cached token when available unless force_refresh=True.
        """
        if not force_refresh and self._is_cached(self._token_cache, self._token_ttl):
            return self._token_cache

        sitekey = self.get_sitekey()
        token = None

        # Try Capsolver first (more reliable for hCaptcha)
        api_key = os.environ.get("CAPSOLVER_API_KEY") or os.environ.get("CAPTCHA_API_KEY")
        if api_key:
            token = self._solve_via_service(sitekey, api_key)

        # Try manual input as fallback
        if not token:
            token = self._manual_input()

        if token:
            self._token_cache = token
            self._token_ttl = time.time() + self._cache_ttl

        return token

    def _solve_via_service(self, sitekey, api_key):
        """Solve captcha via Capsolver or 2captcha."""
        # Detect service type
        capsolver_key = os.environ.get("CAPSOLVER_API_KEY")
        captcha_key = os.environ.get("CAPTCHA_API_KEY")

        if capsolver_key:
            token = self._solve_capsolver(sitekey, capsolver_key)
            if token:
                return token
            # Fall through to 2captcha if capsolver failed and key available

        if captcha_key:
            token = self._solve_2captcha(sitekey, captcha_key)
            if token:
                return token

        return None

    def _solve_capsolver(self, sitekey, api_key):
        """Solve hCaptcha using Capsolver API."""
        create_url = "https://api.capsolver.com/createTask"
        result_url = "https://api.capsolver.com/getTaskResult"

        try:
            # Create task
            resp = requests.post(
                create_url,
                json={
                    "clientKey": api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyLess",
                        "websiteURL": self.UDIO_URL,
                        "websiteKey": sitekey,
                    },
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("errorId", 0) != 0:
                print(f"[hCaptcha] Capsolver create error: {data.get('errorDescription', data)}")
                return None

            task_id = data.get("taskId")
            if not task_id:
                return None

            # Poll for result
            for _ in range(60):
                time.sleep(2)
                resp = requests.post(
                    result_url,
                    json={"clientKey": api_key, "taskId": task_id},
                    timeout=10,
                )
                data = resp.json()

                if data.get("status") == "ready":
                    solution = data.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    if token:
                        print("[hCaptcha] Solved via Capsolver")
                        return token

                if data.get("errorId", 0) != 0:
                    print(f"[hCaptcha] Capsolver poll error: {data.get('errorDescription', data)}")
                    return None

            print("[hCaptcha] Capsolver timed out")
        except Exception as e:
            print(f"[hCaptcha] Capsolver exception: {e}")
        return None

    def _solve_2captcha(self, sitekey, api_key):
        """Solve hCaptcha using 2captcha API."""
        submit_url = "https://2captcha.com/in.php"
        result_url = "https://2captcha.com/res.php"

        try:
            # Submit task
            resp = requests.post(
                submit_url,
                data={
                    "key": api_key,
                    "method": "hcaptcha",
                    "sitekey": sitekey,
                    "pageurl": self.UDIO_URL,
                    "json": 1,
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("status") != 1:
                print(f"[hCaptcha] 2captcha submit error: {data}")
                return None

            captcha_id = data.get("request")
            if not captcha_id or captcha_id.startswith("ERROR"):
                print(f"[hCaptcha] 2captcha error: {data.get('request')}")
                return None

            # Poll for result
            for _ in range(60):
                time.sleep(5)
                resp = requests.get(
                    result_url,
                    params={
                        "key": api_key,
                        "action": "get",
                        "id": captcha_id,
                        "json": 1,
                    },
                    timeout=10,
                )
                data = resp.json()

                if data.get("status") == 1:
                    token = data.get("request")
                    if token:
                        print("[hCaptcha] Solved via 2captcha")
                        return token

                if data.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                    print("[hCaptcha] 2captcha: captcha unsolvable")
                    return None

            print("[hCaptcha] 2captcha timed out")
        except Exception as e:
            print(f"[hCaptcha] 2captcha exception: {e}")
        return None

    def _manual_input(self):
        """Prompt user to manually solve captcha and paste token."""
        print()
        print("=" * 60)
        print("[hCaptcha] No CAPSOLVER_API_KEY or CAPTCHA_API_KEY set.")
        print("[hCaptcha] To auto-solve, set one of these environment variables:")
        print(" export CAPSOLVER_API_KEY=your_key_here")
        print(" export CAPTCHA_API_KEY=your_key_here")
        print()
        print("[hCaptcha] Manual: Visit https://www.udio.com in your browser,")
        print(" solve the captcha, then:")
        print(" 1. Open DevTools (F12) -> Network tab")
        print(" 2. Find a request to udio.com/api/")
        print(" 3. Look for 'h-captcha-response' in request headers")
        print(" 4. Copy the token value")
        print("=" * 60)
        try:
            token = input("Paste hCaptcha token (or Enter to skip): ").strip()
            if token:
                print("[hCaptcha] Manual token accepted")
                return token
        except (EOFError, KeyboardInterrupt):
            pass
        return None

    def clear_cache(self):
        """Clear cached tokens to force a fresh solve."""
        self._token_cache = None
        self._token_ttl = 0