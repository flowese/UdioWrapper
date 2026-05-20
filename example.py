#!/usr/bin/env python3
"""
Example: Using the improved UdioWrapper (v0.0.4).
Fixes the 500 error from Issue #7.
"""

import logging
import sys

from udio_wrapper import UdioWrapper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

AUTH_TOKEN = "YOUR_SB-API-AUTH-TOKEN"  # Get from Udio cookies

# Fix #1: use_cloudscraper=True bypasses Cloudflare if Udio added it
# Fix #2: retries on 500/502/503/504 with exponential backoff
# Fix #3: fixed malformed Cookie header (was "; sb-api-auth-token" → "sb-api-auth-token")
# Fix #4: proper error logging that shows Udio's response body
wrapper = UdioWrapper(
    auth_token=AUTH_TOKEN,
    timeout=90,
    max_retries=3,
    use_cloudscraper=False,  # set True if you install cloudscraper
)

# Quick health check — verify the session works
print("Generating song...")
result = wrapper.create_song(
    prompt="A relaxing jazz melody with piano",
    seed=-1,
)
if result:
    print(f"Success! Generated {len(result)} song(s):")
    for song in result:
        print(f"  - {song['title']} -> {song['song_path']}")
else:
    print("Failed. Enable DEBUG logging to see Udio's error response:")
    print("  logging.getLogger().setLevel(logging.DEBUG)")
    sys.exit(1)
