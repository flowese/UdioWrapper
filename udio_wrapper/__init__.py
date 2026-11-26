"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2024-11-26
Description: Generates songs using the Udio API using textual prompts.
"""

import requests
import os
import time
import json


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(self, auth_token, debug=False):
        self.auth_token = auth_token
        self.all_track_ids = []
        self.debug = debug

    def make_request(self, url, method, data=None, headers=None):
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=60)
            else:
                response = requests.get(url, headers=headers, timeout=60)

            # Print response details in debug mode
            if self.debug:
                print(f"[DEBUG] {method} {url}")
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response headers: {dict(response.headers)}")
                try:
                    print(f"[DEBUG] Response body: {response.text[:2000]}")
                except Exception:
                    print("[DEBUG] Response body: <binary or empty>")

            # Check for CAPTCHA challenge in response
            if response.status_code == 500:
                try:
                    error_data = response.json()
                    if self._is_captcha_error(error_data):
                        raise CaptchaRequiredError(
                            "Udio API returned a CAPTCHA challenge. "
                            "This wrapper cannot automatically solve CAPTCHAs. "
                            "You may need to solve the CAPTCHA manually in a browser first, "
                            "or use a CAPTCHA solving service."
                        )
                except json.JSONDecodeError:
                    pass

            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            print(f"Error: Request to {url} timed out after 60 seconds")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error making {method} request to {url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status: {e.response.status_code}")
                try:
                    print(f"Response body: {e.response.text[:2000]}")
                except Exception:
                    print("Response body: <could not read>")
            return None

    def _is_captcha_error(self, error_data):
        """Check if the error response indicates a CAPTCHA challenge."""
        if not isinstance(error_data, dict):
            return False
        # Common indicators of CAPTCHA in error responses
        error_str = json.dumps(error_data).lower()
        captcha_indicators = ['captcha', 'hcaptcha', 'turnstile', 'challenge', 'recaptcha']
        return any(indicator in error_str for indicator in captcha_indicators)

    def get_headers(self, get_request=False):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="131", "Not:A-Brand";v="8", "Chromium";v="131"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
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
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, 'POST', data, headers)
        return response.json() if response else None

    def generate_extend_song(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
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
        response = self.make_request(url, 'POST', data, headers)
        return response.json() if response else None

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
                "crop_start_time": 0.9
            }
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, 'POST', data, headers)
        return response.json() if response else None

    def process_songs(self, track_ids, folder):
        """Function to process generated songs, wait until they are ready, and download them."""
        print(f"Processing songs in {folder} with track_ids {track_ids}...")
        max_retries = 60  # 5 minutes max wait
        retry_count = 0
        while retry_count < max_retries:
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
                retry_count += 1
        print(f"Timeout waiting for songs in {folder} to finish.")
        return None

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
        # Sanitize filename
        safe_title = "".join(c for c in song_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        file_path = os.path.join(folder, f"{safe_title}.mp3")
        try:
            response = requests.get(song_url, timeout=60)
            response.raise_for_status()
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")


class CaptchaRequiredError(Exception):
    """Raised when Udio API returns a CAPTCHA challenge."""
    pass


# For backwards compatibility
def main():
    print("UdioWrapper v0.0.4")
    print("Usage: from udio_wrapper import UdioWrapper")
    print("       wrapper = UdioWrapper('your-auth-token', debug=True)")


if __name__ == "__main__":
    main()