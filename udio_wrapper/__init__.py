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
        
