"""
Udio Wrapper
Author: Flowese
Version: 0.0.3
Date: 2024-04-15
Description: Generates songs using the Udio API using textual prompts.
"""

import requests
import os
import time
from twocaptcha import TwoCaptcha
import logging

class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(self, auth_token, twocaptcha_api_key):
        self.auth_token = auth_token
        self.all_track_ids = []
        self.solver = TwoCaptcha(twocaptcha_api_key)

    def solve_captcha(self):
        try:
            result = self.solver.hcaptcha(
                sitekey='2945592b-1928-43a9-8473-7e7fed3d752e',
                url='https://www.udio.com/api/generate-proxy'
            )
            return result['code']
        except Exception as e:
            print(f"Failed to solve captcha: {e}")
            return None


    def make_request(self, url, method, data=None, headers=None, retries=3, delay=2):
        try:
            headers = headers or {}
            headers["Accept"] = "application/json, text/plain, */*"
            headers["Content-Type"] = "application/json"
            headers["Cookie"] = f"sb-api-auth-token={self.auth_token}"
            
            for attempt in range(retries):
                print(f"Attempt {attempt + 1}/{retries}")
                if method == 'POST':
                    captcha_solution = self.solve_captcha()
                    if captcha_solution:
                        headers["H-Captcha-Token"] = captcha_solution
                    response = requests.post(url, headers=headers, json=data)
                else:
                    response = requests.get(url, headers=headers)
    
                if response.status_code == 500:
                        print(f"500 Server Error: Retrying {attempt + 1}/{retries}")
                        time.sleep(delay)
                else:
                        response.raise_for_status()
                        return response

            print(f"Error making {method} request to {url}: {response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Error making {method} request to {url}: {e}", exc_info=True) #Error making logger
            return None

    def get_headers(self, get_request=False):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"; sb-api-auth-token={self.auth_token}",
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

auth_token = "your_api_key_here" #add yout api key generated from cookies as per README instructions
twocaptcha_api_key = "e565f9c19a3eccd58ebc8ee4a32eccc3"
udio_wrapper = UdioWrapper(auth_token, twocaptcha_api_key)
response = udio_wrapper.make_request("https://www.udio.com/api/generate-proxy", "POST")
if response:
    print(response.json())
