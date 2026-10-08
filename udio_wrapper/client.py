import asyncio
import uuid
import json
import logging
from typing import List, Optional

import httpx

from udio_wrapper.models.audio import AudioParams, Audio
from udio_wrapper.exceptions import UdioAPIError, AuthenticationError
from udio_wrapper.cookie_manager import CookieManager
from udio_wrapper.utils import wait_for_token

logger = logging.getLogger(__name__)


class UdioClient:
    def __init__(
        self,
        session_cookie: Optional[str] = None,
        cookie_file: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        self.session_cookie = session_cookie
        self.cookie_manager = CookieManager(cookie_file) if cookie_file else None
        self.proxy = proxy
        self.base_url = "https://www.udio.com"
        self.api_url = f"{self.base_url}/api"

    async def _get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        }
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
        elif self.cookie_manager:
            headers["Cookie"] = self.cookie_manager.get_cookies()
        return headers

    async def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> dict:
        async with httpx.AsyncClient(proxy=self.proxy, timeout=60.0) as client:
            headers = await self._get_headers()
            url = f"{self.api_url}/{endpoint}" if not endpoint.startswith("http") else endpoint
            try:
                response = await client.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                error_body = ""
                try:
                    error_body = e.response.text
                except Exception:
                    pass
                logger.error(f"HTTP {status_code} for {url}: {error_body[:500]}")
                if status_code == 401:
                    raise AuthenticationError(f"Authentication failed: {error_body}") from e
                elif status_code == 429:
                    raise UdioAPIError(f"Rate limited: {error_body}") from e
                else:
                    raise UdioAPIError(f"HTTP {status_code}: {error_body}") from e
            except httpx.RequestError as e:
                raise UdioAPIError(f"Request failed: {str(e)}") from e

    async def generate_audio(self, params: AudioParams) -> Audio:
        task_id = str(uuid.uuid4())
        prompt = params.to_prompt()
        logger.info(f"Starting audio generation: task_id={task_id}, prompt={prompt[:100]}...")

        # Send initial generation request
        payload = {
            "prompt": prompt,
            "task_id": task_id,
            "custom_model_id": params.custom_model_id,
            "continue_clip_id": params.continue_clip_id,
            "duration_seconds": params.duration_seconds,
            "style_description": params.style_description,
            "lyrics": params.lyrics,
            "without_lyrics": params.without_lyrics,
        }
        if params.extended_from_clip_id:
            payload["extended_from_clip_id"] = params.extended_from_clip_id

        result = await self._request("POST", "generate-proxy", json=payload)
        logger.info(f"Generation request submitted: task_id={task_id}")

        # Poll for completion
        audio = await wait_for_token(
            client=self,
            task_id=task_id,
            max_wait_time=params.max_wait_time,
        )
        logger.info(f"Audio generation completed: task_id={task_id}")
        return audio

    async def get_user_info(self) -> dict:
        return await self._request("GET", "user-info")

    async def get_history(self, limit: int = 20, offset: int = 0) -> dict:
        return await self._request(
            "GET", f"history?limit={limit}&offset={offset}"
        )

    async def search_songs(self, query: str, limit: int = 20) -> dict:
        return await self._request(
            "GET", f"search?q={query}&limit={limit}"
        )
