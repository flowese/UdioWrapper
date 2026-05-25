#!/usr/bin/env python3
"""
Example: Using UdioWrapper (v0.0.5).

Fixes the 500 error from Issue #7:
  - Fixed malformed Cookie header (was "; sb-api-auth-token" -> "sb-api-auth-token")
  - Uses requests.Session with connection reuse + retry on 5xx
  - Configurable timeout, max_retries, proxies
  - Better error logging showing Udio's response body
  - Optional cloudscraper support for Cloudflare
  - Optional UdioBrowser (Playwright) for hCaptcha bypass

Quick start:
    pip install -r requirements.txt
    pip install cloudscraper   # optional, for Cloudflare
    pip install playwright && playwright install chromium  # optional, for hCaptcha

Get your auth token:
    1. Open https://www.udio.com and log in
    2. Open DevTools -> Application -> Cookies -> sb-api-auth-token
    3. Copy the value
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ======================================================================
#  Option A: Direct API calls (requests-based)
# ======================================================================
def example_direct_api():
    from udio_wrapper import UdioWrapper

    AUTH_TOKEN = "YOUR_SB-API-AUTH-TOKEN"

    wrapper = UdioWrapper(
        auth_token=AUTH_TOKEN,
        timeout=90,
        max_retries=3,
        use_cloudscraper=False,  # set True if you installed cloudscraper
    )

    log.info("Generating song via direct API...")
    result = wrapper.create_song(
        prompt="A relaxing jazz melody with piano",
        seed=-1,
    )
    if result:
        log.info("Success! Generated %d song(s):", len(result))
        for song in result:
            log.info("  - %s -> %s", song["title"], song["song_path"])
    else:
        log.error("Failed. Enable DEBUG logging to see Udio's error response:")
        log.error("  logging.getLogger().setLevel(logging.DEBUG)")
        sys.exit(1)


# ======================================================================
#  Option B: Browser-based API (hCaptcha bypass via Playwright)
# ======================================================================
def example_browser_api():
    from udio_wrapper import UdioBrowser

    log.info("Launching browser (solves hCaptcha once, session persists)...")
    with UdioBrowser(headless=False) as udio:
        # Step 1: Navigate to Udio. Solve captcha once in the window.
        udio.login("https://www.udio.com")

        # Step 2: Generate songs through the browser's fetch()
        resp = udio.generate_songs(["A cinematic orchestral piece"])
        if not resp:
            log.error("No songs generated.")
            return

        track_ids, _ = resp[0]
        if not track_ids:
            log.error("No track IDs returned.")
            return

        # Step 3: Wait for completion
        data = udio.wait_for_songs(track_ids, poll_interval=5, max_wait=300)
        if data:
            for song in data.get("songs", []):
                log.info("Song ready: %s -> %s", song.get("title"), song.get("song_path"))


# ======================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UdioWrapper example")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Use Playwright browser mode (bypasses hCaptcha)",
    )
    args = parser.parse_args()

    if args.browser:
        example_browser_api()
    else:
        example_direct_api()
