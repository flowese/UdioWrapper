import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure requests is mocked if not installed in the environment
if "requests" not in sys.modules:
    mock_requests = MagicMock()
    mock_requests.exceptions.RequestException = Exception
    mock_requests.exceptions.HTTPError = Exception
    sys.modules["requests"] = mock_requests

from udio_wrapper import UdioWrapper, CaptchaRequiredError
from udio_wrapper.hcaptcha_solver import HCaptchaSolver, is_hcaptcha_challenge


class TestUdioWrapperCaptcha(unittest.TestCase):
    def setUp(self):
        self.auth_token = "test-auth-token-12345"

    def test_cookie_header_no_leading_semicolon(self):
        wrapper = UdioWrapper(self.auth_token)
        headers = wrapper.get_headers()
        self.assertEqual(headers["Cookie"], f"sb-api-auth-token={self.auth_token}")
        self.assertFalse(headers["Cookie"].startswith(";"))

    def test_headers_with_captcha_token(self):
        wrapper = UdioWrapper(self.auth_token)
        headers = wrapper.get_headers(captcha_token="my-captcha-token")
        self.assertEqual(headers["h-captcha-response"], "my-captcha-token")

    def test_generate_song_includes_captcha_token_in_body_and_headers(self):
        wrapper = UdioWrapper(self.auth_token, captcha_token="static-token-xyz")
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"track_ids": ["abc-123"]}

        with patch("udio_wrapper.requests.post", return_value=mock_response) as mock_post:
            result = wrapper.generate_song("A smooth jazz song", seed=42)

            self.assertEqual(result, {"track_ids": ["abc-123"]})
            mock_post.assert_called_once()
            call_args, call_kwargs = mock_post.call_args

            self.assertEqual(call_args[0], "https://www.udio.com/api/generate-proxy")
            self.assertEqual(call_kwargs["json"]["captchaToken"], "static-token-xyz")
            self.assertEqual(call_kwargs["json"]["prompt"], "A smooth jazz song")
            self.assertEqual(call_kwargs["json"]["samplerOptions"]["seed"], 42)
            self.assertEqual(call_kwargs["headers"]["h-captcha-response"], "static-token-xyz")

    def test_generate_extend_and_outro_include_captcha_token(self):
        wrapper = UdioWrapper(self.auth_token, captcha_token="extend-outro-token")
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"track_ids": ["extended-1"]}

        with patch("udio_wrapper.requests.post", return_value=mock_response) as mock_post:
            wrapper.generate_extend_song("extended prompt", 123, "song.mp3", "song-id-1")
            call_kwargs = mock_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["captchaToken"], "extend-outro-token")

        with patch("udio_wrapper.requests.post", return_value=mock_response) as mock_post:
            wrapper.generate_outro("outro prompt", 123, "song.mp3", "song-id-1")
            call_kwargs = mock_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["captchaToken"], "extend-outro-token")

    def test_dynamic_captcha_solver_callback(self):
        solver_mock = MagicMock(return_value="dynamically-solved-token")
        wrapper = UdioWrapper(self.auth_token, captcha_solver=solver_mock)

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"track_ids": ["dynamic-track"]}

        with patch("udio_wrapper.requests.post", return_value=mock_response) as mock_post:
            result = wrapper.generate_song("Electronic beats", seed=-1)

            solver_mock.assert_called()
            self.assertEqual(result, {"track_ids": ["dynamic-track"]})
            call_kwargs = mock_post.call_args[1]
            self.assertEqual(call_kwargs["json"]["captchaToken"], "dynamically-solved-token")

    def test_env_var_captcha_token(self):
        with patch.dict("os.environ", {"UDIO_CAPTCHA_TOKEN": "token-from-env"}):
            wrapper = UdioWrapper(self.auth_token)
            self.assertEqual(wrapper.resolve_captcha_token(), "token-from-env")

    def test_is_hcaptcha_challenge_detection(self):
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.url = "https://www.udio.com/api/generate-proxy"
        self.assertTrue(is_hcaptcha_challenge(resp_500))

        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.url = "https://www.udio.com/api/generate-proxy"
        self.assertTrue(is_hcaptcha_challenge(resp_403))

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.url = "https://www.udio.com/api/generate-proxy"
        self.assertFalse(is_hcaptcha_challenge(resp_ok))

    def test_500_error_retry_with_solver_refresh(self):
        solver_mock = MagicMock(side_effect=["initial-token", "refreshed-token"])
        wrapper = UdioWrapper(self.auth_token, captcha_solver=solver_mock, max_retries=0)

        # First request returns 500 Server Error
        err_resp = MagicMock()
        err_resp.ok = False
        err_resp.status_code = 500
        err_resp.url = "https://www.udio.com/api/generate-proxy"
        err_resp.text = "Internal Server Error"

        # Second request succeeds
        ok_resp = MagicMock()
        ok_resp.ok = True
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"track_ids": ["recovered-id"]}

        with patch("udio_wrapper.requests.post", side_effect=[err_resp, ok_resp]) as mock_post:
            res = wrapper.generate_song("Rock solo", seed=99)
            self.assertEqual(res, {"track_ids": ["recovered-id"]})
            self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
