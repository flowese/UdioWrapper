"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2026-05-20
Description: Generates songs using the Udio API using textual prompts.
"""

import os
import time
import logging

logger = logging.getLogger(__name__)

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.exceptions import RequestException
    from urllib3.util.retry import Retry
except ImportError:
    raise ImportError("requests is required. Install it with: pip install requests")

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(self, auth_token, timeout=60, max_retries=3, use_cloudscraper=False, proxies=None):
        self.auth_token = auth_token.strip()
        self.all_track_ids = []
        self.timeout = timeout
        self.proxies = proxies

        if use_cloudscraper and HAS_CLOUDSCRAPER:
            self.session = cloudscraper.create_scraper()
        else:
            self.session = requests.Session()
            retry_strategy = Retry(
                total=max_retries,
                read=max_retries,
                connect=max_retries,
                backoff_factor=0.5,
                allowed_methods=["GET", "POST"],
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)

        if proxies:
            self.session.proxies.update(proxies)

    def make_request(self, url, method, data=None, headers=None):
        try:
            kwargs = {"headers": headers, "timeout": self.timeout}
            if self.proxies:
                kwargs["proxies"] = self.proxies
            if method == "POST":
                kwargs["json"] = data
                response = self.session.post(url, **kwargs)
            else:
                response = self.session.get(url, **kwargs)

            response.raise_for_status()
            return response

        except RequestException as e:
            status = ""
            body = ""
            if e.response is not None:
                status = e.response.status_code
                try:
                    body = e.response.text[:500]
                except Exception:
                    pass
            logger.error(
                "Udio API %s %s -> %s | body: %s",
                method, url, status or str(e), body,
            )
            return None

    def get_headers(self, get_request=False):
        headers = {
            "Accept": "application/json, text/plain, */*" if get_request else "application/json",
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": '"Google Chrome";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    def create_complete_song(self, short_prompt, extend_prompts, outro_prompt, seed=-1, custom_lyrics_short=None, custom_lyrics_extend=None, custom_lyrics_outro=None, num_extensions=1):
        logger.info("Starting generation of complete song sequence...")

        short_song_result = self.create_song(short_prompt, seed, custom_lyrics_short)
        if not short_song_result:
            logger.error("Failed to generate short song.")
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

            logger.info("Generating extend song %d/%d...", i + 1, num_extensions)
            extend_song_result = self.extend(
                prompt,
                seed,
                audio_conditioning_path=last_song_result[0]["song_path"],
                audio_conditioning_song_id=last_song_result[0]["id"],
                custom_lyrics=lyrics,
            )
            if not extend_song_result:
                logger.error("Failed to generate extend song %d.", i + 1)
                return None

            extend_song_results.append(extend_song_result)
            last_song_result = extend_song_result

        logger.info("Generating outro...")
        outro_song_result = self.add_outro(
            outro_prompt,
            seed,
            audio_conditioning_path=last_song_result[0]["song_path"],
            audio_conditioning_song_id=last_song_result[0]["id"],
            custom_lyrics=custom_lyrics_outro,
        )
        if not outro_song_result:
            logger.error("Failed to generate outro.")
            return None

        logger.info("Complete song sequence generated successfully.")
        return {
            "short_song": short_song_result,
            "extend_songs": extend_song_results,
            "outro_song": outro_song_result,
        }

    def _generate(self, prompt, seed, extra_opts=None, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = {
            "prompt": prompt,
            "samplerOptions": {"seed": seed, **(extra_opts or {})},
        }
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        response = self.make_request(url, "POST", data, headers)
        return response.json() if response else None

    def create_song(self, prompt, seed=-1, custom_lyrics=None):
        song_result = self._generate(prompt, seed, custom_lyrics=custom_lyrics)
        if not song_result:
            return None
        track_ids = song_result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "short_songs")

    def extend(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        opts = {}
        if audio_conditioning_path:
            opts["audio_conditioning_path"] = audio_conditioning_path
            opts["audio_conditioning_song_id"] = audio_conditioning_song_id
            opts["audio_conditioning_type"] = "continuation"
        extend_song_result = self._generate(prompt, seed, extra_opts=opts, custom_lyrics=custom_lyrics)
        if not extend_song_result:
            return None
        extend_track_ids = extend_song_result.get("track_ids", [])
        self.all_track_ids.extend(extend_track_ids)
        return self.process_songs(extend_track_ids, "extend_songs")

    def add_outro(self, prompt, seed=-1, audio_conditioning_path=None, audio_conditioning_song_id=None, custom_lyrics=None):
        opts = {"crop_start_time": 0.9}
        if audio_conditioning_path:
            opts["audio_conditioning_path"] = audio_conditioning_path
            opts["audio_conditioning_song_id"] = audio_conditioning_song_id
            opts["audio_conditioning_type"] = "continuation"
        outro_result = self._generate(prompt, seed, extra_opts=opts, custom_lyrics=custom_lyrics)
        if not outro_result:
            return None
        outro_track_ids = outro_result.get("track_ids", [])
        self.all_track_ids.extend(outro_track_ids)
        return self.process_songs(outro_track_ids, "outro_songs")

    def process_songs(self, track_ids, folder):
        logger.info("Processing %s songs with track_ids %s...", folder, track_ids)
        wait = 3
        while True:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                logger.warning("Error checking status for %s, retrying in %ds...", folder, wait)
                time.sleep(wait)
                wait = min(wait * 1.5, 30)
                continue
            if status_result.get("all_finished", False):
                songs = []
                for song in status_result["data"]["songs"]:
                    self.download_song(song["song_path"], song["title"], folder=folder)
                    songs.append(song)
                logger.info("All %d songs in %s ready.", len(songs), folder)
                return songs
            time.sleep(5)

    def check_song_status(self, song_ids):
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        headers = self.get_headers(True)
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
            response = self.session.get(song_url, timeout=self.timeout)
            response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(response.content)
            logger.info("Downloaded %s -> %s", song_title, file_path)
        except RequestException as e:
            logger.error("Failed to download %s: %s", song_title, e)

