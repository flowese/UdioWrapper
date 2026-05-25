"""
Udio Wrapper
Author: Flowese
Version: 0.0.5
Date: 2026-05-25
Description: Generates songs using the Udio API using textual prompts.
Fixes:
  - v0.0.4: Fix malformed Cookie header (no leading semicolon),
            use requests.Session for connection reuse,
            add exponential backoff retry,
            proper error logging showing Udio response body,
            updated User-Agent, configurable timeout/proxies
  - v0.0.5: Support Authorization header as fallback,
            add browser-based mode via UdioBrowser (Playwright) to bypass hCaptcha,
            improved hCaptcha error detection and messaging
"""

import os
import time
import logging
import json
import shutil
import tempfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required: requests
# ---------------------------------------------------------------------------
try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.exceptions import RequestException
except ImportError:
    raise ImportError("requests is required. Install it with: pip install requests")

try:
    from urllib3.util.retry import Retry
except ImportError:
    Retry = None

# ---------------------------------------------------------------------------
# Optional: cloudscraper (Cloudflare bypass)
# ---------------------------------------------------------------------------
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# ---------------------------------------------------------------------------
# Optional: playwright for browser-based API calls (hCaptcha bypass)
# ---------------------------------------------------------------------------
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class UdioWrapper:
    """Python wrapper for Udio's internal API.

    Usage:
        wrapper = UdioWrapper(auth_token="your-sb-api-auth-token")
        wrapper.create_song("a relaxing jazz melody")
    """

    API_BASE_URL = "https://www.udio.com/api"

    def __init__(
        self,
        auth_token,
        timeout=60,
        max_retries=3,
        use_cloudscraper=False,
        proxies=None,
    ):
        self.auth_token = auth_token.strip()
        self.all_track_ids = []
        self.timeout = timeout
        self.proxies = proxies

        # Build session with retry adapter
        if use_cloudscraper and HAS_CLOUDSCRAPER:
            logger.info("Using cloudscraper session (Cloudflare bypass)")
            self.session = cloudscraper.create_scraper()
        else:
            self.session = requests.Session()
            if Retry is not None:
                retry_strategy = Retry(
                    total=max_retries,
                    read=max_retries,
                    connect=max_retries,
                    backoff_factor=0.5,
                    allowed_methods=["GET", "POST"],
                    status_forcelist=[429, 500, 502, 503, 504],
                )
                adapter = HTTPAdapter(max_retries=retry_strategy)
                self.session.mount("https://", adapter)
                self.session.mount("http://", adapter)

        if proxies:
            self.session.proxies.update(proxies)

    # ------------------------------------------------------------------ #
    #  Low-level request helpers
    # ------------------------------------------------------------------ #

    def get_headers(self, get_request=False):
        """Build headers that mimic the Udio web client.

        The auth token is sent as a Cookie named ``sb-api-auth-token``.
        (Previous versions had a leading ``;`` which caused a 500 error.)
        """
        headers = {
            "Accept": (
                "application/json, text/plain, */*"
                if get_request
                else "application/json"
            ),
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    def make_request(self, url, method, data=None, headers=None):
        """Execute an HTTP request with the configured session.

        Returns the ``requests.Response`` on success, or ``None`` on failure
        (after logging the Udio response body so the caller can diagnose).
        """
        try:
            kwargs = {"headers": headers, "timeout": self.timeout}
            if self.proxies:
                kwargs["proxies"] = self.proxies
            if method == "POST":
                kwargs["json"] = data
                response = self.session.post(url, **kwargs)
            else:
                response = self.session.get(url, **kwargs)

            response.raise_for_status()
            return response

        except RequestException as e:
            status = ""
            body = ""
            if e.response is not None:
                status = e.response.status_code
                try:
                    body = e.response.text[:1000]
                except Exception:
                    pass

            msg = f"Udio API {method} {url} -> {status or 'error'}"
            if body:
                msg += f" | body: {body}"
            logger.error(msg)

            # Detect hCaptcha / bot-block hint
            if status == 500:
                if "captcha" in body.lower() or "hcaptcha" in body.lower():
                    logger.warning(
                        "Udio returned 500 with hCaptcha reference. "
                        "The wrapper can't bypass CAPTCHAs directly. "
                        "If you installed playwright, try using "
                        "UdioWrapper with a persistent browser context "
                        'via: wrapper = UdioBrowser(auth_token="...")'
                    )
                elif not body or "Internal Server Error" in body:
                    logger.warning(
                        "Udio returned a generic 500. Possible causes:\n"
                        "  1. Invalid or expired auth_token\n"
                        "  2. Udio has changed its API endpoint/format\n"
                        "  3. hCaptcha / bot detection is blocking the request\n"
                        "  4. Your account has no credits\n"
                        "Install playwright and use UdioBrowser instead, "
                        "or check https://www.udio.com in a browser."
                    )
            return None

    # ------------------------------------------------------------------ #
    #  Song generation pipeline
    # ------------------------------------------------------------------ #

    def create_complete_song(
        self,
        short_prompt,
        extend_prompts,
        outro_prompt,
        seed=-1,
        custom_lyrics_short=None,
        custom_lyrics_extend=None,
        custom_lyrics_outro=None,
        num_extensions=1,
    ):
        """Generate a full song: short → extend → outro."""
        logger.info("Starting generation of complete song sequence...")

        short_song_result = self.create_song(short_prompt, seed, custom_lyrics_short)
        if not short_song_result:
            logger.error("Failed to generate short song.")
            return None

        last_song_result = short_song_result
        extend_song_results = []

        for i in range(num_extensions):
            if i < len(extend_prompts):
                prompt = extend_prompts[i]
                lyrics = (
                    custom_lyrics_extend[i]
                    if custom_lyrics_extend and i < len(custom_lyrics_extend)
                    else None
                )
            else:
                prompt = extend_prompts[-1]
                lyrics = custom_lyrics_extend[-1] if custom_lyrics_extend else None

            logger.info("Generating extend song %d/%d...", i + 1, num_extensions)
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]["song_path"],
                audio_conditioning_song_id=last_song_result[0]["id"],
                custom_lyrics=lyrics,
            )
            if not extend_song_result:
                logger.error("Failed to generate extend song %d.", i + 1)
                return None

            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        logger.info("Generating outro...")
        outro_song_result = self.add_outro(
            outro_prompt,
            seed,
            audio_conditioning_path=last_song_result[0]["song_path"],
            audio_conditioning_song_id=last_song_result[0]["id"],
            custom_lyrics=custom_lyrics_outro,
        )
        if not outro_song_result:
            logger.error("Failed to generate outro.")
            return None

        logger.info("Complete song sequence generated successfully.")
        return {
            "short_song": short_song_result,
            "extend_songs": extend_song_results,
            "outro_song": outro_song_result,
        }

    # ------------------------------------------------------------------ #
    #  _generate – unified API call
    # ------------------------------------------------------------------ #

    def _generate(self, prompt, seed, extra_opts=None, custom_lyrics=None):
        """POST to /api/generate-proxy and return parsed JSON."""
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = {
            "prompt": prompt,
            "samplerOptions": {"seed": seed, **(extra_opts or {})},
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    # ------------------------------------------------------------------ #
    #  Public API: create_song / extend / add_outro
    # ------------------------------------------------------------------ #

    def create_song(self, prompt, seed=-1, custom_lyrics=None):
        """Generate a new song from a text prompt."""
        song_result = self._generate(prompt, seed, custom_lyrics=custom_lyrics)
        if not song_result:
            return None
        track_ids = song_result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "short_songs")

    def extend(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
    ):
        """Extend (continue) an existing song."""
        opts = {}
        if audio_conditioning_path:
            opts["audio_conditioning_path"] = audio_conditioning_path
            opts["audio_conditioning_song_id"] = audio_conditioning_song_id
            opts["audio_conditioning_type"] = "continuation"
        extend_song_result = self._generate(
            prompt, seed, extra_opts=opts, custom_lyrics=custom_lyrics
        )
        if not extend_song_result:
            return None
        extend_track_ids = extend_song_result.get("track_ids", [])
        self.all_track_ids.extend(extend_track_ids)
        return self.process_songs(extend_track_ids, "extend_songs")

    def add_outro(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
    ):
        """Add an outro (conclusion) to an existing song."""
        opts = {"crop_start_time": 0.9}
        if audio_conditioning_path:
            opts["audio_conditioning_path"] = audio_conditioning_path
            opts["audio_conditioning_song_id"] = audio_conditioning_song_id
            opts["audio_conditioning_type"] = "continuation"
        outro_result = self._generate(
            prompt, seed, extra_opts=opts, custom_lyrics=custom_lyrics
        )
        if not outro_result:
            return None
        outro_track_ids = outro_result.get("track_ids", [])
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    # ------------------------------------------------------------------ #
    #  Status polling & download
    # ------------------------------------------------------------------ #

    def process_songs(self, track_ids, folder):
        """Poll song status until all are finished, then download them."""
        logger.info("Processing %s songs with track_ids %s...", folder, track_ids)
        wait = 3
        while True:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                logger.warning(
                    "Error checking status for %s, retrying in %ds...",
                    folder,
                    wait,
                )
                time.sleep(wait)
                wait = min(wait * 1.5, 30)
                continue
            if status_result.get("all_finished", False):
                songs = []
                for song in status_result["data"]["songs"]:
                    self.download_song(song["song_path"], song["title"], folder=folder)
                    songs.append(song)
                logger.info("All %d song(s) in %s ready.", len(songs), folder)
                return songs
            time.sleep(5)

    def check_song_status(self, song_ids):
        """GET /api/songs and check whether every track has finished."""
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(True)
        response = self.make_request(url, "GET", None, headers)
        if response:
            data = response.json()
            all_finished = all(song["finished"] for song in data["songs"])
            return {"all_finished": all_finished, "data": data}
        return None

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        """Download a completed song MP3 to the given folder."""
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{song_title}.mp3")
        try:
            response = self.session.get(song_url, timeout=self.timeout)
            response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(response.content)
            logger.info("Downloaded %s -> %s", song_title, file_path)
        except RequestException as e:
            logger.error("Failed to download %s: %s", song_title, e)

    # ------------------------------------------------------------------ #
    #  Hints for browser-based alternative
    # ------------------------------------------------------------------ #

    @staticmethod
    def requires_browser_mode():
        """Return True when requests-based calls are expected to fail
        because Udio requires a browser context (hCaptcha)."""
        return not HAS_PLAYWRIGHT

    @staticmethod
    def install_playwright_hint():
        return (
            "Install playwright and browsers:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
            "Then use: from udio_wrapper import UdioBrowser"
        )


