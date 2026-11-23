"""Isolated offline unit tests for UdioWrapper request and error handling.

All tests use mocked HTTP responses; no external network requests are made.
"""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

import requests

from udio_wrapper import (
    UdioAuthenticationError,
    UdioChallengeError,
    UdioError,
    UdioHTTPError,
    UdioResponseError,
    UdioWrapper,
)


def make_mock_response(status_code=200, payload=None, text=None, url="https://www.udio.com/api/generate-proxy"):
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = url
    req = requests.Request(
        "POST" if "generate-proxy" in url else "GET",
        url,
        headers={"Cookie": "sb-api-auth-token=super_secret_token_123"},
    ).prepare()
    resp.request = req

    if text is not None:
        resp._content = text.encode("utf-8")
    elif payload is not None:
        resp._content = json.dumps(payload).encode("utf-8")
        resp.headers["Content-Type"] = "application/json"
    else:
        resp._content = b""

    return resp


class TestUdioWrapperRequestHandling(unittest.TestCase):
    def setUp(self):
        self.secret_token = "secret_session_token_xyz"
        self.wrapper = UdioWrapper(self.secret_token, timeout=15)

    # 1. Successful responses are parsed correctly
    def test_successful_generate_song_response_parsed(self):
        expected_data = {"track_ids": ["track_abc_1", "track_abc_2"]}
        mock_resp = make_mock_response(200, payload=expected_data)

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = self.wrapper.generate_song("Synthwave sunset", seed=123)

        self.assertEqual(result, expected_data)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 15.0)
        self.assertEqual(
            mock_post.call_args.kwargs["json"],
            {"prompt": "Synthwave sunset", "samplerOptions": {"seed": 123}},
        )

    def test_successful_song_status_parsed(self):
        expected_songs = [
            {"id": "t1", "title": "Track 1", "finished": True, "song_path": "https://cdn.example.com/t1.mp3"},
            {"id": "t2", "title": "Track 2", "finished": True, "song_path": "https://cdn.example.com/t2.mp3"},
        ]
        mock_resp = make_mock_response(
            200, payload={"songs": expected_songs}, url="https://www.udio.com/api/songs?songIds=t1,t2"
        )

        with patch("requests.get", return_value=mock_resp):
            status = self.wrapper.check_song_status(["t1", "t2"])

        self.assertTrue(status["all_finished"])
        self.assertEqual(status["data"]["songs"], expected_songs)

    # 2. Genuine HTTP 500 remains distinguishable from a verification failure
    def test_genuine_http_500_raises_http_error_not_challenge_error(self):
        mock_resp = make_mock_response(
            500,
            text="Internal Server Error - Database connection failed",
        )

        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(UdioHTTPError) as ctx:
                self.wrapper.generate_song("Chill lofi beat")

        # Must be UdioHTTPError, NOT UdioChallengeError
        self.assertIs(type(ctx.exception), UdioHTTPError)
        self.assertNotIsInstance(ctx.exception, UdioChallengeError)
        self.assertIn("500", str(ctx.exception))
        self.assertIn("does not necessarily indicate a verification challenge", str(ctx.exception))

    def test_generic_http_502_503_raises_http_error(self):
        for status in (502, 503):
            with self.subTest(status=status):
                mock_resp = make_mock_response(status, text="Bad Gateway / Service Unavailable")
                with patch("requests.post", return_value=mock_resp):
                    with self.assertRaises(UdioHTTPError) as ctx:
                        self.wrapper.generate_song("ambient drone")
                self.assertIs(type(ctx.exception), UdioHTTPError)
                self.assertEqual(ctx.exception.response.status_code, status)

    # 3. Explicit verification response produces useful manual instructions
    def test_explicit_json_challenge_raises_challenge_error_with_manual_guidance(self):
        challenge_payloads = [
            {"error": "captcha_required"},
            {"code": "hcaptcha_required"},
            {"error_code": "human_verification_required"},
            {"error": {"code": "captcha_verification_required"}},
        ]
        for payload in challenge_payloads:
            for status in (200, 403, 500):
                with self.subTest(status=status, payload=payload):
                    mock_resp = make_mock_response(status, payload=payload)
                    with patch("requests.post", return_value=mock_resp):
                        with self.assertRaises(UdioChallengeError) as ctx:
                            self.wrapper.generate_song("orchestral theme")

                    self.assertIn("requires human verification", str(ctx.exception))
                    self.assertIn("standard web browser", str(ctx.exception))
                    self.assertIn("Automated solving or bypassing of verification is not supported", str(ctx.exception))

    def test_html_hcaptcha_challenge_page_raises_challenge_error(self):
        html_body = """<!DOCTYPE html>
        <html>
        <head><title>Verification Required</title></head>
        <body>
            <div class="h-captcha" data-sitekey="test-sitekey"></div>
        </body>
        </html>"""
        mock_resp = make_mock_response(403, text=html_body)
        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(UdioChallengeError) as ctx:
                self.wrapper.generate_song("piano ballad")

        self.assertIn("requires human verification", str(ctx.exception))
        self.assertIn("standard web browser", str(ctx.exception))

    # 4. Authentication failures are reported correctly
    def test_http_401_raises_authentication_error(self):
        mock_resp = make_mock_response(401, payload={"error": "unauthorized"})
        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(UdioAuthenticationError) as ctx:
                self.wrapper.generate_song("jazz fusion")

        self.assertIsInstance(ctx.exception, UdioHTTPError)
        self.assertIn("401", str(ctx.exception))
        self.assertIn("sb-api-auth-token", str(ctx.exception))
        self.assertIn("signed in to Udio", str(ctx.exception))

    # 5. Rate limiting is handled without uncontrolled retries
    def test_http_429_raises_http_error_without_retry(self):
        mock_resp = make_mock_response(429, payload={"error": "too many requests"})
        with patch("requests.post", return_value=mock_resp) as mock_post:
            with self.assertRaises(UdioHTTPError) as ctx:
                self.wrapper.generate_song("speed metal")

        # Must only call once - no automated retry loops
        mock_post.assert_called_once()
        self.assertEqual(ctx.exception.response.status_code, 429)

    # 6. Timeouts produce clear exceptions
    def test_timeout_propagates_clearly(self):
        timeout_err = requests.exceptions.Timeout("Connection timed out after 15s")
        with patch("requests.post", side_effect=timeout_err) as mock_post:
            with self.assertRaises(requests.exceptions.Timeout):
                self.wrapper.generate_song("ambient space")
        mock_post.assert_called_once()

    def test_get_timeout_propagates(self):
        timeout_err = requests.exceptions.Timeout("Read timed out")
        with patch("requests.get", side_effect=timeout_err) as mock_get:
            with self.assertRaises(requests.exceptions.Timeout):
                self.wrapper.check_song_status(["t1"])
        mock_get.assert_called_once()

    # 7. Malformed response bodies do not cause misleading errors
    def test_non_json_200_response_raises_response_error(self):
        mock_resp = make_mock_response(200, text="<html>Unexpected maintenance page</html>")
        with patch("requests.post", return_value=mock_resp):
            with self.assertRaises(UdioResponseError) as ctx:
                self.wrapper.generate_song("funk groove")

        self.assertIn("Failed to parse", str(ctx.exception))
        self.assertIs(ctx.exception.response, mock_resp)

    def test_missing_songs_key_in_check_song_status_raises_response_error(self):
        mock_resp = make_mock_response(200, payload={"unexpected_key": 123}, url="https://www.udio.com/api/songs")
        with patch("requests.get", return_value=mock_resp):
            with self.assertRaises(UdioResponseError) as ctx:
                self.wrapper.check_song_status(["track1"])

        self.assertIn("missing 'songs' list", str(ctx.exception))

    # 8. Cookie formatting is correct if that defect is confirmed
    def test_cookie_header_formatting_no_leading_semicolon(self):
        headers = self.wrapper.get_headers()
        cookie = headers["Cookie"]
        self.assertFalse(cookie.startswith(";"))
        self.assertEqual(cookie, f"sb-api-auth-token={self.secret_token}")

    def test_auth_token_sanitization(self):
        # Surrounding whitespace
        w1 = UdioWrapper("  my_token_with_spaces  ")
        self.assertEqual(w1.auth_token, "my_token_with_spaces")
        self.assertEqual(w1.get_headers()["Cookie"], "sb-api-auth-token=my_token_with_spaces")

        # Redundant 'sb-api-auth-token=' prefix from copy-paste
        w2 = UdioWrapper("sb-api-auth-token=actual_token_value")
        self.assertEqual(w2.auth_token, "actual_token_value")
        self.assertEqual(w2.get_headers()["Cookie"], "sb-api-auth-token=actual_token_value")

    def test_header_casing_and_structure(self):
        headers = self.wrapper.get_headers()
        self.assertIn("Sec-Fetch-Dest", headers)
        self.assertNotIn("sec-fetch-dest", headers)
        self.assertEqual(headers["Origin"], "https://www.udio.com")

    # 9. Logs and exceptions never leak authentication secrets
    def test_exceptions_and_outputs_never_leak_token(self):
        secret_leak_canary = "super_classified_token_999888"
        wrapper = UdioWrapper(secret_leak_canary)
        mock_resp = make_mock_response(500, text="Internal Server Error: DB connection failed")

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            with patch("requests.post", return_value=mock_resp):
                with self.assertRaises(UdioHTTPError) as ctx:
                    wrapper.generate_song("secret song prompt")

        # Verify token is absent in str(exception) and output streams
        self.assertNotIn(secret_leak_canary, str(ctx.exception))
        self.assertNotIn(secret_leak_canary, stdout_buf.getvalue())
        self.assertNotIn(secret_leak_canary, stderr_buf.getvalue())

    # 10. Existing generation methods continue to behave as expected
    def test_generate_extend_song_payload(self):
        mock_resp = make_mock_response(200, payload={"track_ids": ["ext_1"]})
        with patch("requests.post", return_value=mock_resp) as mock_post:
            res = self.wrapper.generate_extend_song(
                prompt="extend prompt",
                seed=42,
                audio_conditioning_path="https://example.com/audio.mp3",
                audio_conditioning_song_id="prev_song_123",
                custom_lyrics="extended lyrics",
            )
        self.assertEqual(res, {"track_ids": ["ext_1"]})
        self.assertEqual(
            mock_post.call_args.kwargs["json"],
            {
                "prompt": "extend prompt",
                "samplerOptions": {
                    "seed": 42,
                    "audio_conditioning_path": "https://example.com/audio.mp3",
                    "audio_conditioning_song_id": "prev_song_123",
                    "audio_conditioning_type": "continuation",
                },
                "lyricInput": "extended lyrics",
            },
        )

    def test_generate_outro_payload(self):
        mock_resp = make_mock_response(200, payload={"track_ids": ["outro_1"]})
        with patch("requests.post", return_value=mock_resp) as mock_post:
            res = self.wrapper.generate_outro(
                prompt="outro prompt",
                seed=99,
                audio_conditioning_path="https://example.com/audio2.mp3",
                audio_conditioning_song_id="prev_song_456",
                custom_lyrics="final lyrics",
            )
        self.assertEqual(res, {"track_ids": ["outro_1"]})
        self.assertEqual(
            mock_post.call_args.kwargs["json"],
            {
                "prompt": "outro prompt",
                "samplerOptions": {
                    "seed": 99,
                    "audio_conditioning_path": "https://example.com/audio2.mp3",
                    "audio_conditioning_song_id": "prev_song_456",
                    "audio_conditioning_type": "continuation",
                    "crop_start_time": 0.9,
                },
                "lyricInput": "final lyrics",
            },
        )

    def test_download_song_uses_timeout(self):
        mock_resp = requests.Response()
        mock_resp.status_code = 200
        mock_resp._content = b"fake-audio-bytes"

        with patch("requests.get", return_value=mock_resp) as mock_get:
            with patch("os.makedirs"):
                with patch("builtins.open", unittest.mock.mock_open()):
                    self.wrapper.download_song("https://cdn.example.com/song.mp3", "test_song")

        mock_get.assert_called_once_with("https://cdn.example.com/song.mp3", timeout=15.0)

    def test_invalid_init_parameters_rejected(self):
        for invalid_timeout in (None, False, True, 0, -5, float("inf"), float("nan"), "30"):
            with self.subTest(timeout=invalid_timeout):
                with self.assertRaises(ValueError):
                    UdioWrapper("valid_token", timeout=invalid_timeout)

        for invalid_token in ("", "   ", None, 12345):
            with self.subTest(token=invalid_token):
                with self.assertRaises(ValueError):
                    UdioWrapper(invalid_token)


if __name__ == "__main__":
    unittest.main()
