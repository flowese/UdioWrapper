"""
Udio Wrapper
Author: Flowese
Version: 0.0.1
Date: 2024-04-12
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
            'Cookie': f'_ga=GA1.1.140616435.1712840849; sb-api-auth-token={auth_token}',
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
        print(f"La canción '{song_title}' ha sido descargada en '{directory}'.")

    def process_song(self, song_id, directory='output', save_to_disk=True):
        while True:
            song_info = self.send_request(f'songs?songIds={song_id}')
            if song_info['songs'][0].get('finished', False):
                song_url = song_info['songs'][0]['song_path']
                if save_to_disk:
                    song_title = song_info['songs'][0]['title'].replace(" ", "_")
                    self.download_song(song_url, song_title, directory)
                return song_url
            print("La canción aún no está lista. Comprobando en 10 segundos...")
            sleep(10)

    def generate_song(self, prompt, conditioning=None):
        data = {
            "prompt": prompt,
            "samplerOptions": {"seed": -1}
        }
        if conditioning:
            data["samplerOptions"].update(conditioning)
        return self.send_request('generate-proxy', data, 'POST')

    def inference(self, original_prompt, number_of_extensions=0, extend_prompt=None, outro_prompt=None, save_to_disk=True):
        initial_song = self.generate_song(original_prompt)
        initial_song_url = self.process_song(initial_song['track_ids'][0], save_to_disk=save_to_disk)

        current_song_url = initial_song_url
        current_track_id = initial_song['track_ids'][0]

        # Extend the song the specified number of times
        for _ in range(number_of_extensions):
            if extend_prompt:
                extended_song = self.generate_song(extend_prompt, {
                    "audio_conditioning_path": current_song_url,
                    "audio_conditioning_song_id": current_track_id,
                    "audio_conditioning_type": "continuation"
                })
                current_song_url = self.process_song(extended_song['track_ids'][0], save_to_disk=save_to_disk)
                current_track_id = extended_song['track_ids'][0]

        # Add an outro if an outro prompt is provided
        if outro_prompt:
            outro_song = self.generate_song(outro_prompt, {
                "audio_conditioning_path": current_song_url,
                "audio_conditioning_song_id": current_track_id,
                "audio_conditioning_type": "continuation",
                "crop_start_time": 0.9
            })
            current_song_url = self.process_song(outro_song['track_ids'][0], 'final_songs', save_to_disk)

        return current_song_url