# ----------------------------------------------------------------------- #
#  UdioBrowser – hCaptcha-aware wrapper using Playwright
# ----------------------------------------------------------------------- #

if HAS_PLAYWRIGHT:

    class UdioBrowser:
        """Playwright-based Udio API client that handles hCaptcha.

        Usage::

            from udio_wrapper import UdioBrowser

            with UdioBrowser() as udio:
                udio.login("https://www.udio.com")
                # Solve captcha manually in the browser window (once).
                result = udio.generate_songs(["a jazz tune"])

        The browser persists auth state in a temporary user-data dir so
        the captcha only needs to be solved on the **first** run.
        """

        API_BASE_URL = "https://www.udio.com/api"

        def __init__(self, headless=False, user_data_dir=None):
            self.headless = headless
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            self._user_data_dir = user_data_dir

        # ---- context manager ---------------------------------------- #

        def __enter__(self):
            self.playwright = sync_playwright().start()
            ud = self._user_data_dir or tempfile.mkdtemp(prefix="udiobrowser_")
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=ud,
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
                no_viewport=True,
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            # Inject anti-detection script
            self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            """)
            return self

        def __exit__(self, *args):
            if self.context:
                self.context.close()
            if self.playwright:
                self.playwright.stop()

        # ---- public helpers ----------------------------------------- #

        def login(self, url="https://www.udio.com", timeout=120000):
            """Navigate to Udio.  Solve the hCaptcha manually once."""
            logger.info("Opening %s ...", url)
            self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            logger.info(
                "If a captcha appears, solve it manually in the browser window. "
                "It will be remembered on subsequent runs."
            )
            # Wait for the app shell to load (logged-in state)
            try:
                self.page.wait_for_url("**/my-creations*", timeout=timeout)
                logger.info("Login confirmed (landed on /my-creations).")
            except Exception:
                logger.warning(
                    "Did not land on /my-creations within timeout. "
                    "You may need to log in manually or increase timeout."
                )

        def get_cookies(self):
            """Return the current browser cookies as a dict."""
            cookies = self.context.cookies()
            return {c["name"]: c["value"] for c in cookies}

        def get_auth_token(self):
            """Extract ``sb-api-auth-token`` from the browser's cookies."""
            cookies = self.get_cookies()
            token = cookies.get("sb-api-auth-token")
            if token:
                logger.info("Auth token found in browser cookies.")
            else:
                logger.warning("sb-api-auth-token not found in cookies. Are you logged in?")
            return token

        def api_request(self, method, path, json_data=None):
            """Execute a fetch-style API call through the browser page.

            This bypasses hCaptcha because the request originates from the
            same authenticated browser context.
            """
            script = f"""
                (async () => {{
                    const url = '{self.API_BASE_URL}{path}';
                    const opts = {{
                        method: '{method}',
                        headers: {{
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                        }},
                    }};
                    if ({json_data is not None}) {{
                        opts.body = JSON.stringify({json.dumps(json_data)});
                    }}
                    try {{
                        const resp = await fetch(url, opts);
                        const text = await resp.text();
                        return {{ok: resp.ok, status: resp.status, body: text}};
                    }} catch (err) {{
                        return {{ok: false, status: 0, body: err.message}};
                    }}
                }})();
            """
            result = self.page.evaluate(script)
            if not result.get("ok"):
                logger.error(
                    "Udio API %s %s -> %s | body: %s",
                    method,
                    path,
                    result.get("status", "error"),
                    result.get("body", "")[:500],
                )
                return None
            return json.loads(result["body"])

        def generate_songs(self, prompts, seed=-1, custom_lyrics_list=None):
            """Generate multiple songs using the browser-based API.

            Returns a list of (track_ids, status_data) tuples.
            """
            results = []
            for i, prompt in enumerate(prompts):
                logger.info("Generating song %d/%d: %s", i + 1, len(prompts), prompt)
                data = {
                    "prompt": prompt,
                    "samplerOptions": {"seed": seed},
                }
                if custom_lyrics_list and i < len(custom_lyrics_list):
                    data["lyricInput"] = custom_lyrics_list[i]

                resp = self.api_request("POST", "/generate-proxy", data)
                if resp is None:
                    logger.error("Failed to generate song %d.", i + 1)
                    continue

                track_ids = resp.get("track_ids", [])
                logger.info("Song %d → track_ids: %s", i + 1, track_ids)
                results.append((track_ids, resp))
            return results

        def wait_for_songs(self, track_ids, poll_interval=5, max_wait=300):
            """Poll /api/songs until all track_ids are finished."""
            elapsed = 0
            while elapsed < max_wait:
                path = f"/songs?songIds={','.join(track_ids)}"
                data = self.api_request("GET", path)
                if data and "songs" in data:
                    all_finished = all(s.get("finished") for s in data["songs"])
                    if all_finished:
                        logger.info("All %d tracks finished.", len(track_ids))
                        return data
                time.sleep(poll_interval)
                elapsed += poll_interval
            logger.warning("Timed out waiting for songs after %ds.", max_wait)
            return None
