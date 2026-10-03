"""
Udio Wrapper
Author: Flowese
Version: 0.0.5
Date: 2026-10-04
Description: Generates songs using the Udio API using textual prompts.
"""

import os
import re
import time

import requests

from .browser_client import BrowserClientError, UdioBrowserClient  # noqa: F401

UDIO_NO_PUBLIC_API = (
    "Udio does not offer a public API "
    "(https://help.udio.com/en/articles/10756277-udio-public-api). "
    "This package calls the unofficial website endpoint POST /api/generate-proxy."
)


class UdioError(RuntimeError):
    """Base error for UdioWrapper."""


class UdioAuthError(UdioError):
    """401: the auth cookie was rejected."""


class UdioChallengeError(UdioError):
    """Verification/bot-protection refusal (HTTP 403/500/503 or captcha keywords)."""


class UdioAPIError(UdioError):
    """HTTP failure talking to an unofficial Udio website endpoint."""

    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(self, auth_token, cookie_name="sb-api-auth-token", max_retries=3,
                 request_timeout=30, raise_on_error=False):
        self.auth_token = auth_token
        self.cookie_name = cookie_name
        self.max_retries = max(1, int(max_retries))
        self.request_timeout = request_timeout
        self.raise_on_error = raise_on_error
        self.all_track_ids = []

    # ---- diagnostics (never used to bypass anything) ----

    def is_challenge_block(self, response):
        if response is None:
            return False
        status = getattr(response, "status_code", None)
        if status in (403, 500, 503):
            return True
        try:
            body = (getattr(response, "text", "") or "").lower()
        except Exception:
            return False
        return any(k in body for k in ("captcha", "challenge", "bot", "verify"))

    def is_retryable_status(self, code):
        return code in (429, 500, 502, 503, 504)

    def get_challenge_guidance(self, status=None, url=None):
        return (
            f"Udio refused the request ({status or 'verification required'}) at "
            f"{url or 'the generate endpoint'}. This is Udio's human-verification "
            "bot protection; this wrapper does not extract, replay, or solve "
            "CAPTCHA tokens (that would violate Udio's ToS).\n"
            "Manual steps:\n"
            "  1. Open https://www.udio.com/ in your own browser and sign in.\n"
            "  2. Complete any verification challenge the site shows you.\n"
            "  3. Run one generation from the Udio site UI yourself.\n"
            "  4. Copy a fresh auth cookie from your browser session: either "
            "'sb-api-auth-token' or 'sb-ssr-production-auth-token'.\n"
            "  5. Re-run your script, passing that cookie (set cookie_name to the "
            "matching name) and pausing between requests."
        )

    def get_auth_guidance(self, body=None):
        return (
            "Udio returned HTTP 401 Unauthorized. Your auth cookie is missing, "
            "expired, or was renamed. Sign in again at https://www.udio.com/, "
            "copy a fresh 'sb-api-auth-token' or 'sb-ssr-production-auth-token' "
            "cookie value, and pass it to UdioWrapper (set cookie_name to the "
            "one you used). Do not commit secrets to source control."
        )

    # ---- request layer ----

    def _emit_error(self, message, status_code=None, body=None, exc=None):
        print(message)
        if self.raise_on_error:
            raise exc(message) if exc is not None else UdioError(message)
        return None

    def make_request(self, url, method, data=None, headers=None):
        last_response = None
        for attempt in range(self.max_retries):
            try:
                if method == 'POST':
                    response = requests.post(url, headers=headers, json=data,
                                             timeout=self.request_timeout)
                else:
                    response = requests.get(url, headers=headers,
                                            timeout=self.request_timeout)
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                print(f"Error making {method} request to {url}: {e}")
                if self._is_generate_proxy(url):
                    message = f"Network error calling generate-proxy: {e}"
                    if self.raise_on_error:
                        raise UdioAPIError(message) from e
                    return None
                return None

            if response.ok:
                return response

            last_response = response
            print(f"Error making {method} request to {url}: "
                  f"{response.status_code} {response.reason}")
            body = (response.text or "").strip()[:500]
            if body:
                print(f"Response body: {body}")

            if response.status_code == 401:
                guidance = self.get_auth_guidance(body)
                print(guidance)
                if self.raise_on_error:
                    raise UdioAuthError(guidance)
                return None

            if self.is_retryable_status(response.status_code) and attempt < self.max_retries - 1:
                time.sleep(min(2 ** attempt, 8))
                continue
            break

        body = (getattr(last_response, "text", "") or "").strip()[:500] if last_response is not None else ""
        status = getattr(last_response, "status_code", None)
        if self._is_generate_proxy(url):
            if last_response is not None and self.is_challenge_block(last_response):
                guidance = self.get_challenge_guidance(status, url)
                print(guidance)
                if self.raise_on_error:
                    raise UdioChallengeError(guidance)
                return None
            message = (
                f"{UDIO_NO_PUBLIC_API} HTTP {status} is an upstream rejection of "
                "this unofficial client (changed contract, extra browser checks, "
                "or a server error). This repository cannot restore the April 2024 "
                "generate-proxy behavior on its own."
            )
            if self.raise_on_error:
                raise UdioAPIError(message, status_code=status, body=body)
            print(message)
            return None
        return None

    def _is_generate_proxy(self, url):
        return url.rstrip("/").endswith("/generate-proxy")

    def get_headers(self, get_request=False):
        return {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Cookie": f"{self.cookie_name}={(self.auth_token or '').strip()}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }

    # ---- generation API ----

    def create_complete_song(self, short_prompt, extend_prompts, outro_prompt, seed=-1,
                             custom_lyrics_short=None, custom_lyrics_extend=None,
                             custom_lyrics_outro=None, num_extensions=1):
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
            extend_song_result = self.extend(
                prompt, seed,
                audio_conditioning_path=last_song_result[0].get('song_path'),
                audio_conditioning_song_id=last_song_result[0].get('id'),
                custom_lyrics=lyrics,
            )
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                return None
            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        print("Generating the outro...")
        outro_song_result = self.add_outro(
            outro_prompt, seed,
            audio_conditioning_path=last_song_result[0].get('song_path'),
            audio_conditioning_song_id=last_song_result[0].get('id'),
            custom_lyrics=custom_lyrics_outro,
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

    def create_song(self, prompt, seed=-1, custom_lyrics=None):
        try:
            song_result = self.generate_song(prompt, seed, custom_lyrics)
        except UdioAPIError:
            return None
        if not song_result:
            return None
        track_ids = song_result.get('track_ids') or []
        if not track_ids:
            print("generate-proxy returned no track_ids.")
            return None
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "short_songs")

    def extend(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        try:
            extend_song_result = self.generate_extend_song(
                prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics
            )
        except UdioAPIError:
            return None
        if not extend_song_result:
            return None
        extend_track_ids = extend_song_result.get('track_ids') or []
        if not extend_track_ids:
            print("generate-proxy returned no track_ids.")
            return None
        self.all_track_ids.extend(extend_track_ids)
        return self.process_songs(extend_track_ids, "extend_songs")

    def add_outro(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        try:
            outro_result = self.generate_outro(
                prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics
            )
        except UdioAPIError:
            return None
        if not outro_result:
            return None
        outro_track_ids = outro_result.get('track_ids') or []
        if not outro_track_ids:
            print("generate-proxy returned no track_ids.")
            return None
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    def generate_song(self, prompt, seed, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, 'POST', data, headers)
        return self._parse_json(response)

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
        return self._parse_json(response)

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
        return self._parse_json(response)

    def _parse_json(self, response):
        if response is None:
            return None
        try:
            return response.json()
        except ValueError:
            snippet = (getattr(response, "text", "") or "")[:200]
            print(f"Could not parse JSON response: {snippet}")
            return None

    def process_songs(self, track_ids, folder, max_attempts=72, poll_interval=5):
        """Wait until generated songs are ready, download them, return the list."""
        if not track_ids:
            print("No track_ids given.")
            return None
        print(f"Processing songs in {folder} with track_ids {track_ids}...")
        for _ in range(max_attempts):
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                print(f"Error checking song status for {folder}.")
                return None
            if status_result.get('all_finished', False):
                songs = []
                for song in status_result.get('data', {}).get('songs', []):
                    if song.get('moderation') is True:
                        print(f"Skipping moderated song {song.get('id')}.")
                        continue
                    if not song.get('song_path'):
                        print(f"Skipping song without song_path: {song.get('id')}.")
                        continue
                    self.download_song(song['song_path'], song.get('title', 'track'), folder=folder)
                    songs.append(song)
                print(f"All songs in {folder} are ready and downloaded.")
                return songs
            time.sleep(poll_interval)
        print(f"Timed out waiting for songs in {folder}.")
        return None

    def check_song_status(self, song_ids):
        if not song_ids:
            print("No song_ids given.")
            return None
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(True)
        response = self.make_request(url, 'GET', None, headers)
        if response is None:
            return None
        try:
            data = response.json()
        except ValueError:
            print("Could not parse song status JSON.")
            return None
        songs = data.get('songs', [])
        all_finished = bool(songs) and all(song.get('finished') for song in songs)
        return {'all_finished': all_finished, 'data': data}

    def _sanitize_filename(self, name, max_length=120):
        name = re.sub(r'[\\/:*?"<>|]', '', str(name or ''))
        name = re.sub(r'\s+', ' ', name).strip()
        return name[:max_length] or "track"

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{self._sanitize_filename(song_title)}.mp3")
        try:
            response = requests.get(song_url, timeout=self.request_timeout)
            response.raise_for_status()
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
            return file_path
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")
            return None
