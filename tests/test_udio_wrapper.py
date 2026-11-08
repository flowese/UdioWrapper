import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from udio_wrapper import (
    CapSolverClient,
    TwoCaptchaClient,
    UdioCaptchaError,
    UdioWrapper,
)


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, content=b"mp3-bytes"):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.content = content

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests_http_error(self.status_code)


def requests_http_error(status_code: int):
    import requests

    err = requests.exceptions.HTTPError(f"{status_code} Server Error")
    resp = MagicMock()
    resp.status_code = status_code
    err.response = resp
    return err


class TestUdioWrapper(unittest.TestCase):
    def test_cookie_header_formats_single_and_split_tokens(self):
        wrapper = UdioWrapper("tok123")
        headers = wrapper.get_headers()
        self.assertEqual(headers["Cookie"], "sb-api-auth-token=tok123")

        split = UdioWrapper(
            "",
            auth_token_0="part0",
            auth_token_1="part1",
        )
        self.assertEqual(
            split.get_headers()["Cookie"],
            "sb-api-auth-token.0=part0; sb-api-auth-token.1=part1",
        )

        raw = UdioWrapper("sb-ssr-production-auth-token.0=a; sb-ssr-production-auth-token.1=b")
        self.assertEqual(
            raw.get_headers()["Cookie"],
            "sb-ssr-production-auth-token.0=a; sb-ssr-production-auth-token.1=b",
        )

    def test_generate_song_injects_static_captcha_token(self):
        session = MagicMock()
        session.post.return_value = DummyResponse(
            200, {"track_ids": ["track-1", "track-2"]}
        )
        wrapper = UdioWrapper(
            "tok123",
            captcha_token="hcap-static-token",
            session=session,
        )
        res = wrapper.generate_song("chill lo-fi beat", seed=42, custom_lyrics="hello")
        self.assertEqual(res, {"track_ids": ["track-1", "track-2"]})
        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"]["captchaToken"], "hcap-static-token")
        self.assertEqual(kwargs["json"]["lyricInput"], "hello")
        self.assertEqual(kwargs["headers"]["x-captcha-token"], "hcap-static-token")

    def test_auto_retry_on_500_with_fresh_captcha_solver(self):
        session = MagicMock()
        session.post.side_effect = [
            DummyResponse(500, {"error": "Internal Server Error"}),
            DummyResponse(200, {"track_ids": ["recovered-track"]}),
        ]
        tokens = iter(["initial-token", "fresh-solved-token"])
        solver = MagicMock(side_effect=lambda sitekey, url: next(tokens))

        wrapper = UdioWrapper(
            "tok123",
            captcha_solver=solver,
            retry_delay=0.0,
            max_retries=2,
            session=session,
        )
        result = wrapper.generate_song("synthwave")
        self.assertEqual(result, {"track_ids": ["recovered-track"]})
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(solver.call_count, 2)
        second_call_payload = session.post.call_args_list[1][1]["json"]
        self.assertEqual(second_call_payload["captchaToken"], "fresh-solved-token")

    def test_capsolver_client_solves_and_returns_token(self):
        session = MagicMock()
        session.post.side_effect = [
            DummyResponse(200, {"errorId": 0, "taskId": "task-99"}),
            DummyResponse(200, {"errorId": 0, "status": "processing"}),
            DummyResponse(
                200,
                {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": "capsolver-tok-abc"},
                },
            ),
        ]
        client = CapSolverClient("cs-key", poll_interval=0.0, session=session)
        tok = client.solve_hcaptcha("sitekey-1", "https://www.udio.com")
        self.assertEqual(tok, "capsolver-tok-abc")
        self.assertEqual(session.post.call_count, 3)

    def test_twocaptcha_client_solves_and_returns_token(self):
        session = MagicMock()
        session.post.return_value = DummyResponse(200, {"status": 1, "request": "id-77"})
        session.get.side_effect = [
            DummyResponse(200, {"status": 0, "request": "CAPCHA_NOT_READY"}),
            DummyResponse(200, {"status": 1, "request": "2captcha-tok-xyz"}),
        ]
        client = TwoCaptchaClient("2c-key", poll_interval=0.0, session=session)
        tok = client.solve_hcaptcha("sitekey-1", "https://www.udio.com")
        self.assertEqual(tok, "2captcha-tok-xyz")
        self.assertEqual(session.get.call_count, 2)

    def test_download_song_sanitizes_unsafe_title(self):
        session = MagicMock()
        session.get.return_value = DummyResponse(200, content=b"fake-mp3-data")
        wrapper = UdioWrapper("tok123", session=session)
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapper.download_song(
                "https://cdn.udio.com/track.mp3",
                "My Song: Part 1 / Remix?*",
                folder=tmpdir,
            )
            files = os.listdir(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].endswith(".mp3"))
            self.assertNotIn("/", files[0])
            self.assertNotIn(":", files[0])


if __name__ == "__main__":
    unittest.main()
