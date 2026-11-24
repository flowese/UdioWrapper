0.0.4
Date: 2024-04-18
Description: Generates songs using the Udio API using textual prompts, including necessary headers to prevent 500 Server Errors due to hCaptcha/bot protection.
"""

import requests
import os
import time

class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.all_track_ids = []

    def make_request(self, url, method, data=None, headers=None):
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f"Error making {method} request to {url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response body: {e.response.text}")
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
            "Sec-Fetch-Dest": "empty",
            "x-ud-captcha-token": ""
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "sec-fetch-dest": "empty"
            })
        return headers

    def create_song(self, prompt, seed=-1, custom_lyrics=None, instrumental=False):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers(get_request=False)
        
        data = {
            "prompt": prompt,
            "seed": seed,
            "custom_lyrics": custom_lyrics,
            "instrumental": instrumental
        }
        
        response = self.make_request(url, 'POST', data=data, headers=headers)
        if response:
            try:
                return response.json()
            except ValueError:
                print("Response is not valid JSON")
        return None

    def extend(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers(get_request=False)
        
        data = {
            "prompt": prompt,
            "seed": seed,
            "audio_conditioning_path": audio_conditioning_path,
            "audio_conditioning_song_id": audio_conditioning_song_id,
            "custom_lyrics": custom_lyrics,
            "is_extension": True
        }
        
        response = self.make_request(url, 'POST', data=data, headers=headers)
        if response:
            try:
                return response.json()
            except ValueError:
                print("Response is not valid JSON")
        return None

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
            song_data = last_song_result[0] if isinstance(last_song_result, list) else last_song_result
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=song_data.get('song_path'),
                audio_conditioning_song_id=song_data.get('id'),
                custom_lyrics=lyrics
            )
            
            if not extend_song_result:
                print(f"Error generating extend song {i + 1}.")
                break
                
            last_song_result = extend_song_result
            extend_song_results.append(extend_song_result)
            time.sleep(5)

        return last_song_result