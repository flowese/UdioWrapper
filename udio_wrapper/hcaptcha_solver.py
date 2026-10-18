"""
hcaptcha_solver.py - Udio Wrapper hCaptcha solution
Automatically solve hCaptcha challenges for Udio's /generate-proxy endpoint
"""
import logging
import time
import requests
from typing import Optional

# Basic logger setup
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)


class HCaptchaSolver:
    """Handles hCaptcha token acquisition for Udio API requests."""

    # Sitekey for Udio's hCaptcha (found in Udio's frontend JS)
    HCAPTCHA_SITEKEY = "2945592b-1928-43a9-8473-7e7fed3d752e"
    PAGE_URL = "https://www.udio.com"

    def __init__(self, api_key: str = None, service: str = None):
        """
        Initialize captcha solver.

        :param api_key: API key for 2captcha or Capsolver service
        :param service: "2captcha" or "capsolver"
        """
        self.api_key = api_key
        self.service = service.lower() if service else None
        self._cached_token = None
        self._cached_expiry = 0

    def get_token(self) -> Optional[str]:
        """Get a cached hCaptcha token if available, otherwise fetch a new one."""
        current_time = time.time()

        # Return cached token if still valid (30 minute TTL)
        if self._cached_token and current_time < self._cached_expiry - 900:
            logger.debug("Returning cached hCaptcha token")
            return self._cached_token

        # Fetch fresh token
        token = self._fetch_captcha_token()
        if token:
            self._cached_token = token
            self._cached_expiry = current_time + 1800  # 30 minutes
            logger.info("Fetched new hCaptcha token")
            return token
        else:
            logger.warning("Could not obtain hCaptcha token")
            return None

    def clear_cache(self):
        """Clear cached token to force refresh on next request."""
        self._cached_token = None
        self._cached_expiry = 0
        logger.debug("hCaptcha token cache cleared")

    def _fetch_captcha_token(self) -> Optional[str]:
        """Fetch a fresh hCaptcha token from the configured service."""
        if self.service == "2captcha":
            return self._fetch_from_2captcha()
        elif self.service == "capsolver":
            return self._fetch_from_capsolver()
        else:
            logger.error(f"Unsupported hCaptcha service: {self.service}")
            return None

    def _fetch_from_2captcha(self) -> Optional[str]:
        """Fetch hCaptcha token using 2captcha API."""
        logger.info("Attempting to solve hCaptcha via 2captcha")
        if not self.api_key:
            logger.error("2captcha API key not provided")
            return None

        try:
            # Step 1: Submit the captcha to 2captcha
            submit_url = "http://2captcha.com/in.php"
            submit_data = {
                'key': self.api_key,
                'method': 'hcaptcha',
                'sitekey': self.HCAPTCHA_SITEKEY,
                'pageurl': self.PAGE_URL,
                'json': 1
            }

            logger.debug(f"Submitting hCaptcha to 2captcha: {submit_data}")
            response = requests.post(submit_url, data=submit_data, timeout=30)
            result = response.json()

            if result.get('status') != 1:
                logger.error(f"Failed to submit hCaptcha to 2captcha: {result}")
                return None

            captcha_id = result.get('request')
            logger.info(f"Submitted hCaptcha to 2captcha, ID: {captcha_id}")

            # Step 2: Poll for the solution
            result_url = "http://2captcha.com/res.php"
            start_time = time.time()
            max_wait = 120  # 2 minutes timeout

            while time.time() - start_time < max_wait:
                time.sleep(5)  # Wait 5 seconds between polls

                poll_data = {
                    'key': self.api_key,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }

                logger.debug(f"Polling 2captcha for result: {poll_data}")
                response = requests.post(result_url, data=poll_data, timeout=30)
                result = response.json()

                if result.get('status') == 1:
                    token = result.get('request')
                    logger.info(f"Successfully solved hCaptcha via 2captcha")
                    return token
                elif result.get('request') != 'CAPCHA_NOT_READY':
                    logger.error(f"Error polling 2captcha: {result}")
                    return None

            logger.error("Timed out waiting for 2captcha solution")
            return None

        except Exception as e:
            logger.error(f"Exception while solving hCaptcha via 2captcha: {e}")
            return None

    def _fetch_from_capsolver(self) -> Optional[str]:
        """Fetch hCaptcha token using Capsolver API."""
        logger.info("Attempting to solve hCaptcha via Capsolver")
        if not self.api_key:
            logger.error("Capsolver API key not provided")
            return None

        try:
            # Step 1: Submit the captcha to Capsolver
            submit_url = "https://api.capsolver.com/createTask"
            submit_data = {
                "clientKey": self.api_key,
                "task": {
                    "type": "HCaptchaTaskProxyLess",
                    "websiteURL": self.PAGE_URL,
                    "websiteKey": self.HCAPTCHA_SITEKEY,
                }
            }

            logger.debug(f"Submitting hCaptcha to Capsolver: {submit_data}")
            response = requests.post(submit_url, json=submit_data, timeout=30)
            result = response.json()

            if result.get('errorId') != 0:
                logger.error(f"Failed to submit hCaptcha to Capsolver: {result}")
                return None

            task_id = result.get('taskId')
            logger.info(f"Submitted hCaptcha to Capsolver, Task ID: {task_id}")

            # Step 2: Poll for the solution
            result_url = "https://api.capsolver.com/getTaskResult"
            start_time = time.time()
            max_wait = 120  # 2 minutes timeout

            while time.time() - start_time < max_wait:
                time.sleep(5)  # Wait 5 seconds between polls

                poll_data = {
                    "clientKey": self.api_key,
                    "taskId": task_id
                }

                logger.debug(f"Polling Capsolver for result: {poll_data}")
                response = requests.post(result_url, json=poll_data, timeout=30)
                result = response.json()

                if result.get('status') == "ready":
                    token = result.get('solution', {}).get('gRecaptchaResponse')
                    if token:
                        logger.info(f"Successfully solved hCaptcha via Capsolver")
                        return token
                    else:
                        logger.error(f"Capsolver returned ready but no token: {result}")
                        return None
                elif result.get('status') == "processing":
                    continue  # Still processing
                else:
                    logger.error(f"Error polling Capsolver: {result}")
                    return None

            logger.error("Timed out waiting for Capsolver solution")
            return None

        except Exception as e:
            logger.error(f"Exception while solving hCaptcha via Capsolver: {e}")
            return None

    def is_hcaptcha_required(self, response) -> bool:
        """Determine if a 500 response is likely hCaptcha related."""
        # Basic heuristic: check for common indicators
        indicators = [
            response.status_code == 500,
            "captcha" in (response.text or "").lower(),
            "hcaptcha" in (response.text or "").lower(),
            "challenge" in (response.text or "").lower(),
            "blocked" in (response.text or "").lower()
        ]
        return any(indicators)


def is_hcaptcha_blocked(response) -> bool:
    """Quick check if response contains hCaptcha indicators."""
    if not hasattr(response, 'text') or response.text is None:
        return False

    text = str(response.text).lower()
    return any(indicator in text for indicator in ["captcha", "hcaptcha", "challenge", "blocked"])


class CaptchaRequiredError(Exception):
    """Exception raised when hCaptcha is required for a request."""
    pass