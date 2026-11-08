"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2024-04-15
Description: Generates songs using the Udio API using textual prompts.
"""

import os
import re
import time
from typing import Any, Callable, Dict, List, Optional
import requests


DEFAULT_HCAPTCHA_SITEKEY = "2945d92a-2228-4330-8022-5e3229f54c46"
DEFAULT_PAGE_URL = "https://www.udio.com/my-creations"


class UdioCaptchaError(RuntimeError):
    """Raised when hCaptcha token resolution fails."""


class CapSolverClient:
    """Minimal REST client for CapSolver hCaptcha tasks."""

    API_URL = "https://api.capsolver.com"

    def __init__(
        self,
        api_key: str,
        poll_interval: float = 2.0,
        timeout: float = 120.0,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.session = session or requests.Session()

    def solve_hcaptcha(
        self,
        sitekey: str,
        page_url: str = DEFAULT_PAGE_URL,
        user_agent: Optional[str] = None,
    ) -> str:
        task: Dict[str, Any] = {
            "type": "HCaptchaTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        if user_agent:
            task["userAgent"] = user_agent

        create_resp = self.session.post(
            f"{self.API_URL}/createTask",
            json={"clientKey": self.api_key, "task": task},
            timeout=30,
        )
        create_resp.raise_for_status()
        create_data = create_resp.json()
        if create_data.get("errorId", 0) != 0 or not create_data.get("taskId"):
            raise UdioCaptchaError(
                f"CapSolver createTask failed: {create_data.get('errorDescription', create_data)}"
            )

        task_id = create_data["taskId"]
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)
            res_resp = self.session.post(
                f"{self.API_URL}/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
                timeout=30,
            )
            res_resp.raise_for_status()
            res_data = res_resp.json()
            if res_data.get("errorId", 0) != 0:
                raise UdioCaptchaError(
                    f"CapSolver getTaskResult failed: {res_data.get('errorDescription', res_data)}"
                )
            status = res_data.get("status")
            if status == "ready":
                solution = res_data.get("solution") or {}
                token = solution.get("gRecaptchaResponse") or solution.get("token")
                if not token:
                    raise UdioCaptchaError("CapSolver returned ready status without token")
                return str(token)
        raise UdioCaptchaError("CapSolver timed out waiting for hCaptcha solution")


class TwoCaptchaClient:
    """Minimal REST client for 2Captcha hCaptcha tasks."""

    IN_URL = "https://2captcha.com/in.php"
    RES_URL = "https://2captcha.com/res.php"

    def __init__(
        self,
        api_key: str,
        poll_interval: float = 3.0,
        timeout: float = 120.0,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.session = session or requests.Session()

    def solve_hcaptcha(
        self,
        sitekey: str,
        page_url: str = DEFAULT_PAGE_URL,
        user_agent: Optional[str] = None,
    ) -> str:
        params: Dict[str, Any] = {
            "key": self.api_key,
            "method": "hcaptcha",
            "sitekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        }
        if user_agent:
            params["userAgent"] = user_agent

        in_resp = self.session.post(self.IN_URL, data=params, timeout=30)
        in_resp.raise_for_status()
        in_data = in_resp.json()
        if in_data.get("status") != 1 or not in_data.get("request"):
            raise UdioCaptchaError(f"2Captcha submit failed: {in_data}")

        captcha_id = in_data["request"]
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)
            res_resp = self.session.get(
                self.RES_URL,
                params={
                    "key": self.api_key,
                    "action": "get",
                    "id": captcha_id,
                    "json": 1,
                },
                timeout=30,
            )
            res_resp.raise_for_status()
            res_data = res_resp.json()
            if res_data.get("status") == 1:
                return str(res_data["request"])
            if res_data.get("request") != "CAPCHA_NOT_READY":
                raise UdioCaptchaError(f"2Captcha polling failed: {res_data}")
        raise UdioCaptchaError("2Captcha timed out waiting for hCaptcha solution")


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        auth_token: str,
        auth_token_0: Optional[str] = None,
        auth_token_1: Optional[str] = None,
        captcha_token: Optional[str] = None,
        captcha_solver: Optional[Callable[..., str]] = None,
        capsolver_api_key: Optional[str] = None,
        twocaptcha_api_key: Optional[str] = None,
        sitekey: Optional[str] = None,
        page_url: str = DEFAULT_PAGE_URL,
        captcha_ttl: float = 110.0,
        reuse_captcha_token: bool = True,
        max_retries: int = 2,
        retry_delay: float = 1.0,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        self.auth_token = auth_token
        self.auth_token_0 = auth_token_0
        self.auth_token_1 = auth_token_1
        self.all_track_ids: List[str] = []

        self.sitekey = (
            sitekey
            or os.environ.get("UDIO_HCAPTCHA_SITEKEY")
            or DEFAULT_HCAPTCHA_SITEKEY
        )
        self.page_url = page_url
        self.captcha_ttl = captcha_ttl
        self.reuse_captcha_token = reuse_captcha_token
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.session = session or requests.Session()

        initial_token = captcha_token or os.environ.get("UDIO_CAPTCHA_TOKEN")
        self._static_captcha_token: Optional[str] = initial_token
        self._cached_captcha_token: Optional[str] = initial_token
        self._cached_captcha_timestamp: float = (
            time.monotonic() if initial_token else 0.0
        )

        capsolver_key = capsolver_api_key or os.environ.get("CAPSOLVER_API_KEY")
        twocaptcha_key = twocaptcha_api_key or os.environ.get("TWOCAPTCHA_API_KEY")

        if captcha_solver is not None:
            self.captcha_solver = captcha_solver
        elif capsolver_key:
            client = CapSolverClient(capsolver_key, session=self.session)
            self.captcha_solver = lambda sk, url: client.solve_hcaptcha(
                sk, url, user_agent=self.USER_AGENT
            )
        elif twocaptcha_key:
            client_2c = TwoCaptchaClient(twocaptcha_key, session=self.session)
            self.captcha_solver = lambda sk, url: client_2c.solve_hcaptcha(
                sk, url, user_agent=self.USER_AGENT
            )
        else:
            self.captcha_solver = None

    def _build_cookie_header(self) -> str:
        """Build a clean Cookie header supporting single tokens, split Supabase cookies, or raw Cookie strings."""
        parts: List[str] = []
        raw = (self.auth_token or "").strip().lstrip(";").strip()
        if raw:
            if "=" in raw and ("sb-" in raw or ";" in raw):
                parts.append(raw)
            else:
                parts.append(f"sb-api-auth-token={raw}")
        if self.auth_token_0:
            parts.append(f"sb-api-auth-token.0={self.auth_token_0.strip()}")
        if self.auth_token_1:
            parts.append(f"sb-api-auth-token.1={self.auth_token_1.strip()}")
        return "; ".join(parts)

    def _call_solver(self) -> Optional[str]:
        if self.captcha_solver is None:
            return None
        try:
            return self.captcha_solver(self.sitekey, self.page_url)
        except TypeError:
            return self.captcha_solver()

    def resolve_captcha_token(self, force_refresh: bool = False) -> Optional[str]:
        """Resolve an hCaptcha token using cache, static token, or the configured solver."""
        now = time.monotonic()
        if (
            not force_refresh
            and self.reuse_captcha_token
            and self._cached_captcha_token
            and (now - self._cached_captcha_timestamp) < self.captcha_ttl
        ):
            return self._cached_captcha_token

        if self.captcha_solver is not None:
            solved = self._call_solver()
            if solved:
                self._cached_captcha_token = solved
                self._cached_captcha_timestamp = time.monotonic()
                return solved

        if not force_refresh and self._static_captcha_token:
            return self._static_captcha_token

        return None

    def invalidate_captcha_token(self) -> None:
        """Invalidate any cached captcha token so the next request forces a fresh solve."""
        self._cached_captcha_token = None
        self._cached_captcha_timestamp = 0.0

    def _should_retry_with_captcha(self, response: Optional[requests.Response]) -> bool:
        if response is None:
            return False
        if response.status_code in (400, 401, 403, 429, 500, 502, 503):
            return True
        return False

    def make_request(self, url, method, data=None, headers=None):
        is_generate = isinstance(url, str) and url.endswith("/generate-proxy")
        req_headers = dict(headers) if headers else self.get_headers(get_request=(method != "POST"))
        payload = dict(data) if isinstance(data, dict) else data

        if is_generate and isinstance(payload, dict) and "captchaToken" not in payload:
            token = self.resolve_captcha_token(force_refresh=False)
            if token:
                payload["captchaToken"] = token
                req_headers["x-captcha-token"] = token

        attempts = 1 + (self.max_retries if is_generate else 0)
        last_error: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                if method == "POST":
                    response = self.session.post(
                        url, headers=req_headers, json=payload, timeout=self.timeout
                    )
                else:
                    response = self.session.get(
                        url, headers=req_headers, timeout=self.timeout
                    )

                if (
                    is_generate
                    and self._should_retry_with_captcha(response)
                    and attempt + 1 < attempts
                    and self.captcha_solver is not None
                ):
                    self.invalidate_captcha_token()
                    fresh_token = self.resolve_captcha_token(force_refresh=True)
                    if fresh_token and isinstance(payload, dict):
                        payload = dict(payload)
                        payload["captchaToken"] = fresh_token
                        req_headers = dict(req_headers)
                        req_headers["x-captcha-token"] = fresh_token
                    if self.retry_delay > 0:
                        time.sleep(self.retry_delay * (2 ** attempt))
                    continue

                response.raise_for_status()
                if is_generate and not self.reuse_captcha_token:
                    self.invalidate_captcha_token()
                return response
            except requests.exceptions.RequestException as e:
                last_error = e
                if (
                    is_generate
                    and attempt + 1 < attempts
                    and self.captcha_solver is not None
                ):
                    try:
                        self.invalidate_captcha_token()
                        fresh_token = self.resolve_captcha_token(force_refresh=True)
                        if fresh_token and isinstance(payload, dict):
                            payload = dict(payload)
                            payload["captchaToken"] = fresh_token
                            req_headers = dict(req_headers)
                            req_headers["x-captcha-token"] = fresh_token
                    except Exception as solver_err:
                        print(f"Error solving hCaptcha for {url}: {solver_err}")
                        break
                    if self.retry_delay > 0:
                        time.sleep(self.retry_delay * (2 ** attempt))
                    continue
                print(f"Error making {method} request to {url}: {e}")
                return None

        if last_error is not None:
            print(f"Error making {method} request to {url}: {last_error}")
        return None

    def get_headers(self, get_request=False, captcha_token: Optional[str] = None):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": self._build_cookie_header(),
            "Origin": "https://www.udio.com",
            "Referer": self.page_url,
            "User-Agent": self.USER_AGENT,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if not get_request:
            headers.update(
                {
                    "sec-ch-ua": '"Google Chrome";v="124", "Not:A-Brand";v="8", "Chromium";v="124"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"macOS"',
                    "sec-fetch-dest": "empty",
                }
            )
        if captcha_token:
            headers["x-captcha-token"] = captcha_token
        return headers

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
        captcha_token: Optional[str] = None,
    ):
        print("Starting the generation of the complete song sequence...")

        # Generate the short song
        print("Generating the short song...")
        short_song_result = self.create_song(
            short_prompt, seed, custom_lyrics_short, captcha_token=captcha_token
        )
        if not short_song_result:
            print("Error generating the short song.")
            return None

        last_song_result = short_song_result
        extend_song_results = []

        # Generate the extend songs
        for i in range(num_extensions):
            if i < len(extend_prompts):
                prompt = extend_prompts[i]
                lyrics = (
                    custom_lyrics_extend[i]
                    if custom_lyrics_extend and i < len(custom_lyrics_extend)
                    else None
                )
            else:
                prompt = extend_prompts[-1]  # Reuse the last prompt if not enough are provided
                lyrics = custom_lyrics_extend[-1] if custom_lyrics_extend else None

            print(f"Generating extend song {i + 1}...")
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]["song_path"],
                audio_conditioning_song_id=last_song_result[0]["id"],
                custom_lyrics=lyrics,
                captcha_token=captcha_token,
            )
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                return None

            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        # Generate the outro
        print("Generating the outro...")
        outro_song_result = self.add_outro(
            outro_prompt,
            seed,
            audio_conditioning_path=last_song_result[0]["song_path"],
            audio_conditioning_song_id=last_song_result[0]["id"],
            custom_lyrics=custom_lyrics_outro,
            captcha_token=captcha_token,
        )
        if not outro_song_result:
            print("Error generating the outro.")
            return None

        print("Complete song sequence generated and processed successfully.")
        return {
            "short_song": short_song_result,
            "extend_songs": extend_song_results,
            "outro_song": outro_song_result,
        }

    def create_song(self, prompt, seed=-1, custom_lyrics=None, captcha_token: Optional[str] = None):
        song_result = self.generate_song(
            prompt, seed, custom_lyrics, captcha_token=captcha_token
        )
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
        captcha_token: Optional[str] = None,
    ):
        extend_song_result = self.generate_extend_song(
            prompt,
            seed,
            audio_conditioning_path,
            audio_conditioning_song_id,
            custom_lyrics,
            captcha_token=captcha_token,
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
        captcha_token: Optional[str] = None,
    ):
        outro_result = self.generate_outro(
            prompt,
            seed,
            audio_conditioning_path,
            audio_conditioning_song_id,
            custom_lyrics,
            captcha_token=captcha_token,
        )
        if not outro_result:
            return None
        outro_track_ids = outro_result.get("track_ids", [])
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    def _prepare_generate_payload(
        self,
        data: Dict[str, Any],
        captcha_token: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, str]]:
        token = captcha_token or self.resolve_captcha_token(force_refresh=False)
        headers = self.get_headers(get_request=False, captcha_token=token)
        if token:
            data["captchaToken"] = token
        return data, headers

    def generate_song(
        self,
        prompt,
        seed=-1,
        custom_lyrics=None,
        captcha_token: Optional[str] = None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        data: Dict[str, Any] = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        data, headers = self._prepare_generate_payload(data, captcha_token=captcha_token)
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def generate_extend_song(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
        captcha_token: Optional[str] = None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        data: Dict[str, Any] = {
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
        data, headers = self._prepare_generate_payload(data, captcha_token=captcha_token)
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def generate_outro(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
        captcha_token: Optional[str] = None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        data: Dict[str, Any] = {
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
        data, headers = self._prepare_generate_payload(data, captcha_token=captcha_token)
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def process_songs(self, track_ids, folder):
        """Function to process generated songs, wait until they are ready, and download them."""
        print(f"Processing songs in {folder} with track_ids {track_ids}...")
        while True:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                print(f"Error checking song status for {folder}.")
                return None
            elif status_result.get("all_finished", False):
                songs = []
                for song in status_result["data"]["songs"]:
                    self.download_song(song["song_path"], song["title"], folder=folder)
                    songs.append(song)
                print(f"All songs in {folder} are ready and downloaded.")
                return songs
            else:
                time.sleep(5)

    def check_song_status(self, song_ids):
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(True)
        response = self.make_request(url, "GET", None, headers)
        if response:
            data = response.json()
            all_finished = all(song["finished"] for song in data["songs"])
            return {"all_finished": all_finished, "data": data}
        else:
            return None

    @staticmethod
    def _sanitize_filename(title: str) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|]+', "_", str(title or "").strip()).strip(". ")
        return cleaned or "untitled"

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        safe_title = self._sanitize_filename(song_title)
        file_path = os.path.join(folder, f"{safe_title}.mp3")
        try:
            response = self.session.get(song_url, timeout=self.timeout)
            response.raise_for_status()
            with open(file_path, "wb") as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")
