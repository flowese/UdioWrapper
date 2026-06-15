"""HCaptcha solver for UdioWrapper"""
import time
import requests
from typing import Optional


class HCaptchaSolver:
    """Solve hcaptcha using 2captcha API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.site_key = "a5c0acb9-4dd7-406d-83b0-a275583e15c1"
        self.page_url = "https://www.udio.com"

    def solve(self, timeout: int = 120) -> Optional[str]:
        """Solve captcha, return token or None"""
        try:
            resp = requests.post(
                "http://2captcha.com/in.php",
                data={
                    "key": self.api_key,
                    "method": "hcaptcha",
                    "sitekey": self.site_key,
                    "pageurl": self.page_url,
                    "json": 1,
                },
                timeout=30,
            )
            result = resp.json()
            if result.get("status") != 1:
                print(f"[Captcha] Submit failed: {result}")
                return None

            captcha_id = result["request"]
            for _ in range(timeout // 5):
                time.sleep(5)
                resp = requests.get(
                    "http://2captcha.com/res.php",
                    params={
                        "key": self.api_key,
                        "action": "get",
                        "id": captcha_id,
                        "json": 1,
                    },
                    timeout=30,
                )
                result = resp.json()
                if result.get("status") == 1:
                    return result["request"]
                if result.get("request") != "CAPCHA_NOT_READY":
                    print(f"[Captcha] Error: {result}")
                    return None
            return None
        except Exception as e:
            print(f"[Captcha] Exception: {e}")
            return None
