"""
Udio Wrapper
Version: 0.0.4
Description: Generates songs using the Udio API using textual prompts.
"""

import logging
import os
import time

try:
    from urllib3.util.retry import Retry
except ImportError:
    Retry = None

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.exceptions import RequestException
except ImportError:
    raise ImportError("requests >= 2.26.0 required")

logger = logging.getLogger(__name__)

HAS_CLOUDSCRAPER = False
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    pass

HAS_CURL_CFFI = False
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    pass


class UdioWrapper:
    API_BASE_URL = "https://www.udio.com/api"

    def __init__(
        self,
        auth_token,
        timeout=60,
        max_retries=3,
        max_poll_time=300,
        use_cloudscraper=False,
        use_curl_cffi=False,
        proxies=None,
    ):
        self.auth_token = auth_token.strip()
        self.all_track_ids = []
        self.timeout = timeout
        self.max_poll_time = max_poll_time
        self.proxies = proxies or self._resolve_proxies()
        self.session = self._build_session(
            use_cloudscraper, use_curl_cffi, max_retries
        )

    @staticmethod
    def _resolve_proxies():
        proxies = {}
        for scheme in ("http", "https"):
            val = os.environ.get(f"{scheme}_proxy") or os.environ.get(
                f"{scheme.upper()}_PROXY"
            )
            if val:
                proxies[scheme] = val
        return proxies or None

    def _build_session(self, use_cloudscraper, use_curl_cffi, max_retries):
        session = None

        if use_curl_cffi and HAS_CURL_CFFI:
            logger.info("using curl_cffi session (TLS fingerprint mimic)")
            session = curl_requests.Session()
            if self.proxies:
                session.proxies.update(self.proxies)
            return session

        if use_cloudscraper and HAS_CLOUDSCRAPER:
            logger.info("using cloudscraper session (Cloudflare JS bypass)")
            session = cloudscraper.create_scraper()
        else:
            if use_cloudscraper and not HAS_CLOUDSCRAPER:
                logger.warning(
                    "cloudscraper not installed, fallback to requests. "
                    "Install: pip install cloudscraper"
                )
            session = requests.Session()

        if Retry is not None:
            retry = Retry(
                total=max_retries,
                read=max_retries,
                connect=max_retries,
                backoff_factor=1.0,
                allowed_methods={"GET", "POST"},
                status_forcelist={429, 500, 502, 503, 504},
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)

        if self.proxies:
            session.proxies.update(self.proxies)
        return session

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
            snippet = ""
            if e.response is not None:
                try:
                    snippet = e.response.text[:200]
                except Exception:
                    pass
            logger.error(
                "Udio API %s %s -> %s | %s",
                method, url, status or "N/A", snippet or "",
            )
            return None

    @staticmethod
    def _parse_json(response):
        if response is None:
            return None
        try:
            return response.json()
        except Exception as e:
            logger.error("JSON parse error: %s", e)
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
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if not get_request:
            headers.update({
                "sec-ch-ua": (
                    '"Google Chrome";v="126", '
                    '"Not.A/Brand";v="24", '
                    '"Chromium";v="126"'
                ),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })
        return headers

    @staticmethod
    def _safe_filename(title):
        safe = title.replace("/", "_").replace("\\", "_")
        return "".join(c for c in safe if c not in "\0:")

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
        logger.info("generating complete song sequence (seed=%s, %d extends, 1 outro)", seed, num_extensions)

        if not extend_prompts:
            logger.error("extend_prompts is empty")
            return None

        short_song = self.create_song(short_prompt, seed, custom_lyrics_short)
        if not short_song:
            return None

        last = short_song
        extends = []

        for i in range(num_extensions):
            prompt = (
                extend_prompts[i] if i < len(extend_prompts) else extend_prompts[-1]
            )
            lyrics = (
                custom_lyrics_extend[i]
                if custom_lyrics_extend and i < len(custom_lyrics_extend)
                else None
            )
            logger.info("extend %d/%d", i + 1, num_extensions)
            result = self.extend(
                prompt, seed,
                audio_conditioning_path=last[0]["song_path"],
                audio_conditioning_song_id=last[0]["id"],
                custom_lyrics=lyrics,
            )
            if not result:
                return None
            extends.append(result)
            last = result

        logger.info("generating outro")
        outro = self.add_outro(
            outro_prompt, seed,
            audio_conditioning_path=last[0]["song_path"],
            audio_conditioning_song_id=last[0]["id"],
            custom_lyrics=custom_lyrics_outro,
        )
        if not outro:
            return None

        return {"short_song": short_song, "extend_songs": extends, "outro_song": outro}

    def create_song(self, prompt, seed=-1, custom_lyrics=None):
        result = self.generate_song(prompt, seed, custom_lyrics)
        if not result:
            return None
        tids = result.get("track_ids", [])
        self.all_track_ids.extend(tids)
        return self.process_songs(tids, "short_songs")

    def extend(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
    ):
        result = self.generate_extend_song(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics
        )
        if not result:
            return None
        tids = result.get("track_ids", [])
        self.all_track_ids.extend(tids)
        return self.process_songs(tids, "extend_songs")

    def add_outro(
        self,
        prompt,
        seed=-1,
        audio_conditioning_path=None,
        audio_conditioning_song_id=None,
        custom_lyrics=None,
    ):
        result = self.generate_outro(
            prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics
        )
        if not result:
            return None
        tids = result.get("track_ids", [])
        self.all_track_ids.extend(tids)
        return self.process_songs(tids, "outro_songs")

    def generate_song(self, prompt, seed, custom_lyrics=None):
        data = {"prompt": prompt, "samplerOptions": {"seed": seed}}
        if custom_lyrics:
            data["lyricInput"] = custom_lyrics
        return self._parse_json(
            self.make_request(f"{self.API_BASE_URL}/generate-proxy", "POST", data, self.get_headers())
        )

    def generate_extend_song(
        self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None
    ):
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
        return self._parse_json(
            self.make_request(f"{self.API_BASE_URL}/generate-proxy", "POST", data, self.get_headers())
        )

    def generate_outro(
        self, prompt, seed, audio_conditioning_path, audio_conditioning_song_id, custom_lyrics=None
    ):
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
        return self._parse_json(
            self.make_request(f"{self.API_BASE_URL}/generate-proxy", "POST", data, self.get_headers())
        )

    def process_songs(self, track_ids, folder):
        logger.info("processing %s %s", folder, track_ids)
        deadline = time.time() + self.max_poll_time
        while time.time() < deadline:
            status = self.check_song_status(track_ids)
            if status is None:
                return None
            if status.get("all_finished"):
                songs = []
                for song in status["data"]["songs"]:
                    self.download_song(song["song_path"], song["title"], folder=folder)
                    songs.append(song)
                logger.info("all %s done (%d songs)", folder, len(songs))
                return songs
            time.sleep(5)
        logger.error("timeout waiting for %s", folder)
        return None

    def check_song_status(self, song_ids):
        url = f"{self.API_BASE_URL}/songs?songIds={','.join(song_ids)}"
        response = self.make_request(url, "GET", None, self.get_headers(get_request=True))
        if not response:
            return None
        data = self._parse_json(response)
        if not data or not data.get("songs"):
            return None
        all_finished = all(s["finished"] for s in data["songs"])
        return {"all_finished": all_finished, "data": data}

    def download_song(self, song_url, song_title, folder="downloaded_songs"):
        os.makedirs(folder, exist_ok=True)
        safe = self._safe_filename(song_title)
        path = os.path.join(folder, f"{safe}.mp3")
        try:
            resp = self.session.get(song_url, stream=True, timeout=self.timeout)
            resp.raise_for_status()
            with open(path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("downloaded %s -> %s", safe, path)
        except RequestException as e:
            logger.error("download failed %s: %s", safe, e)
