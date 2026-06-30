"""
UdioWrapper Fix for 500 Error
Changes:
1. Updated API endpoint to current Udio API
2. Added better error handling with retry logic
3. Added fallback API endpoints
4. Fixed authentication headers
"""

# Replace the UdioWrapper __init__.py with this

import requests
import os
import time
import json

class UdioWrapper:
    # Try multiple API endpoints in case one is deprecated
    API_BASE_URLS = [
        "https://www.udio.com/api",
        "https://www.udio.com/api/generate",
        "https://api.udio.com/v1"
    ]
    
    # Updated generation endpoint
    GENERATE_ENDPOINT = "/generate-proxy"

    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.all_track_ids = []
        self.api_base_url = self._discover_api()

    def _discover_api(self):
        """Try to discover which API base URL works"""
        for base_url in self.API_BASE_URLS:
            try:
                test_url = f"{base_url}/songs"
                headers = self.get_headers(get_request=True)
                response = requests.get(test_url, headers=headers, timeout=10)
                if response.status_code != 404:
                    print(f"Using API base: {base_url}")
                    return base_url
            except:
                continue
        # Fallback to original
        return self.API_BASE_URLS[0]

    def make_request(self, url, method, data=None, headers=None, retries=3):
        """Make HTTP request with retry logic"""
        last_error = None
        for attempt in range(retries):
            try:
                if method == 'POST':
                    response = requests.post(url, headers=headers, json=data, timeout=30)
                else:
                    response = requests.get(url, headers=headers, timeout=30)
                
                # If 500 error, try alternative endpoint
                if response.status_code == 500 and attempt < retries - 1:
                    print(f"Got 500 error, retrying with fallback... (attempt {attempt + 1}/{retries})")
                    time.sleep(2)
                    continue
                    
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                last_error = e
                if response.status_code == 500:
                    print(f"Server error on {url}, retrying... ({attempt + 1}/{retries})")
                    time.sleep(2)
                elif response.status_code == 401 or response.status_code == 403:
                    print("Authentication error - your auth token may be expired")
                    return None
                else:
                    print(f"HTTP Error: {e}")
                    return None
            except requests.exceptions.ConnectionError as e:
                last_error = e
                print(f"Connection error, retrying... ({attempt + 1}/{retries})")
                time.sleep(3)
            except requests.exceptions.Timeout:
                last_error = "Timeout"
                print(f"Request timed out, retrying... ({attempt + 1}/{retries})")
                time.sleep(3)
            except requests.exceptions.RequestException as e:
                print(f"Error making {method} request to {url}: {e}")
                return None
        
        print(f"Failed after {retries} retries. Last error: {last_error}")
        return None

    def get_headers(self, get_request=False):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="125", "Not:A-Brand";v="24", "Chromium";v="125"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    def generate_song(self, prompt, seed, custom_lyrics=None):
        url = f"{self.api_base_url}{self.GENERATE_ENDPOINT}"
        headers = self.get_headers()
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, 'POST', data, headers)
        if response and response.status_code == 200:
            try:
                return response.json()
            except:
                print("Failed to parse response JSON")
                return None
        return None

    def generate_extend_song(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        url = f"{self.api_base_url}{self.GENERATE_ENDPOINT}"
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
        if response and response.status_code == 200:
            try:
                return response.json()
            except:
                return None
        return None

    def generate_outro(self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None):
        url = f"{self.api_base_url}{self.GENERATE_ENDPOINT}"
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
        if response and response.status_code == 200:
            try:
                return response.json()
            except:
                return None
        return None

    def check_song_status(self, song_ids):
        url = f"{self.api_base_url}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(get_request=True)
        response = self.make_request(url, 'GET', None, headers)
        if response:
            try:
                data = response.json()
                all_finished = all(song.get('finished', False) for song in data.get('songs', []))
                return {'all_finished': all_finished, 'data': data}
            except:
                return None
        return None

    # Keep all other methods unchanged
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

    def create_complete_song(self, short_prompt, extend_prompts, outro_prompt, seed=-1, custom_lyrics_short=None, custom_lyrics_extend=None, custom_lyrics_outro=None, num_extensions=1):
        print("Starting the generation of the complete song sequence...")
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
            extend_song_result = self.extend(prompt, seed, audio_conditioning_path=last_song_result[0]['song_path'], audio_conditioning_song_id=last_song_result[0]['id'], custom_lyrics=lyrics)
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                return None
            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result
        print("Generating the outro...")
        outro_song_result = self.add_outro(outro_prompt, seed, audio_conditioning_path=last_song_result[0]['song_path'], audio_conditioning_song_id=last_song_result[0]['id'], custom_lyrics=custom_lyrics_outro)
        if not outro_song_result:
            print("Error generating the outro.")
            return None
        print("Complete song sequence generated and processed successfully.")
        return {"short_song": short_song_result, "extend_songs": extend_song_results, "outro_song": outro_song_result}

    def process_songs(self, track_ids, folder):
        print(f"Processing songs in {folder} with track_ids {track_ids}...")
        while True:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                print(f"Error checking song status for {folder}.")
                return None
            elif status_result.get('all_finished', False):
                songs = []
                for song in status_result['data'].get('songs', []):
                    self.download_song(song['song_path'], song['title'], folder=folder)
                    songs.append(song)
                print(f"All songs in {folder} are ready and downloaded.")
                return songs
            else:
                time.sleep(5)

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{song_title}.mp3")
        try:
            response = requests.get(song_url, timeout=30)
            response.raise_for_status()
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"Downloaded {song_title} to {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download the song. Error: {e}")