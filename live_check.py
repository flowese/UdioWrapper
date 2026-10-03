"""Single real POST diagnostic for Issue #7. No retries, no automation."""

import os
import sys

from udio_wrapper import UdioWrapper


def main():
    token = os.environ.get("UDIO_AUTH_TOKEN", "").strip()
    cookie_name = os.environ.get("UDIO_COOKIE_NAME", "sb-api-auth-token").strip()
    if not token:
        print("Set UDIO_AUTH_TOKEN (and optionally UDIO_COOKIE_NAME) first.")
        sys.exit(1)

    wrapper = UdioWrapper(token, cookie_name=cookie_name, max_retries=1)
    url = f"{wrapper.API_BASE_URL}/generate-proxy"
    headers = wrapper.get_headers()
    data = {"prompt": "diagnostic", "samplerOptions": {"seed": -1}}

    import requests
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
        sys.exit(1)

    print(f"Status: {response.status_code}")
    print(f"Body: {(response.text or '')[:500]}")
    if response.ok:
        print("Verdict: success — generate-proxy accepted the request.")
    elif response.status_code == 401:
        print("Verdict: auth rejected.")
        print(wrapper.get_auth_guidance(response.text))
    elif wrapper.is_challenge_block(response):
        print("Verdict: verification/bot-protection refusal (Issue #7).")
        print(wrapper.get_challenge_guidance(response.status_code, url))
    else:
        print("Verdict: upstream error. Try again later; if it persists, check the README.")


if __name__ == "__main__":
    main()
