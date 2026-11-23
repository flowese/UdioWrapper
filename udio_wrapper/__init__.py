"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2026-11-23
Description: Generates songs using the Udio API using textual prompts with hCaptcha token resolution,
RFC-6265 cookie handling, and automatic retry/backoff on HTTP 500/429 challenges.
"""

import os
import time
from typing import Any, Callable, Dict, List, Optional
import requests


class UdioCaptchaRequiredError(RuntimeError):
    """Raised when Udio's generate-proxy endpoint requires a valid hCaptcha token."""


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"
    DEFAULT_HCAPTCHA_SITEKEY = "2945592b-1928-43a9-8473-7e7f45c52e4d"

    def __init__(
        self,
        auth_token: str,
        captcha_token: Optional[str] = None,
        captcha_solver: Optional[Callable[[str, str], str]] = None,
        extra_cookies: Optional[Dict[str, str]] = None,
        request_timeout: int = 30,
        max_retries: int = 3,
    ):
        if not auth_token or not str(auth_token).strip():
            raise ValueError("auth_token must be a non-empty string")
        self.auth_token = str(auth_token).strip()
        self.captcha_token = captcha_token or os.environ.get("UDIO_HCAPTCHA_TOKEN")
        self.captcha_solver = captcha_solver
        self.extra_cookies = dict(extra_cookies or {})
        self.request_timeout = request_timeout
        self.max_retries = max(1, int(max_retries))
        self.session = requests.Session()
        self.all_track_ids: List[str] = []

    def resolve_captcha_token(self, force_refresh: bool = False) -> Optional[str]:
        """Resolves an hCaptcha token from explicit config, environment, or solver callback."""
        if not force_refresh and self.captcha_token:
            return self.captcha_token
        if callable(self.captcha_solver):
            solved = self.captcha_solver(
                self.DEFAULT_HCAPTCHA_SITEKEY,
                f"{self.API_BASE_URL}/generate-proxy",
            )
            if solved and str(solved).strip():
                self.captcha_token = str(solved).strip()
                return self.captcha_token
        env_token = os.environ.get("UDIO_HCAPTCHA_TOKEN")
        if env_token and env_token.strip():
            self.captcha_token = env_token.strip()
            return self.captcha_token
        return self.captcha_token

    def _build_cookie_header(self) -> str:
        """Builds an RFC-6265 compliant Cookie header without leading semicolons."""
        cookie_parts = [f"sb-api-auth-token={self.auth_token}"]
        for key, value in self.extra_cookies.items():
            clean_key = str(key).strip()
            clean_val = str(value).strip()
            if clean_key and clean_val and clean_key != "sb-api-auth-token":
                cookie_parts.append(f"{clean_key}={clean_val}")
        return "; ".join(cookie_parts)

    def make_request(
        self,
        url: str,
        method: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[requests.Response]:
        req_headers = dict(headers or self.get_headers(get_request=(method.upper() == "GET")))
        payload = dict(data) if isinstance(data, dict) else data

        for attempt in range(1, self.max_retries + 1):
            try:
                if method.upper() == "POST":
                    response = self.session.post(
                        url,
                        headers=req_headers,
                        json=payload,
                        timeout=self.request_timeout,
                    )
                else:
                    response = self.session.get(
                        url,
                        headers=req_headers,
                        timeout=self.request_timeout,
                    )

                if response.status_code in (403, 429, 500) and url.endswith("/generate-proxy"):
                    body_text = (response.text or "").lower()
                    needs_captcha = (
                        "captcha" in body_text
                        or response.status_code == 500
                        or not (isinstance(payload, dict) and payload.get("captchaToken"))
                    )
                    if needs_captcha and callable(self.captcha_solver) and attempt < self.max_retries:
                        fresh_token = self.resolve_captcha_token(force_refresh=True)
                        if fresh_token and isinstance(payload, dict):
                            payload["captchaToken"] = fresh_token
                            req_headers["x-hcaptcha-token"] = fresh_token
                            time.sleep(min(2 ** (attempt - 1), 4))
                            continue

                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt - 1), 4))
                    continue
                print(f"Error making {method} request to {url}: {e}")
                return None
        return None

    def get_headers(self, get_request: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": self._build_cookie_header(),
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
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
            token = self.resolve_captcha_token(force_refresh=False)
            if token:
                headers["x-hcaptcha-token"] = token
        return headers

    def _build_generation_payload(
        self,
        prompt: str,
        sampler_options: Dict[str, Any],
        custom_lyrics: Optional[str] = None,
        captcha_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "prompt": prompt,
            "samplerOptions": sampler_options,
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        resolved_captcha = captcha_token or self.resolve_captcha_token(force_refresh=False)
        if resolved_captcha:
            data["captchaToken"] = resolved_captcha
        return data

    def create_complete_song(
        self,
        short_prompt: str,
        extend_prompts: List[str],
        outro_prompt: str,
        seed: int = -1,
        custom_lyrics_short: Optional[str] = None,
        custom_lyrics_extend: Optional[List[str]] = None,
        custom_lyrics_outro: Optional[str] = None,
        num_extensions: int = 1,
    ):
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
                lyrics = (
                    custom_lyrics_extend[i]
                    if custom_lyrics_extend and i < len(custom_lyrics_extend)
                    else None
                )
            else:
                prompt = extend_prompts[-1]
                lyrics = custom_lyrics_extend[-1] if custom_lyrics_extend else None

            print(f"Generating extend song {i + 1}...")
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]["song_path"],
                audio_conditioning_song_id=last_song_result[0]["id"],
                custom_lyrics=lyrics,
            )
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                return None
            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        print("Generating the outro song...")
        outro_song_result = self.add_outro(
            outro_prompt,
            seed,
            audio_conditioning_path=last_song_result[0]["song_path"],
            audio_conditioning_song_id=last_song_result[0]["id"],
            custom_lyrics=custom_lyrics_outro,
        )
        if not outro_song_result:
            print("Error generating the outro song.")
            return None

        print("Complete song sequence generated and downloaded successfully.")
        return {
            "short_song": short_song_result,
            "extend_songs": extend_song_results,
            "outro_song": outro_song_result,
        }

    def create_song(
        self,
        prompt: str,
        seed: int = -1,
        custom_lyrics: Optional[str] = None,
        captcha_token: Optional[str] = None,
    ):
        song_result = self.generate_song(prompt, seed, custom_lyrics, captcha_token=captcha_token)
        if not song_result:
            return None
        track_ids = song_result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "short_songs")

    def extend(
        self,
        prompt: str,
        seed: int = -1,
        audio_conditioning_path: Optional[str] = None,
        audio_conditioning_song_id: Optional[str] = None,
        custom_lyrics: Optional[str] = None,
        captcha_token: Optional[str] = None,
    ):
        extend_result = self.generate_extend_song(
            prompt,
            seed,
            audio_conditioning_path,
            audio_conditioning_song_id,
            custom_lyrics,
            captcha_token=captcha_token,
        )
        if not extend_result:
            return None
        extend_track_ids = extend_result.get("track_ids", [])
        self.all_track_ids.extend(extend_track_ids)
        return self.process_songs(extend_track_ids, "extend_songs")

    def add_outro(
        self,
        prompt: str,
        seed: int = -1,
        audio_conditioning_path: Optional[str] = None,
        audio_conditioning_song_id: Optional[str] = None,
        custom_lyrics: Optional[str] = None,
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

    def generate_song(
        self,
        prompt: str,
        seed: int,
        custom_lyrics: Optional[str] = None,
        captcha_token: Optional[str] = None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = self._build_generation_payload(
            prompt=prompt,
            sampler_options={"seed": seed},
            custom_lyrics=custom_lyrics,
            captcha_token=captcha_token,
        )
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def generate_extend_song(
        self,
        prompt: str,
        seed: int,
        audio_conditioning_path: Optional[str],
        audio_conditioning_song_id: Optional[str],
        custom_lyrics: Optional[str] = None,
        captcha_token: Optional[str] = None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = self._build_generation_payload(
            prompt=prompt,
            sampler_options={
                "seed": seed,
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
            },
            custom_lyrics=custom_lyrics,
            captcha_token=captcha_token,
        )
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def generate_outro(
        self,
        prompt: str,
        seed: int,
        audio_conditioning_path: Optional[str],
        audio_conditioning_song_id: Optional[str],
        custom_lyrics: Optional[str] = None,
        captcha_token: Optional[str] = None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = self._build_generation_payload(
            prompt=prompt,
            sampler_options={
                "seed": seed,
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
                "crop_start_time": 0.9,
            },
            custom_lyrics=custom_lyrics,
            captcha_token=captcha_token,
        )
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def process_songs(self, track_ids: List[str], folder: str):
        """Function to process generated songs, wait until they are ready, and download them."""
        print(f"Processing songs in {folder} with track_ids {track_ids}...")
        while True:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                print(f"Error checking song status for {folder}.")
                return None
            if status_result.get("all_finished", False):
                songs = []
                for song in status_result["data"]["songs"]:
                    self.download_song(song["song_path"], song["title"], folder=folder)
                    songs.append(song)
                print(f"All songs in {folder} are ready and downloaded.")
                return songs
            time.sleep(5)

    def check_song_status(self, song_ids: List[str]):
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(True)
        response = self.make_request(url, "GET", None, headers)
        if response:
            data = response.json()
            all_finished = all(song["finished"] for song in data["songs"])
            return {"all_finished": all_finished, "data": data}
        return None

    def download_song(self, song_url: str, song_title: str, folder: str = "downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        safe_title = "".join(c if c not in '\\/:*?"<>|' else "_" for c in str(song_title))
        file_path = os.path.join(folder, f"{safe_title}.mp3")
        try:
            response = self.session.get(song_url, timeout=self.request_timeout)
            response.raise_for_status()
            with open(file_path, "wb") as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")
