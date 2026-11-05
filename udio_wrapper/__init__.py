"""
Udio Wrapper
Author: Flowese (Enhanced with hCaptcha resolution for Issue #7)
Version: 0.0.4
Description: Generates songs using the Udio API using textual prompts with hCaptcha support.
"""

import os
import time
import requests
from udio_wrapper.hcaptcha_solver import (
    HCaptchaSolver,
    is_hcaptcha_challenge,
    UDIO_HCAPTCHA_SITEKEY,
    UDIO_SITE_URL,
)


class UdioAPIError(Exception):
    """Base exception for Udio API errors."""
    pass


class CaptchaRequiredError(UdioAPIError):
    """Raised when Udio requires hCaptcha verification on /api/generate-proxy."""
    pass


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(
        self,
        auth_token,
        captcha_token=None,
        captcha_solver=None,
        captcha_api_key=None,
        captcha_service=None,
    ):
        self.auth_token = auth_token
        self.captcha_token = captcha_token or os.environ.get("UDIO_CAPTCHA_TOKEN")
        self.captcha_solver = captcha_solver
        self._solver_instance = None

        if captcha_api_key or os.getenv("CAPTCHA_API_KEY") or os.getenv("CAPSOLVER_API_KEY") or os.getenv("TWOCAPTCHA_API_KEY"):
            self._solver_instance = HCaptchaSolver(
                api_key=captcha_api_key,
                service=captcha_service,
                sitekey=UDIO_HCAPTCHA_SITEKEY,
                site_url=UDIO_SITE_URL,
            )

        self.all_track_ids = []

    def resolve_captcha_token(self, force_refresh=False):
        """
        Resolves an hCaptcha token from configured sources:
        1. Explicit self.captcha_token or UDIO_CAPTCHA_TOKEN
        2. Dynamic callback (self.captcha_solver)
        3. Automated solver (self._solver_instance: 2captcha / capsolver)
        """
        if self.captcha_token and not force_refresh:
            return self.captcha_token

        if callable(self.captcha_solver):
            try:
                token = self.captcha_solver()
                if token:
                    return token
            except Exception as e:
                print(f"[UdioWrapper] captcha_solver callback error: {e}")

        if self._solver_instance:
            token = self._solver_instance.get_token(force=force_refresh)
            if token:
                return token

        return self.captcha_token

    def make_request(self, url, method, data=None, headers=None):
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.get(url, headers=headers)
            
            # If Udio triggers a challenge, return response directly so diagnosis can inspect it
            if is_hcaptcha_challenge(response):
                return response

            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            resp = getattr(e, "response", None)
            if resp is not None and is_hcaptcha_challenge(resp):
                return resp
            print(f"Error making {method} request to {url}: {e}")
            return None

    def get_headers(self, get_request=False, captcha_token=None):
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
        if captcha_token:
            headers["h-captcha-response"] = captcha_token
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
        captcha_token=None,
    ):
        print("Starting the generation of the complete song sequence...")

        # Generate the short song
        print("Generating the short song...")
        short_song_result = self.create_song(short_prompt, seed, custom_lyrics_short, captcha_token=captcha_token)
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
                prompt = extend_prompts[-1]
                lyrics = custom_lyrics_extend[-1] if custom_lyrics_extend else None

            print(f"Generating extend song {i + 1}...")
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]['song_path'],
                audio_conditioning_song_id=last_song_result[0]['id'],
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
            audio_conditioning_path=last_song_result[0]['song_path'],
            audio_conditioning_song_id=last_song_result[0]['id'],
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
            "outro_song": outro_song_result
        }

    def create_song(self, prompt, seed=-1, custom_lyrics=None, captcha_token=None):
        song_result = self.generate_song(prompt, seed, custom_lyrics, captcha_token=captcha_token)
        if not song_result:
            return None
        track_ids = song_result.get('track_ids', [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "short_songs")

    def extend(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None, captcha_token=None):
        extend_song_result = self.generate_extend_song(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics, captcha_token=captcha_token
        )
        if not extend_song_result:
            return None
        extend_track_ids = extend_song_result.get('track_ids', [])
        self.all_track_ids.extend(extend_track_ids)
        return self.process_songs(extend_track_ids, "extend_songs")

    def add_outro(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None, captcha_token=None):
        outro_result = self.generate_outro(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics, captcha_token=captcha_token
        )
        if not outro_result:
            return None
        outro_track_ids = outro_result.get('track_ids', [])
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    def _post_generate_proxy(self, payload, captcha_token=None):
        """
        Handles requests to /api/generate-proxy, ensuring hCaptcha token injection
        and providing clear diagnosis for 500 / captcha challenges (Fixes Issue #7).
        """
        url = f"{self.API_BASE_URL}/generate-proxy"
        token = captcha_token or self.resolve_captcha_token()

        data = dict(payload)
        if token:
            data["captchaToken"] = token

        headers = self.get_headers(get_request=False, captcha_token=token)
        response = self.make_request(url, 'POST', data, headers)

        # If a 500 challenge or captcha block is encountered, try refreshing via solver
        if response is not None and is_hcaptcha_challenge(response):
            if (callable(self.captcha_solver) or self._solver_instance) and not captcha_token:
                print("[UdioWrapper] Received 500 / Captcha Challenge from Udio. Attempting to refresh hCaptcha token...")
                fresh_token = self.resolve_captcha_token(force_refresh=True)
                if fresh_token:
                    data["captchaToken"] = fresh_token
                    headers = self.get_headers(get_request=False, captcha_token=fresh_token)
                    response = self.make_request(url, 'POST', data, headers)

        if response is None:
            return None

        status = getattr(response, "status_code", 0)
        if not (200 <= status < 300):
            if is_hcaptcha_challenge(response) or status == 500:
                print(
                    "\n" + "=" * 70 + "\n"
                    f"[UdioWrapper] 500 Server Error on /api/generate-proxy (Issue #7).\n"
                    f"Udio requires an hCaptcha verification token for music generation.\n"
                    f"To fix this error, you can:\n"
                    f"  1. Pass captcha_token='...' to UdioWrapper or export UDIO_CAPTCHA_TOKEN=...\n"
                    f"  2. Provide a dynamic solver callback: UdioWrapper(auth_token, captcha_solver=my_callback)\n"
                    f"  3. Configure an automated service: UdioWrapper(auth_token, captcha_api_key='...', captcha_service='2captcha'|'capsolver')\n"
                    f"Udio hCaptcha Sitekey: {UDIO_HCAPTCHA_SITEKEY}\n"
                    f"Server Response ({status}): {getattr(response, 'text', '')[:200]}\n"
                    + "=" * 70 + "\n"
                )
            return None

        try:
            return response.json()
        except Exception as e:
            print(f"[UdioWrapper] Error parsing generation response JSON: {e}")
            return None

    def generate_song(self, prompt, seed=-1, custom_lyrics=None, captcha_token=None):
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        return self._post_generate_proxy(data, captcha_token=captcha_token)

    def generate_extend_song(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None, captcha_token=None):
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
        return self._post_generate_proxy(data, captcha_token=captcha_token)

    def generate_outro(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None, captcha_token=None):
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
        return self._post_generate_proxy(data, captcha_token=captcha_token)

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
        if response and getattr(response, "status_code", 0) == 200:
            try:
                data = response.json()
                all_finished = all(song.get('finished', False) for song in data.get('songs', []))
                return {'all_finished': all_finished, 'data': data}
            except Exception:
                return None
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
