"""
Browser-backed fallback for UdioWrapper (Issue #7).

Udio requires a fresh hCaptcha token on POST /api/generate-proxy, so plain
requests-based calls fail with HTTP 500. This client drives a real, headed
Chromium browser: you log in once, and any verification challenge is solved
by you in the browser window. The client automates prompt entry, submission,
capturing generated track ids from the browser's own generate-proxy response,
polling for completion, and downloading the songs.
"""

import os
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

UDIO_HOME = "https://www.udio.com/"

SESSION_COOKIES = (
    "sb-ssr-production-auth-token",
    "sb-api-auth-token",
)


class BrowserClientError(RuntimeError):
    pass


class UdioBrowserClient:
    def __init__(self, user_data_dir=None, headless=False, login_timeout_s=600):
        self.user_data_dir = user_data_dir or os.path.join(
            os.path.expanduser("~"), ".udio_wrapper_browser"
        )
        self.headless = headless
        self.login_timeout_s = login_timeout_s
        self._pw = None
        self._context = None
        self.page = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def start(self):
        if sync_playwright is None:
            raise BrowserClientError(
                "playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            )
        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            self.user_data_dir, headless=self.headless
        )
        self.page = self._context.new_page()

    def close(self):
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _has_session_cookie(self):
        for cookie in self._context.cookies():
            if any(name in cookie["name"] for name in SESSION_COOKIES):
                return True
        return False

    def wait_for_login(self):
        """Open Udio; the user logs in and completes any challenge in the window."""
        self.page.goto(UDIO_HOME, wait_until="domcontentloaded")
        deadline = time.time() + self.login_timeout_s
        while time.time() < deadline:
            if self._has_session_cookie():
                return True
            time.sleep(2)
        raise BrowserClientError("Timed out waiting for a logged-in Udio session.")

    def _fill_prompt_and_submit(self, prompt):
        self.page.goto(UDIO_HOME, wait_until="domcontentloaded")
        box = self.page.locator("textarea, [contenteditable='true']").first
        box.wait_for(state="visible", timeout=30000)
        box.click()
        box.fill(prompt)
        box.press("Enter")

    def create_song(self, prompt, timeout_s=1800, poll_s=5):
        """Create a song through the real UI. Returns a list of song dicts."""
        with self.page.expect_response(
            lambda r: "/api/generate-proxy" in r.url and r.request.method == "POST",
            timeout=timeout_s * 1000,
        ) as resp_info:
            self._fill_prompt_and_submit(prompt)
        response = resp_info.value
        if not response.ok:
            raise BrowserClientError(
                f"generate-proxy failed from the browser too: "
                f"{response.status} {(response.text() or '')[:300]}"
            )
        payload = response.json()
        track_ids = payload.get("track_ids", [])
        if not track_ids:
            raise BrowserClientError(f"No track_ids in generate-proxy response: {payload}")
        return self.wait_for_songs(track_ids, timeout_s=timeout_s, poll_s=poll_s)

    def wait_for_songs(self, track_ids, timeout_s=1800, poll_s=5):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            resp = self._context.request.get(
                "https://www.udio.com/api/songs",
                params={"songIds": ",".join(track_ids)},
            )
            if resp.ok:
                data = resp.json()
                if all(song.get("finished") for song in data.get("songs", [])):
                    return data["songs"]
            time.sleep(poll_s)
        raise BrowserClientError(f"Timed out waiting for songs {track_ids}.")

    def download_songs(self, songs, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        paths = []
        for song in songs:
            url = song.get("song_path")
            if not url:
                continue
            title = song.get("title", song.get("id", "track"))
            path = os.path.join(folder, f"{title}.mp3")
            resp = self._context.request.get(url)
            with open(path, "wb") as fh:
                fh.write(resp.body())
            paths.append(path)
        return paths

    def extend(self, *args, **kwargs):
        raise NotImplementedError(
            "Extend is not automated; use the open browser window's UI."
        )

    def add_outro(self, *args, **kwargs):
        raise NotImplementedError(
            "Outro is not automated; use the open browser window's UI."
        )
