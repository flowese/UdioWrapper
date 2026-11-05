"""
hCaptcha auto-solver and challenge detection for UdioWrapper.

Resolves issue #7: 500 Server Error - Auto Solve hcaptcha.
When Udio encounters an automated request on /api/generate-proxy, its backend
enforces an hCaptcha challenge. When missing, the endpoint responds with
HTTP 500 Server Error (Internal Server Error) or 403 Forbidden.

This module provides detection and integration with popular CAPTCHA solving
services (2captcha and Capsolver), as well as custom user callbacks.
"""

import os
import time

UDIO_HCAPTCHA_SITEKEY = "2945592b-1928-43a9-8473-7e7fed3d752e"
UDIO_SITE_URL = "https://www.udio.com"


class HCaptchaSolver:
    """Helper to automatically solve invisible hCaptcha using 2captcha or Capsolver."""

    def __init__(self, api_key=None, service=None, sitekey=None, site_url=None):
        self.sitekey = sitekey or UDIO_HCAPTCHA_SITEKEY
        self.site_url = site_url or UDIO_SITE_URL
        self.api_key = (
            api_key
            or os.getenv("CAPTCHA_API_KEY")
            or os.getenv("CAPSOLVER_API_KEY")
            or os.getenv("TWOCAPTCHA_API_KEY")
        )
        self.service = service or (
            "capsolver" if os.getenv("CAPSOLVER_API_KEY") else "2captcha"
        )
        self._cache = None

    def clear_cache(self):
        """Invalidate the cached captcha token."""
        self._cache = None

    def get_token(self, force=False):
        """
        Solve and return a fresh hCaptcha token, or return cached token if valid.
        Returns None if no API key is configured or solving fails.
        """
        if self._cache and not force:
            return self._cache

        if not self.api_key:
            return None

        token = None
        try:
            if self.service.lower() == "capsolver":
                token = self._solve_capsolver()
            else:
                token = self._solve_2captcha()
        except Exception as exc:
            print(f"[UdioWrapper] hCaptcha solver error ({self.service}): {exc}")
            return None

        if token:
            self._cache = token
        return token

    def _solve_2captcha(self):
        import requests

        submit_url = "https://2captcha.com/in.php"
        payload = {
            "key": self.api_key,
            "method": "hcaptcha",
            "sitekey": self.sitekey,
            "pageurl": self.site_url,
            "json": 1,
        }
        resp = requests.post(submit_url, data=payload, timeout=30)
        res_data = resp.json() if resp.status_code == 200 else {}
        if res_data.get("status") != 1:
            print(f"[UdioWrapper] 2captcha submission failed: {resp.text[:200]}")
            return None

        task_id = res_data.get("request")
        result_url = "https://2captcha.com/res.php"
        for _ in range(30):
            time.sleep(4)
            res = requests.get(
                result_url,
                params={"key": self.api_key, "action": "get", "id": task_id, "json": 1},
                timeout=30,
            )
            r_json = res.json() if res.status_code == 200 else {}
            if r_json.get("status") == 1:
                return r_json.get("request")
            if r_json.get("request") == "CAPCHA_NOT_READY":
                continue
            print(f"[UdioWrapper] 2captcha error: {r_json.get('request')}")
            return None
        return None

    def _solve_capsolver(self):
        import requests

        create_url = "https://api.capsolver.com/createTask"
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": self.site_url,
                "websiteKey": self.sitekey,
            },
        }
        resp = requests.post(create_url, json=payload, timeout=30)
        task_id = resp.json().get("taskId") if resp.status_code == 200 else None
        if not task_id:
            print(f"[UdioWrapper] Capsolver createTask failed: {resp.text[:200]}")
            return None

        result_url = "https://api.capsolver.com/getTaskResult"
        for _ in range(30):
            time.sleep(3)
            res = requests.post(
                result_url,
                json={"clientKey": self.api_key, "taskId": task_id},
                timeout=30,
            )
            res_data = res.json() if res.status_code == 200 else {}
            status = res_data.get("status")
            if status == "ready":
                return res_data.get("solution", {}).get("gRecaptchaResponse")
            if status == "failed":
                print(f"[UdioWrapper] Capsolver solve failed: {res_data}")
                return None
        return None


def is_hcaptcha_challenge(response):
    """
    Check if an HTTP response corresponds to a captcha/bot challenge on Udio.
    Udio's generate-proxy endpoint returns HTTP 500 (or sometimes 403) when hCaptcha is missing.
    """
    if response is None:
        return False

    status = getattr(response, "status_code", None)
    if status in (403, 429):
        return True

    url = getattr(response, "url", "") or ""
    # Issue #7: Udio returns 500 on generate-proxy when captcha is required
    if status == 500 and "generate-proxy" in url:
        return True

    try:
        text = response.text.lower() if hasattr(response, "text") else ""
        if any(term in text for term in ("captcha", "hcaptcha", "challenge", "cf-mitigated", "bot detection")):
            return True
    except Exception:
        pass

    return False
