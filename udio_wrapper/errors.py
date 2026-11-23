"""Safe request error handling and verification guidance for UdioWrapper."""

import json
from html.parser import HTMLParser
import requests


class UdioError(Exception):
    """Base exception for UdioWrapper errors."""


class UdioHTTPError(UdioError, requests.HTTPError):
    """An unsuccessful HTTP response from Udio, preserving HTTPError compatibility."""

    def __init__(self, message, response=None, request=None):
        super().__init__(message, response=response, request=request)
        if response is not None and getattr(self, "response", None) is None:
            self.response = response
        if request is not None and getattr(self, "request", None) is None:
            self.request = request
        elif response is not None and getattr(response, "request", None) is not None:
            self.request = response.request


class UdioAuthenticationError(UdioHTTPError):
    """Udio rejected the request's authentication (HTTP 401)."""


class UdioChallengeError(UdioHTTPError):
    """Udio explicitly requested human verification (e.g. CAPTCHA / hCaptcha)."""


class UdioResponseError(UdioError):
    """Udio returned an invalid, unparseable, or unexpected response body."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class _ChallengeHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_challenge = False

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "class" and value:
                classes = value.split()
                if "h-captcha" in classes or "cf-turnstile" in classes:
                    self.has_challenge = True


KNOWN_CHALLENGE_CODES = {
    "captcha_required",
    "hcaptcha_required",
    "human_verification_required",
    "captcha_verification_required",
}


def is_challenge_response(response):
    """Determine if an HTTP response explicitly requires human verification.
    
    A generic HTTP 500, 403, or 429 status code alone is NOT assumed to be a
    challenge. Only explicit challenge signatures in the response body or headers
    qualify.
    """
    if response is None:
        return False

    # Check for HTML challenge signatures (inspect only initial prefix of text)
    content = getattr(response, "content", b"")
    text_prefix = content[:8192].decode("utf-8", errors="replace").strip()
    if text_prefix.startswith("<"):
        parser = _ChallengeHTMLParser()
        parser.feed(text_prefix)
        if parser.has_challenge:
            return True

    # Check for explicit JSON challenge codes
    try:
        payload = response.json()
    except Exception:
        # Fallback to inspecting raw prefix if full JSON decode fails
        try:
            payload = json.loads(text_prefix)
        except Exception:
            return False

    if isinstance(payload, dict):
        fields = [payload]
        if isinstance(payload.get("error"), dict):
            fields.append(payload["error"])
        for d in fields:
            for key in ("error", "code", "error_code"):
                val = d.get(key)
                if isinstance(val, str) and val.strip().lower() in KNOWN_CHALLENGE_CODES:
                    return True

    return False


def raise_for_status(response):
    """Inspect the HTTP response and raise structured Udio exceptions without leaking secrets."""
    if response is None:
        raise UdioResponseError("No response received from Udio.")

    if is_challenge_response(response):
        raise UdioChallengeError(
            "Udio requires human verification. Open Udio in your standard web browser "
            "and complete the verification manually. Automated solving or bypassing of "
            "verification is not supported.",
            response=response,
        )

    if response.status_code == 401:
        raise UdioAuthenticationError(
            "Udio rejected authentication (HTTP 401). Please check your sb-api-auth-token "
            "and ensure you are signed in to Udio.",
            response=response,
        )

    if 400 <= response.status_code < 600:
        raise UdioHTTPError(
            f"Udio API request failed with HTTP {response.status_code}. "
            "A server error does not necessarily indicate a verification challenge.",
            response=response,
        )
