"""
Udio Wrapper
Author: Flowese
Version: 0.0.4
Date: 2026-05-26
Description: Generates songs using the Udio API using textual prompts.
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.exceptions import RequestException
    from urllib3.util.retry import Retry
except ImportError:
    raise ImportError(
        "requests is required. Install it with: pip install requests>=2.31.0"
    )

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(
        self,
        auth_token,
        timeout=60,
        max_retries=3,
        max_poll_time=300,
        use_cloudscraper=False,
        proxies=None,
    ):
        self.auth_token = auth_token.strip()
        self.all_track_ids = []
        self.timeout = timeout
        self.max_poll_time = max_poll_time
        self.proxies = proxies or self._env_proxies()

        if use_cloudscraper:
            if HAS_CLOUDSCRAPER:
                logger.info("Using cloudscraper session (Cloudflare bypass enabled)")
                self.session = cloudscraper.create_scraper()
            else:
                logger.warning(
                    "cloudscraper requested but not installed. "
                    "Install with: pip install cloudscraper>=1.2.0"
                )
                self.session = requests.Session()
        else:
            self.session = requests.Session()

        if not isinstance(self.session, requests.Session):
            return  # cloudscraper session has its own retry logic
        retry_strategy = Retry(
            total=max_retries,
            read=max_retries,
            connect=max_retries,
            backoff_factor=1.0,
            allowed_methods=["GET", "POST"],
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if self.proxies:
            self.session.proxies.update(self.proxies)

    @staticmethod
    def _env_proxies():
        """Read proxy settings from environment variables."""
        proxies = {}
        for key, env_name in [("http", "HTTP_PROXY"), ("https", "HTTPS_PROXY")]:
            value = os.environ.get(env_name) or os.environ.get(env_name.lower())
            if value:
                proxies[key] = value
        return proxies or None

    def make_request(self, url, method, data=None, headers=None):
        kwargs = {"headers": headers, "timeout": self.timeout}
        try:
            if method == "POST":
                kwargs["json"] = data
                response = self.session.post(url, **kwargs)
            else:
                response = self.session.get(url, **kwargs)
            response.raise_for_status()
            return response
        except RequestException as e:
            status = getattr(e.response, "status_code", None)
            body = ""
            if e.response is not None:
                try:
                    body = e.response.text[:500]
                except Exception:
                    pass
            logger.error(
                "Udio API %s %s -> %s | body=%.200s",
                method, url, status or "N/A", body or "N/A",
            )
            return None

    @staticmethod
    def _parse_json(response):
        """Safely parse JSON from response, returning None on failure."""
        if response is None:
            return None
        try:
            return response.json()
        except Exception as e:
            logger.error("Failed to parse JSON response: %s", e)
            return None

    def get_headers(self, get_request=False):
        headers = {
            "Accept": (
                "application/json, text/plain, */*"
                if get_request
                else "application/json"
            ),
            "Content-Type": "application/json",
            "Cookie": f"sb-api-auth-token={self.auth_token}",
            "Origin": "https://www.udio.com",
            "Referer": "https://www.udio.com/my-creations",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": (
                    '"Google Chrome";v="125", '
                    '"Not.A/Brand";v="24", '
                    '"Chromium";v="125"'
                ),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    @staticmethod
    def _safe_filename(title):
        """Remove path separators from a filename to prevent traversal."""
        return title.replace("/", "_").replace("\\", "_").replace("\0", "")

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
    ):
        logger.info("Starting generation of complete song sequence...")
        if not extend_prompts:
            logger.error("extend_prompts cannot be empty.")
            return None

        short_song_result = self.create_song(short_prompt, seed, custom_lyrics_short)
        if not short_song_result:
            logger.error("Failed to generate short song.")
            return None

        last_song_result = short_song_result
        extend_song_results = []

        for i in range(num_extensions):
            if i < len(extend_prompts):
                prompt = extend_prompts[i]
                lyrics = (
                    custom_lyrics_extend[i]
                    if custom_lyrics_extend and i < len(custom_lyrics_extend)
                    else None
                )
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

    def create_song(self, prompt, seed=-1, custom_lyrics=None):
        song_result = self.generate_song(prompt, seed, custom_lyrics)
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
    ):
        result = self.generate_extend_song(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id,
            custom_lyrics,
        )
        if not result:
            return None
        track_ids = result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "extend_songs")

    def add_outro(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
    ):
        result = self.generate_outro(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id,
            custom_lyrics,
        )
        if not result:
            return None
        track_ids = result.get("track_ids", [])
        self.all_track_ids.extend(track_ids)
        return self.process_songs(track_ids, "outro_songs")

    def generate_song(self, prompt, seed, custom_lyrics=None):
        url = f"{self.API_BASE_URL}/generate-proxy"
        headers = self.get_headers()
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        return self._parse_json(self.make_request(url, "POST", data, headers))

    def generate_extend_song(
        self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id,
        custom_lyrics=None,
    ):
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
        return self._parse_json(self.make_request(url, "POST", data, headers))

    def generate_outro(
        self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id,
        custom_lyrics=None,
    ):
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
        return self._parse_json(self.make_request(url, "POST", data, headers))

    def process_songs(self, track_ids, folder):
        logger.info(
            "Processing songs in %s with track_ids %s...", folder, track_ids
        )
        deadline = time.time() + self.max_poll_time
        while time.time() < deadline:
            status_result = self.check_song_status(track_ids)
            if status_result is None:
                logger.error("Error checking song status for %s.", folder)
                return None
            if status_result.get("all_finished", False):
                songs = []
                for song in status_result["data"]["songs"]:
                    self.download_song(
                        song["song_path"], song["title"], folder=folder
                    )
                    songs.append(song)
                logger.info("All songs in %s are ready and downloaded.", folder)
                return songs
            time.sleep(5)
        logger.error("Timed out waiting for songs in %s.", folder)
        return None

    def check_song_status(self, song_ids):
        url = (
            f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        )
        headers = self.get_headers(get_request=True)
        response = self.make_request(url, "GET", None, headers)
        if response:
            data = self._parse_json(response)
            if not data or not data.get("songs"):
                return None
            all_finished = all(s["finished"] for s in data["songs"])
            return {"all_finished": all_finished, "data": data}
        return None

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        safe_title = self._safe_filename(song_title)
        file_path = os.path.join(folder, f"{safe_title}.mp3")
        try:
            response = self.session.get(song_url, stream=True)
            response.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("Downloaded %s to %s", safe_title, file_path)
        except RequestException as e:
            logger.error("Failed to download song %s: %s", safe_title, e)
