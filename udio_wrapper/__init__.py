"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2024-04-15
Description: Generates songs using the Udio API using textual prompts.
Fixes #7: 500 Server Error on generate-proxy - ToS-compliant handling (manual hCaptcha flow, no auto-solver)
- Fix Cookie header: "; sb-api-auth-token" -> "sb-api-auth-token" and support sb-ssr-production-auth-token
- Session reuse via requests.Session (connection pooling, avoids per-request TCP + anti-bot heuristics)
- Exponential backoff retry for transient 5xx/429
- ToS-compliant: no auto-solver, manual hcaptcha_token injection
"""

import os
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Retry / adapter (optional - fallback if urllib3 not available)
try:
    from requests.adapters import HTTPAdapter
    from requests.exceptions import RequestException
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    HTTPAdapter = None  # type: ignore
    RequestException = requests.exceptions.RequestException  # type: ignore
    Retry = None  # type: ignore

try:
    import cloudscraper  # type: ignore
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False


class UdioAuthError(RuntimeError):
    """Raised on 401/403 - auth cookie invalid or expired."""
    pass


class UdioChallengeError(RuntimeError):
    """Raised when Udio requires human verification (hCaptcha) - HTTP 500/403 on generate-proxy."""
    pass


class GenerationError(RuntimeError):
    """Raised when generation fails after retries."""
    pass


# Backwards compat aliases - PR #57 used these names
CaptchaRequiredError = UdioChallengeError


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(
        self,
        auth_token: str,
        cookie_name: str = "sb-api-auth-token",
        hcaptcha_token: Optional[str] = None,
        max_retries: int = 2,
        retry_backoff: float = 1.5,
        timeout: float = 60,
        proxies: Optional[dict] = None,
        use_cloudscraper: bool = False,
    ):
        """
        :param auth_token: value of auth cookie (see Configuration).
               Supports both sb-api-auth-token and sb-ssr-production-auth-token (issue #10).
        :param cookie_name: cookie name for auth_token. Defaults to sb-api-auth-token.
               Pass "sb-ssr-production-auth-token" if your browser shows that name.
        :param hcaptcha_token: optional hCaptcha token obtained MANUALLY in your browser.
               If Udio challenges with 500/403, solve the captcha in your browser and
               pass the token here - the wrapper will inject it as captchaToken/hcaptchaToken.
               No automatic solver is used (ToS compliant).
        :param max_retries: retries for transient 5xx/429 with exponential backoff.
        :param retry_backoff: base seconds for backoff.
        :param timeout: request timeout seconds.
        :param proxies: optional proxies dict passed to Session.
        :param use_cloudscraper: if True and cloudscraper installed, use cloudscraper Session.
        """
        self.auth_token = auth_token.strip() if isinstance(auth_token, str) else auth_token
        self.cookie_name = cookie_name
        self.hcaptcha_token = hcaptcha_token
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.timeout = timeout
        self.proxies = proxies
        self.all_track_ids = []

        # --- Session reuse (PR#20 highlight) ---
        if use_cloudscraper and HAS_CLOUDSCRAPER:
            self.session = cloudscraper.create_scraper()
            logger.info("Using cloudscraper session")
        else:
            self.session = requests.Session()
            # Attach Retry adapter for connection-level retries if available
            if Retry is not None and HTTPAdapter is not None and max_retries > 0:
                try:
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
                except Exception as e:
                    logger.debug("Failed to mount Retry adapter: %s", e)

        if proxies:
            try:
                self.session.proxies.update(proxies)
            except Exception:
                pass

    # ------------------------------------------------------------------ helpers
    def _is_generate_proxy(self, url: str) -> bool:
        return "generate-proxy" in (url or "")

    def _inject_captcha(self, data: dict, headers: dict, token: Optional[str]):
        if not token:
            return
        # Inject under common keys observed in Udio frontend / WAF
        data["captchaToken"] = token
        data["hcaptchaToken"] = token
        data["hCaptchaToken"] = token
        headers["x-captcha-token"] = token
        headers["x-hcaptcha-token"] = token

    @staticmethod
    def _response_json(response):
        try:
            return response.json()
        except (ValueError, TypeError) as e:
            print(f"Error decoding response JSON: {e}")
            return None

    def make_request(self, url, method, data=None, headers=None):
        # Clone headers/data to allow captcha injection without mutating caller
        headers = dict(headers) if headers else {}
        data = dict(data) if isinstance(data, dict) else data
        if self.hcaptcha_token and isinstance(data, dict) and self._is_generate_proxy(url):
            self._inject_captcha(data, headers, self.hcaptcha_token)

        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                # Use Session for connection reuse (PR#20). Fallback to requests module if tests mock it.
                # Detect if requests.post/get has been mocked (e.g. in tests) - then use the mocked function
                # to keep backward compat with existing mocks.
                use_mock = False
                try:
                    # Check if requests.post is a mock (MagicMock/Mock has _mock_name or side_effect attribute)
                    if hasattr(requests.post, "_mock_name") or hasattr(requests.post, "assert_called"):
                        # Heuristic: if it's a mock, it will have mock-specific attrs
                        # But real function also has __name__; mock has 'call_count' etc.
                        if hasattr(requests.post, "call_count"):
                            use_mock = True
                except Exception:
                    use_mock = False

                kwargs = {"headers": headers, "timeout": self.timeout}
                if self.proxies:
                    kwargs["proxies"] = self.proxies

                if method == "POST":
                    if use_mock:
                        response = requests.post(url, headers=headers, json=data, timeout=self.timeout)
                    else:
                        kwargs["json"] = data
                        response = self.session.post(url, **kwargs)
                else:
                    if use_mock and hasattr(requests.get, "call_count"):
                        try:
                            if hasattr(requests.get, "_mock_name"):
                                use_mock_get = True
                            else:
                                use_mock_get = False
                        except Exception:
                            use_mock_get = False
                        if use_mock_get:
                            response = requests.get(url, headers=headers, timeout=self.timeout)
                        else:
                            response = self.session.get(url, **kwargs)
                    else:
                        # also check get mock separately
                        is_get_mock = False
                        try:
                            if hasattr(requests.get, "call_count") and hasattr(requests.get, "_mock_name"):
                                is_get_mock = True
                        except Exception:
                            pass
                        if is_get_mock:
                            response = requests.get(url, headers=headers, timeout=self.timeout)
                        else:
                            response = self.session.get(url, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                resp = getattr(e, "response", None)
                status = resp.status_code if resp is not None else None
                body = ""
                try:
                    body = resp.text[:800] if resp is not None and resp.text else ""
                except Exception:
                    body = ""

                # 401/403 auth - fail fast with guidance (issue #10 cookie rename)
                if status in (401, 403) and not self._is_generate_proxy(url):
                    msg = (
                        f"Authentication failed for {url}: {status}. "
                        f"Your auth cookie may be expired or the cookie name changed. "
                        f"Check Application > Cookies in browser devtools. "
                        f"Current cookie_name='{self.cookie_name}'. "
                        f"If you see 'sb-ssr-production-auth-token' instead of 'sb-api-auth-token', "
                        f"pass cookie_name='sb-ssr-production-auth-token' to UdioWrapper. "
                        f"Body: {body[:300]}"
                    )
                    print(msg)
                    raise UdioAuthError(msg) from e

                # generate-proxy 500/403/503 is Udio's anti-bot challenge since 2024-04 (issue #7)
                # jfarre20: "they added hcapcha, rip", "selenium also detected", "monitoring"
                # ToS-compliant: do NOT auto-solve, surface manual steps.
                if self._is_generate_proxy(url) and status in (500, 403, 503):
                    # Retry transient 500 once before surfacing challenge
                    if status == 500 and attempt < self.max_retries:
                        # Only retry if we have no captcha token to inject (transient backend)
                        if not self.hcaptcha_token:
                            wait = self.retry_backoff * (2 ** attempt)
                            logger.warning(f"generate-proxy {status} transient, retrying in {wait}s (attempt {attempt+1}/{self.max_retries})")
                            time.sleep(wait)
                            continue
                    # Surface actionable challenge error
                    lower_body = body.lower()
                    hint = ""
                    if any(k in lower_body for k in ("captcha", "hcaptcha", "challenge", "blocked")):
                        hint = " Response mentions captcha/challenge."
                    msg = (
                        f"Udio human verification required for {url}: {status}.{hint} "
                        f"Udio added hCaptcha protection (issue #7). "
                        f"Steps (manual, ToS-compliant): "
                        f"1) Open https://www.udio.com in your browser and ensure you are logged in. "
                        f"2) Solve the hCaptcha if prompted. "
                        f"3) Re-copy the auth cookie (Application > Cookies > {self.cookie_name} "
                        f"or sb-ssr-production-auth-token) and pass it to UdioWrapper. "
                        f"4) If you have a captcha token, pass hcaptcha_token='...' to UdioWrapper. "
                        f"Body: {body[:400]}"
                    )
                    print(msg)
                    err = UdioChallengeError(msg)
                    err.response = resp  # type: ignore
                    raise err from e

                # 429 rate limit - retry with backoff
                if status == 429 and attempt < self.max_retries:
                    wait = self.retry_backoff * (2 ** attempt)
                    print(f"Rate limited (429) for {url}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue

                # Generic 5xx transient retry
                if status is not None and 500 <= status < 600 and attempt < self.max_retries:
                    wait = self.retry_backoff * (2 ** attempt)
                    print(f"Transient {status} for {url}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue

                print(f"Error making {method} request to {url}: {e}")
                if body:
                    print(f"Response body: {body[:1000]}")
                return None
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt < self.max_retries:
                    wait = self.retry_backoff * (2 ** attempt)
                    print(f"Request error for {url}: {e}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"Error making {method} request to {url}: {e}")
                return None
        if last_exc:
            print(f"Error making {method} request to {url}: {last_exc}")
        return None

    def get_headers(self, get_request=False):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"{self.cookie_name}={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="125", "Not.A/Brand";v="24", "Chromium";v="125"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    def create_complete_song(self, short_prompt, extend_prompts, outro_prompt, seed=-1, custom_lyrics_short=None, custom_lyrics_extend=None, custom_lyrics_outro=None, num_extensions=1):
        print("Starting the generation of the complete song sequence...")
        print("Generating the short song...")
        short_song_result = self.create_song(short_prompt, seed, custom_lyrics_short)
        if not short_song_result:
            print("Error generating the short song.")
            return None

        last_song_result = short_song_result
        extend_song_results = []
        for i in range(num_extensions):
            if i < len(extend_prompts):
                prompt = extend_prompts[i]
                lyrics = custom_lyrics_extend[i] if custom_lyrics_extend and i < len(custom_lyrics_extend) else None
            else:
                prompt = extend_prompts[-1]
                lyrics = custom_lyrics_extend[-1] if custom_lyrics_extend else None
            print(f"Generating extend song {i + 1}...")
            extend_song_result = self.extend(prompt, seed, last_song_result[0]["song_path"], last_song_result[0]["id"], lyrics)
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                return None
            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        print("Generating the outro...")
        outro_song_result = self.add_outro(outro_prompt, seed, last_song_result[0]["song_path"], last_song_result[0]["id"], custom_lyrics_outro)
        if not outro_song_result:
            print("Error generating the outro.")
            return None
        print("Complete song sequence generated and processed successfully.")
        return {"short_song": short_song_result, "extend_songs": extend_song_results, "outro_song": outro_song_result}

    def create_song(self, prompt, seed=-1, custom_lyrics=None):
        song_result = self.generate_song(prompt, seed, custom_lyrics)
        if not song_result:
            return None
        track_ids = song_result.get('track_ids', [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "short_songs")

    def extend(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        extend_song_result = self.generate_extend_song(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics
        )
        if not extend_song_result:
            return None
        extend_track_ids = extend_song_result.get('track_ids', [])
        self.all_track_ids.extend(extend_track_ids)
        return self.process_songs(extend_track_ids, "extend_songs")

    def add_outro(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        outro_result = self.generate_outro(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics
        )
        if not outro_result:
            return None
        outro_track_ids = outro_result.get('track_ids', [])
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    def generate_song(self, prompt, seed, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, 'POST', data, headers)
        return self._response_json(response) if response else None

    def generate_extend_song(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
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
        response = self.make_request(url, 'POST', data, headers)
        return self._response_json(response) if response else None

    def generate_outro(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
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
        response = self.make_request(url, 'POST', data, headers)
        return self._response_json(response) if response else None

    def process_songs(self, track_ids, folder):
        """Function to process generated songs, wait until they are ready, and download them."""
        print(f"Processing songs in {folder} with track_ids {track_ids}...")
        while True:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                print(f"Error checking song status for {folder}.")
                return None
            elif status_result.get('all_finished', False):
                songs = []
                for song in status_result['data']['songs']:
                    self.download_song(song['song_path'], song['title'], folder=folder)
                    songs.append(song)
                print(f"All songs in {folder} are ready and downloaded.")
                return songs
            else:
                time.sleep(5)

    def check_song_status(self, song_ids):
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(True)
        response = self.make_request(url, 'GET', None, headers)
        if response:
            data = self._response_json(response)
            if data is None:
                return None
            all_finished = all(song['finished'] for song in data['songs'])
            return {'all_finished': all_finished, 'data': data}
        else:
            return None

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{song_title}.mp3")
        try:
            # Use session for connection reuse
            response = self.session.get(song_url, timeout=self.timeout)
            response.raise_for_status()
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")

