"""
Browser-based Udio wrapper that bypasses hCaptcha protection.

Uses Playwright with persistent browser context so you only need to
solve the captcha once. After that, cookies and localStorage are
saved and reused on subsequent runs.
"""

import os
import time
import json
from pathlib import Path


class UdioBrowser:
    """
    Browser-based Udio song generator that handles hCaptcha automatically.

    On first run, a browser window opens. If Udio shows a hCaptcha,
    solve it manually once. The session is then persisted and future
    runs should work without captcha prompts.

    Usage:
        wrapper = UdioBrowser()
        wrapper.login()
        songs = wrapper.generate_song("a jazz track about coding at midnight")
    """

    API_BASE_URL = "https://www.udio.com/api"
    UDIO_URL = "https://www.udio.com"

    def __init__(
        self,
        user_data_dir: str = None,
        headless: bool = False,
        timeout: int = 60000,
    ):
        self.user_data_dir = user_data_dir or str(
            Path.home() / ".udio_browser_profile"
        )
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._context = None
        self._page = None
        self._cached_token = None
        self.all_track_ids = []

    def _start_browser(self):
        """Lazy-init Playwright with a persistent browser context."""
        if self._page is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "playwright is required for browser mode.\n"
                "Install: pip install playwright && playwright install chromium"
            )

        self._playwright = sync_playwright().start()
        os.makedirs(self.user_data_dir, exist_ok=True)

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        # Hide automation markers
        self._context.add_init_script("""
            Object.defineProperty(navigator, "webdriver", {
                get: () => undefined,
            });
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {},
            };
            const origQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (params) => (
                params.name === "notifications"
                    ? Promise.resolve({ state: Notification.permission })
                    : origQuery(params)
            );
        """)

        self._page = self._context.new_page()

    def login(self, auth_token: str = None) -> bool:
        """
        Open Udio in browser. If auth_token is provided, inject it as a cookie.
        Otherwise, navigate to Udio for manual login.

        Returns True if we successfully obtained a session.
        """
        self._start_browser()
        print("Opening Udio in browser...")

        if auth_token:
            self._page.goto(self.UDIO_URL, wait_until="domcontentloaded")
            self._context.add_cookies([{
                "name": "sb-api-auth-token",
                "value": auth_token,
                "domain": ".udio.com",
                "path": "/",
            }])

        self._page.goto(
            f"{self.UDIO_URL}/my-creations", wait_until="networkidle"
        )

        # Handle hCaptcha if present
        captcha_frame = self._page.locator(
            'iframe[src*="hcaptcha"]'
        )
        if captcha_frame.count() > 0:
            print("")
            print("=" * 50)
            print("  hCaptcha detected — please solve it in the browser")
            print("  Your session will be saved for future runs.")
            print("=" * 50)
            print("")
            try:
                self._page.wait_for_function(
                    "() => document.querySelectorAll("
                    '\'iframe[src*="hcaptcha"]\').length === 0',
                    timeout=300000,  # 5 minutes
                )
                print("Captcha solved! Session saved.")
            except Exception:
                print(
                    "Timed out waiting for captcha. "
                    "Try running login() again."
                )
                return False

        # Extract token from cookies
        cookies = self._context.cookies()
        for cookie in cookies:
            if cookie["name"] == "sb-api-auth-token":
                self._cached_token = cookie["value"]
                print(f"Session obtained (token length: {len(self._cached_token)})")
                return True

        print(
            "Could not find auth token automatically. "
            "Log in on the Udio page in the browser, then close it."
        )
        input("Press Enter after logging in...")
        return self._refresh_token()

    def _refresh_token(self) -> bool:
        """Attempt to extract the auth token after manual login."""
        try:
            self._page.goto(
                f"{self.UDIO_URL}/api/auth/session",
                wait_until="networkidle",
            )
            body = self._page.locator("pre").inner_text()
            session = json.loads(body)
            token = session.get("access_token")
            if token:
                self._cached_token = token
                return True
        except Exception:
            pass

        cookies = self._context.cookies()
        for cookie in cookies:
            if "auth" in cookie.get("name", "").lower():
                self._cached_token = cookie["value"]
                return True
        return False

    def _api_fetch(self, endpoint: str, data: dict) -> dict:
        """
        Call Udio API through the browser's native fetch.
        This carries the real browser fingerprint, so hCaptcha is satisfied.
        """
        self._start_browser()
        url = f"{self.API_BASE_URL}/{endpoint}"

        result = self._page.evaluate(
            """
            async ({url, data}) => {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json",
                    },
                    body: JSON.stringify(data),
                    credentials: "include",
                });
                return {
                    status: resp.status,
                    body: await resp.json().catch(() => resp.text()),
                };
            }
            """,
            {"url": url, "data": data},
        )

        if result["status"] >= 500:
            raise RuntimeError(
                f"Udio returned HTTP {result['status']}. "
                "This may mean hCaptcha is blocking the request. "
                "Try running login() again to refresh your session."
            )

        if result["status"] >= 400:
            raise RuntimeError(
                f"Udio API error {result['status']}: "
                f"{result.get('body', '')}"
            )

        return result["body"]

    def generate_song(
        self, prompt: str, seed: int = -1, custom_lyrics: str = None
    ) -> list:
        """Generate a song and wait for completion."""
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics

        print(f"Generating: {prompt[:80]}...")
        result = self._api_fetch("generate-proxy", data)
        track_ids = result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self._wait_for_songs(track_ids)

    def extend_song(
        self,
        prompt: str,
        seed: int = -1,
        audio_conditioning_path: str = None,
        audio_conditioning_song_id: str = None,
        custom_lyrics: str = None,
    ) -> list:
        """Extend an existing song."""
        data = {
            "prompt": prompt,
            "samplerOptions": {
                "seed": seed,
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
            },
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics

        result = self._api_fetch("generate-proxy", data)
        track_ids = result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self._wait_for_songs(track_ids)

    def add_outro(
        self,
        prompt: str,
        seed: int = -1,
        audio_conditioning_path: str = None,
        audio_conditioning_song_id: str = None,
        custom_lyrics: str = None,
    ) -> list:
        """Add an outro to an existing song."""
        data = {
            "prompt": prompt,
            "samplerOptions": {
                "seed": seed,
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
                "crop_start_time": 0.9,
            },
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics

        result = self._api_fetch("generate-proxy", data)
        track_ids = result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self._wait_for_songs(track_ids)

    def _wait_for_songs(
        self, track_ids: list, poll_interval: int = 5
    ) -> list:
        """Poll until all songs are complete."""
        print(f"Waiting for {len(track_ids)} track(s)...")

        while True:
            result = self._api_fetch(
                "songs/status", {"song_ids": track_ids}
            )

            if result.get("all_finished"):
                songs = result.get("data", {}).get("songs", [])
                print(f"Complete! {len(songs)} song(s) ready.")
                return songs

            done = sum(
                1
                for s in result.get("data", {}).get("songs", [])
                if s.get("status") == "complete"
            )
            print(f"  {done}/{len(track_ids)} ready, waiting {poll_interval}s...")
            time.sleep(poll_interval)

    def close(self):
        """Release browser resources."""
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None
