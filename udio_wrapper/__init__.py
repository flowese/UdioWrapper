"""
Udio Wrapper
Author: Flowese
Version: 0.0.3
Date: 2026-11-26
Description: Generates songs using the Udio API using textual prompts.
"""

import os
import time
import requests


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(self, auth_token, hcaptcha_solver=None, timeout=30):
        self.auth_token = auth_token
        self.hcaptcha_solver = hcaptcha_solver
        self.timeout = timeout
        self.all_track_ids = []

    def resolve_hcaptcha(self, hcaptcha_token=None):
        if hcaptcha_token:
            return hcaptcha_token
        if callable(self.hcaptcha_solver):
            return self.hcaptcha_solver()
        return None

    def make_request(self, url, method, data=None, headers=None):
        try:
            if method.upper() == "POST":
                response = requests.post(
                    url, headers=headers, json=data, timeout=self.timeout
                )
            else:
                response = requests.get(
                    url, headers=headers, timeout=self.timeout
                )
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "unknown"
            body_preview = e.response.text[:300] if e.response is not None else ""
            print(
                f"HTTP error ({status_code}) making {method} request to {url}: {e} | Response: {body_preview}"
            )
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error making {method} request to {url}: {e}")
            return None

    def get_headers(self, get_request=False, hcaptcha_token=None):
        clean_token = (self.auth_token or "").lstrip("; ").strip()
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={clean_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if hcaptcha_token:
            headers["x-hcaptcha-token"] = hcaptcha_token
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="124", "Not:A-Brand";v="8", "Chromium";v="124"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    def _build_payload(self, prompt, seed, custom_lyrics=None, sampler_extra=None, hcaptcha_token=None):
        sampler_options = {"seed": seed}
        if sampler_extra:
            sampler_options.update(sampler_extra)
        payload = {
            "prompt": prompt,
            "samplerOptions": sampler_options,
        }
        if custom_lyrics:
            payload["lyricInput"] = custom_lyrics
        if hcaptcha_token:
            payload["hcaptchaToken"] = hcaptcha_token
        return payload

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
        hcaptcha_token=None,
    ):
        print("Starting the generation of the complete song sequence...")

        print("Generating the short song...")
        
        short_song_result = self.create_song(
            short_prompt, seed, custom_lyrics_short, hcaptcha_token=hcaptcha_token
        )
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
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]["song_path"],
                audio_conditioning_song_id=last_song_result[0]["id"],
                custom_lyrics=lyrics,
                hcaptcha_token=hcaptcha_token,
            )
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                return None

            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        print("Generating the outro...")
        outro_song_result = self.add_outro(
            outro_prompt,
            seed,
            audio_conditioning_path=last_song_result[0]["song_path"],
            audio_conditioning_song_id=last_song_result[0]["id"],
            custom_lyrics=custom_lyrics_outro,
            hcaptcha_token=hcaptcha_token,
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

    def create_song(self, prompt, seed=-1, custom_lyrics=None, hcaptcha_token=None):
        song_result = self.generate_song(prompt, seed, custom_lyrics, hcaptcha_token=hcaptcha_token)
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
        hcaptcha_token=None,
    ):
        extend_song_result = self.generate_extend_song(
            prompt,
            seed,
            audio_conditioning_path,
            audio_conditioning_song_id,
            custom_lyrics,
            hcaptcha_token=hcaptcha_token,
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
        hcaptcha_token=None,
    ):
        outro_result = self.generate_outro(
            prompt,
            seed,
            audio_conditioning_path,
            audio_conditioning_song_id,
            custom_lyrics,
            hcaptcha_token=hcaptcha_token,
        )
        if not outro_result:
            return None
        outro_track_ids = outro_result.get("track_ids", [])
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    def generate_song(self, prompt, seed, custom_lyrics=None, hcaptcha_token=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        token = self.resolve_hcaptcha(hcaptcha_token)
        headers = self.get_headers(hcaptcha_token=token)
        data = self._build_payload(prompt, seed, custom_lyrics=custom_lyrics, hcaptcha_token=token)
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def generate_extend_song(
        self,
        prompt,
        seed,
        audio_conditioning_path,
        audio_conditioning_song_id,
        custom_lyrics=None,
        hcaptcha_token=None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        token = self.resolve_hcaptcha(hcaptcha_token)
        headers = self.get_headers(hcaptcha_token=token)
        data = self._build_payload(
            prompt,
            seed,
            custom_lyrics=custom_lyrics,
            sampler_extra={
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
            },
            hcaptcha_token=token,
        )
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def generate_outro(
        self,
        prompt,
        seed,
        audio_conditioning_path,
        audio_conditioning_song_id,
        custom_lyrics=None,
        hcaptcha_token=None,
    ):
        url = f"{self.API_BASE_URL}/generate-proxy"
        token = self.resolve_hcaptcha(hcaptcha_token)
        headers = self.get_headers(hcaptcha_token=token)
        data = self._build_payload(
            prompt,
            seed,
            custom_lyrics=custom_lyrics,
            sampler_extra={
                "audio_conditioning_path": audio_conditioning_path,
                "audio_conditioning_song_id": audio_conditioning_song_id,
                "audio_conditioning_type": "continuation",
                "crop_start_time": 0.9,
            },
            hcaptcha_token=token,
        )
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
        headers = self.get_headers(get_request=True)
        response = self.make_request(url, "GET", None, headers)
        if response:
            data = response.json()
            all_finished = all(song["finished"] for song in data["songs"])
            return {"all_finished": all_finished, "data": data}
        return None

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{song_title}.mp3")
        try:
            response = requests.get(song_url, timeout=self.timeout)
            response.raise_for_status()
            with open(file_path, "wb") as file:
                file.write(response.content)
            print(f"Downloaded {song_title} with url {song_url} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")
            
