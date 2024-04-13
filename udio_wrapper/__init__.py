"""
Udio Wrapper
Author: Flowese
Version: 0.0.2
Date: 2024-04-13
Description: Generates songs using the Udio API using textual prompts.
"""

import requests
from time import sleep
import os

class UdioWrapper:
    def __init__(self, auth_token):
        self.base_url = 'https://www.udio.com/api'
        self.headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Referer': 'https://www.udio.com/',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'Cookie': f'; sb-api-auth-token={auth_token}',
        }

    def send_request(self, endpoint, data=None, method='GET'):
        url = f'{self.base_url}/{endpoint}'
        if method == 'POST':
            response = requests.post(url, headers=self.headers, json=data)
        else:
            response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def download_song(self, song_url, song_title, directory):
        os.makedirs(directory, exist_ok=True)
        file_path = os.path.join(directory, f"{song_title}.mp3")
        response_download = requests.get(song_url, headers=self.headers)
        with open(file_path, 'wb') as f:
            f.write(response_download.content)
        print(f"The song '{song_title}' has been downloaded to '{directory}'.")

    def process_song(self, song_id, directory='output', save_to_disk=True):
        while True:
            song_info = self.send_request(f'songs?songIds={song_id}')
            if song_info['songs'][0].get('finished', False):
                song_url = song_info['songs'][0]['song_path']
                if save_to_disk:
                    song_title = song_info['songs'][0]['title'].replace(" ", "_")
                    self.download_song(song_url, song_title, directory)
                return song_url
            print("The song is not ready yet. Checking in 15 seconds...")
            sleep(15)

    def generate_song(self, prompt, lyric_input=None, conditioning=None):
        data = {
            "prompt": prompt,
            "samplerOptions": {"seed": -1}
        }
        if lyric_input is not None:
            data["lyricInput"] = lyric_input
        if conditioning:
            data["samplerOptions"].update(conditioning)
        return self.send_request('generate-proxy', data, 'POST')

    def inference(self, original_prompt, original_lyric_input=None, number_of_extensions=0, extend_prompt=None, extend_lyric_input=None, outro_prompt=None, outro_lyric_input=None, save_to_disk=True):
        initial_song = self.generate_song(prompt=original_prompt, lyric_input=original_lyric_input)
        initial_song_url = self.process_song(initial_song['track_ids'][0], save_to_disk=save_to_disk)

        current_song_url = initial_song_url
        current_track_id = initial_song['track_ids'][0]

        for _ in range(number_of_extensions):
            if extend_prompt:
                extended_song = self.generate_song(prompt=extend_prompt, lyric_input=extend_lyric_input, conditioning={
                    "audio_conditioning_path": current_song_url,
                    "audio_conditioning_song_id": current_track_id,
                    "audio_conditioning_type": "continuation"
                })
                current_song_url = self.process_song(extended_song['track_ids'][0], save_to_disk=save_to_disk)
                current_track_id = extended_song['track_ids'][0]

        if outro_prompt:
            outro_song = self.generate_song(prompt=outro_prompt, lyric_input=outro_lyric_input, conditioning={
                "audio_conditioning_path": current_song_url,
                "audio_conditioning_song_id": current_track_id,
                "audio_conditioning_type": "continuation",
                "crop_start_time": 0.9
            })
            current_song_url = self.process_song(outro_song['track_ids'][0], 'final_songs', save_to_disk)

        return current_song_url

