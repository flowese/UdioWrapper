"""
hCaptcha auto-solver for UdioWrapper.

Solves issue #7 (500 Server Error - Auto Solve hcaptcha).

Udio's /generate-proxy endpoint returns HTTP 500 when the backend cannot
verify a valid hCaptcha token. The web frontend solves the invisible
hCaptcha challenge (sitekey below) and sends the resulting token with the
request. This module reproduces that step programmatically.

It supports two popular solver services, configured via constructor args
or environment variables:

  * 2captcha  : CAPTCHA_API_KEY env var (or ``captcha_api_key`` arg)
  * Capsolver : CAPSOLVER_API_KEY env var (or ``captcha_api_key`` arg)

If no API key is configured the solver degrades gracefully: it logs a hint
and returns None, so callers can still retry the request.

The Udio hCaptcha sitekey is read from the live udio.com frontend bundle.
"""
import os
import re
import time
import requests

# Invisible hCaptcha sitekey used by https://www.udio.com (verified against
# the deployed JS bundle: /_next/static/chunks/*).
UDIO_HCAPTCHA_SITEKEY = "2945592b-1928-43a9-8473-7e7fed3d752e"
UDIO_SITE_URL = "https://www.udio.com"


class HCaptchaSolver:
    """Solve an invisible hCaptcha challenge via 2captcha or Capsolver."""

    def __init__(self, sitekey=None, site_url=None, api_key=None, service=None):
        self.sitekey = sitekey or UDIO_HCAPTCHA_SITEKEY
        self.site_url = site_url or UDIO_SITE_URL
        # Resolve API key and preferred service.
        self.api_key = api_key or os.getenv("CAPTCHA_API_KEY") or os.getenv("CAPSOLVER_API_KEY")
        self.service = service or (
            "2captcha" if os.getenv("CAPTCHA_API_KEY") else "capsolver"
        )
        self._cache = None

    def clear_cache(self):
        self._cache = None

    def get_token(self, force=False):
        """Return a fresh hCaptcha token, or None if unavailable."""
        if self._cache and not force:
            return self._cache
        if not self.api_key:
            print(
                "hCaptcha: no API key set. Set CAPTCHA_API_KEY (2captcha) or "
                "CAPSOLVER_API_KEY to enable auto-solving."
            )
            return None
        token = None
        try:
            if self.service == "2captcha":
                token = self._solve_2captcha()
            else:
                token = self._solve_capsolver()
        except Exception as exc:  # never let a solver failure kill the request
            print(f"hCaptcha: solver error: {exc}")
            return None
        if token:
            self._cache = token
        return token

    def _solve_2captcha(self):
        # Submit the challenge.
        resp = requests.post(
            "https://2captcha.com/in.php",
            data={
                "key": self.api_key,
                "method": "hcaptcha",
                "sitekey": self.sitekey,
                "pageurl": self.site_url,
            },
            timeout=30,
        )
        text = resp.text.strip()
        if not text.startswith("OK|"):
            print(f"hCaptcha: 2captcha submit failed: {text}")
            return None
        task_id = text.split("|", 1)[1]
        # Poll for the result.
        for _ in range(30):
            time.sleep(3)
            res = requests.get(
                "https://2captcha.com/res.php",
                params={"key": self.api_key, "action": "get", "id": task_id},
                timeout=30,
            ).text.strip()
            if res.startswith("OK|"):
                return res.split("|", 1)[1]
            if res == "CAPCHA_NOT_READY":
                continue
            if res.startswith("ERROR"):
                print(f"hCaptcha: 2captcha error: {res}")
                return None
        return None

    def _solve_capsolver(self):
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": self.site_url,
                "websiteKey": self.sitekey,
            },
        }
        resp = requests.post("https://api.capsolver.com/createTask", json=payload, timeout=30)
        task_id = resp.json().get("taskId")
        if not task_id:
            print(f"hCaptcha: capsolver createTask failed: {resp.text[:200]}")
            return None
        for _ in range(30):
            time.sleep(3)
            status = requests.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
                timeout=30,
            ).json()
            if status.get("status") == "ready":
                return status.get("solution", {}).get("gRecaptchaResponse")
            if status.get("status") == "failed":
                print(f"hCaptcha: capsolver failed: {status}")
                return None
        return None


def is_hcaptcha_blocked(response):
    """Heuristic: does this response indicate a missing/invalid captcha?"""
    if response is None:
        return False
    if response.status_code in (403, 500, 503):
        return True
    try:
        body = response.text.lower()
    except Exception:
        return False
    return any(k in body for k in ("captcha", "challenge", "bot"))
