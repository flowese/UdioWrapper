"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2024-04-15
Description: Generates songs using the Udio API using textual prompts.
Fixes #7: 500 Server Error - hCaptcha handling (auto solve hook + retry)
"""

import requests
import os
import time
import logging
from typing import Optional, Callable

from .hcaptcha_solver import HCaptchaSolver, is_hcaptcha_blocked

logger = logging.getLogger(__name__)


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"
    # Udio's hCaptcha sitekey for generate-proxy endpoint
    HCAPTCHA_SITEKEY = "2945592b-1928-43a9-8473-7e7fed3d752e"

    def __init__(
        self,
        auth_token: str,
        captcha_api_key: Optional[str] = None,
        captcha_service: Optional[str] = None,
        captcha_callback: Optional[Callable[[], Optional[str]]] = None,
        hcaptcha_token: Optional[str] = None,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ):
        """
        Initialize UdioWrapper with authentication and optional captcha handling.

        :param auth_token: sb-api-auth-token cookie value from Udio
        :param captcha_api_key: API key for 2captcha or Capsolver service
        :param captcha_service: "2captcha" or "capsolver"
        :param captcha_callback: Optional callable that returns an hCaptcha token.
            If provided, will be called when hCaptcha is detected. Useful for
            manual solving or custom captcha-solving integrations.
        :param hcaptcha_token: Pre-computed hCaptcha token to inject in requests
        :param max_retries: Maximum retry attempts for failed requests
        :param retry_backoff: Base backoff time in seconds between retries
        """
        self.auth_token = auth_token
        self.all_track_ids = []

        # hCaptcha handling configuration
        self._hcaptcha_token = hcaptcha_token
        self._captcha_callback = captcha_callback
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._captcha_solver = HCaptchaSolver(
            api_key=captcha_api_key, service=captcha_service
        )

        # Track retry state for current operation
        self._last_captcha_response = None

    # ------------------------------------------------------------------ helpers
    def _is_captcha_response(self, response) -> bool:
        """Heuristic: 500 from generate-proxy after hCaptcha rollout."""
        if response is None:
            return False
        if response.status_code != 500:
            return False
        try:
            body = (response.text or "").lower()
        except Exception:
            body = ""
        # Udio returns generic 500 but issue comments confirm hCaptcha rollout.
        # Treat any 500 on generate-proxy as possibly captcha-triggered so
        # caller gets actionable error instead of silent None.
        if "generate-proxy" in (response.url or ""):
            # If body mentions captcha/hcaptcha, definitely captcha.
            if any(k in body for k in ("captcha", "hcaptcha", "challenge", "blocked")):
                return True
            # Otherwise still flag as captcha-suspected to surface guidance
            return True
        return any(k in body for k in ("captcha", "hcaptcha"))

    def _get_captcha_token(self) -> Optional[str]:
        """Get hCaptcha token from static value, callback, or solver service."""
        if self._hcaptcha_token:
            return self._hcaptcha_token
        if self._captcha_callback is not None:
            try:
                token = self._captcha_callback()
                if token:
                    logger.info("Obtained hCaptcha token via captcha_callback")
                    return token
            except Exception as e:
                logger.warning(f"captcha_callback failed: {e}")
        # Fall back to configured solver service
        return self._captcha_solver.get_token()

    def _inject_captcha(self, data: dict, headers: dict, token: Optional[str]):
        """Inject hCaptcha token into request data and headers."""
        if not token:
            return
        # Udio's frontend sends token under several possible keys depending on version.
        # Inject under all commonly observed keys so at least one is accepted.
        # Body:
        data["captchaToken"] = token
        data["hcaptchaToken"] = token
        data["hCaptchaToken"] = token
        # Some WAFs also expect header
        headers["x-captcha-token"] = token
        headers["x-hcaptcha-token"] = token

    def _post_generate(self, data: dict) -> Optional[dict]:
        """
        Internal POST to /generate-proxy with hCaptcha + retry handling.
        Retries on captcha detection if a token/callback is available,
        otherwise fails fast with guidance. Also retries transient 500 with backoff.
        """
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        # Inject static token if present on first attempt
        token = self._get_captcha_token()
        if token:
            self._inject_captcha(data, headers, token)

        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.make_request(url, 'POST', data, headers)
                # make_request returns None on non-captcha HTTP errors
                if response is None:
                    # Transient failure: retry with backoff if attempts left
                    if attempt < self.max_retries:
                        sleep_s = self.retry_backoff * (2 ** attempt)
                        logger.info(f"Retrying generate-proxy in {sleep_s:.1f}s (attempt {attempt+1}/{self.max_retries})")
                        time.sleep(sleep_s)
                        continue
                    return None
                return response.json() if response else None
            except requests.exceptions.HTTPError as e:
                resp = e.response if hasattr(e, 'response') else None
                last_exc = e
                # Surface captcha-specific error
                if resp is not None and self._is_captcha_response(resp):
                    logger.warning(
                        f"Captcha likely required for {url}: {resp.status_code} {resp.text[:500] if resp.text else ''}"
                    )
                    print(
                        f"[UdioWrapper] 500 on {url} looks like hCaptcha challenge. "
                        f"Provide hcaptcha_token or captcha_callback to auto-solve. "
                        f"See https://github.com/flowese/UdioWrapper/issues/7"
                    )
                    # Try to obtain a fresh token via callback
                    fresh = None
                    if self._captcha_callback is not None:
                        try:
                            fresh = self._captcha_callback()
                        except Exception as cb_e:
                            logger.warning(f"captcha_callback error on retry: {cb_e}")
                    # Also accept updated self._hcaptcha_token if caller set it
                    if not fresh:
                        fresh = self._hcaptcha_token
                    if fresh and fresh != token:
                        token = fresh
                        logger.info(f"Retrying generate-proxy with fresh hCaptcha token (attempt {attempt+1})")
                        self._inject_captcha(data, headers, token)
                        continue
                    # If we have a token but same one failed, or no callback, try once more with current token
                    if token and attempt == 0:
                        # First captcha error even though we sent a token -> token may be stale,
                        # try to re-fetch via callback once more
                        if self._captcha_callback is not None:
                            time.sleep(1)
                            continue
                    # No way to recover
                    print(
                        f"[UdioWrapper] hCaptcha required and no fresh token available. "
                        f"Solve the captcha in browser, copy the hcaptcha token, and pass it as "
                        f"UdioWrapper(auth_token, hcaptcha_token='...') or "
                        f"UdioWrapper(auth_token, captcha_callback=lambda: solve(...))."
                    )
                    return None
                # Transient 500: retry with backoff
                if attempt < self.max_retries:
                    sleep_s = self.retry_backoff * (2 ** attempt)
                    logger.info(f"Retrying generate-proxy in {sleep_s:.1f}s (attempt {attempt+1}/{self.max_retries})")
                    time.sleep(sleep_s)
                    continue
                print(f"Error making POST request to {url}: {e}")
                if resp is not None:
                    try:
                        print(f"Response body: {resp.text[:1000]}")
                    except Exception:
                        pass
                return None
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt < self.max_retries:
                    sleep_s = self.retry_backoff * (2 ** attempt)
                    logger.info(f"Retrying generate-proxy in {sleep_s:.1f}s (attempt {attempt+1}/{self.max_retries})")
                    time.sleep(sleep_s)
                    continue
                print(f"Error making POST request to {url}: {e}")
                return None
        if last_exc is not None:
            raise last_exc
        return None

    def make_request(self, url, method, data=None, headers=None, max_retries=2):
        """
        Make an HTTP request with basic retry logic.
        For generate-proxy, use _post_generate instead which handles hCaptcha.
        """
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            resp = e.response if hasattr(e, 'response') else None
            if resp is not None and self._is_captcha_response(resp):
                logger.warning(
                    f"Captcha likely required for {url}: {resp.status_code} {resp.text[:500] if resp.text else ''}"
                )
                print(
                    f"[UdioWrapper] 500 on {url} looks like hCaptcha challenge. "
                    f"Provide hcaptcha_token or captcha_callback to auto-solve. "
                    f"See https://github.com/flowese/UdioWrapper/issues/7"
                )
            print(f"Error making {method} request to {url}: {e}")
            if resp is not None:
                try:
                    print(f"Response body: {resp.text[:1000]}")
                except Exception:
                    pass
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error making {method} request to {url}: {e}")
            return None

    def get_headers(self, get_request=False):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty"
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "sec-fetch-dest": "empty"
            })
        return headers

    def create_complete_song(self, short_prompt, extend_prompts, outro_prompt, seed=-1, custom_lyrics_short=None, custom_lyrics_extend=None, custom_lyrics_outro=None, num_extensions=1):
        print("Starting the generation of the complete song sequence...")

        # Generate the short song
        print("Generating the short song...")
        short_song_result = self.create_song(short_prompt, seed, custom_lyrics_short)
        if not short_song_result:
            print("Error generating the short song.")
            return None

        last_song_result = short_song_result
        extend_song_results = []

        # Generate the extend songs
        for i in range(num_extensions):
            if i < len(extend_prompts):
                prompt = extend_prompts[i]
                lyrics = custom_lyrics_extend[i] if custom_lyrics_extend and i < len(custom_lyrics_extend) else None
            else:
                prompt = extend_prompts[-1]  # Reuse the last prompt if not enough are provided
                lyrics = custom_lyrics_extend[-1] if custom_lyrics_extend else None

            print(f"Generating extend song {i + 1}...")
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]['song_path'],
                audio_conditioning_song_id=last_song_result[0]['id'],
                custom_lyrics=lyrics
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
            audio_conditioning_path=last_song_result[0]['song_path'],
            audio_conditioning_song_id=last_song_result[0]['id'],
            custom_lyrics=custom_lyrics_outro
        )
        if not outro_song_result:
            print("Error generating the outro.")
            return None

        print("Complete song sequence generated and processed successfully.")
        return {
            "short_song": short_song_result,
            "extend_songs": extend_song_results,
            "outro_song": outro_song_result
        }

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
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        return self._post_generate(data)

    def generate_extend_song(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        data = {
            "prompt": prompt,
            "samplerOptions": {
                "seed": seed,
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation"
            }
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        return self._post_generate(data)

    def generate_outro(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        data = {
            "prompt": prompt,
            "samplerOptions": {
                "seed": seed,
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
                "crop_start_time": 0.9
            }
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        return self._post_generate(data)

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
            data = response.json()
            all_finished = all(song['finished'] for song in data['songs'])
            return {'all_finished': all_finished, 'data': data}
        else:
            return None

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{song_title}.mp3")
        try:
            response = requests.get(song_url)
            response.raise_for_status()
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")