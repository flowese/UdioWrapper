"""Request failures exposed by the wrapper, without response-body logging."""

import json
from html.parser import HTMLParser

import requests


class UdioHTTPError(requests.HTTPError):
    """An unsuccessful HTTP response from Udio."""


class UdioAuthenticationError(UdioHTTPError):
    """Udio rejected the request's authentication."""


class UdioChallengeError(UdioHTTPError):
    """Udio explicitly requested human verification."""


class _ChallengePageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_challenge = False

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "class" and value and "h-captcha" in value.split():
                self.has_challenge = True


def _is_challenge_response(response):
    # Inspect a small prefix only. A generic 403/500, or the word "captcha"
    # inside a user's prompt, is not evidence of a verification challenge.
    prefix = response.content[:8192].decode("utf-8", errors="replace")
    try:
        payload = json.loads(prefix)
    except (ValueError, RecursionError):
        if not prefix.lstrip().startswith("<"):
            return False
        parser = _ChallengePageParser()
        parser.feed(prefix)
        return parser.has_challenge

    if not isinstance(payload, dict):
        return False
    codes = {
        "captcha_required",
        "hcaptcha_required",
        "human_verification_required",
        "captcha_verification_required",
    }
    fields = [payload]
    if isinstance(payload.get("error"), dict):
        fields.append(payload["error"])
    for fields_by_name in fields:
        for name in ("error", "code", "error_code"):
            value = fields_by_name.get(name)
            if isinstance(value, str) and value.strip().lower() in codes:
                return True
    return False


def raise_for_udio_error(response):
    """Keep the response available to callers; omit its contents from messages."""
    if _is_challenge_response(response):
        raise UdioChallengeError(
            "Udio requires human verification. Open Udio in your normal browser "
            "and complete the verification there. This wrapper cannot complete "
            "the challenge; browser verification may not enable API access.",
            response=response,
        )
    if response.status_code == 401:
        raise UdioAuthenticationError(
            "Udio rejected authentication (HTTP 401). Sign in to Udio in your "
            "normal browser and review your authentication configuration.",
            response=response,
        )
    if 400 <= response.status_code < 600:
        raise UdioHTTPError(
            "Udio returned HTTP {}. A status code alone does not identify a "
            "CAPTCHA challenge. Check the service in your normal browser before "
            "submitting another generation request.".format(response.status_code),
            response=response,
        )
