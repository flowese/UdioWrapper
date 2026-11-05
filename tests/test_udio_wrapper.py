import os
import unittest
from unittest.mock import MagicMock, patch

from udio_wrapper import UdioWrapper, CaptchaRequiredError, UdioAPIError
from udio_wrapper.hcaptcha_solver import (
    HCaptchaSolver,
    is_hcaptcha_challenge,
    UDIO_HCAPTCHA_SITEKEY,
)


class TestUdioWrapper(unittest.TestCase):
    def setUp(self):
        self.auth_token = "test_auth_token_xyz"
        self.wrapper = UdioWrapper(self.auth_token)

    def test_headers_without_leading_semicolon(self):
        headers = self.wrapper.get_headers()
        self.assertEqual(headers["Cookie"], f"sb-api-auth-token={self.auth_token}")
        self.assertFalse(headers["Cookie"].startswith(";"))

    def test_headers_with_captcha_token(self):
        captcha_token = "captcha-test-token-123"
        headers = self.wrapper.get_headers(captcha_token=captcha_token)
        self.assertEqual(headers["h-captcha-response"], captcha_token)

    def test_resolve_captcha_token_from_init(self):
        w = UdioWrapper(self.auth_token, captcha_token="custom_token")
        self.assertEqual(w.resolve_captcha_token(), "custom_token")

    def test_resolve_captcha_token_from_callable(self):
        solver = MagicMock(return_value="solved_token_abc")
        w = UdioWrapper(self.auth_token, captcha_solver=solver)
        self.assertEqual(w.resolve_captcha_token(), "solved_token_abc")
        solver.assert_called_once()

    def test_resolve_captcha_token_from_env(self):
        with patch.dict(os.environ, {"UDIO_CAPTCHA_TOKEN": "env_token_456"}):
            w = UdioWrapper(self.auth_token)
            self.assertEqual(w.resolve_captcha_token(), "env_token_456")

    @patch("udio_wrapper.requests.post")
    def test_generate_song_injects_captcha_token_in_body(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"track_ids": ["track_1", "track_2"]}
        mock_post.return_value = mock_resp

        w = UdioWrapper(self.auth_token, captcha_token="my_token")
        result = w.generate_song("a funky disco beat", seed=42)

        self.assertIsNotNone(result)
        self.assertEqual(result["track_ids"], ["track_1", "track_2"])

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["captchaToken"], "my_token")
        self.assertEqual(kwargs["headers"]["h-captcha-response"], "my_token")

    def test_is_hcaptcha_challenge_detection(self):
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.url = "https://www.udio.com/api/generate-proxy"
        resp_500.text = "Internal Server Error"
        self.assertTrue(is_hcaptcha_challenge(resp_500))

        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.url = "https://www.udio.com/api/generate-proxy"
        self.assertTrue(is_hcaptcha_challenge(resp_403))

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.url = "https://www.udio.com/api/songs"
        resp_200.text = '{"songs": []}'
        self.assertFalse(is_hcaptcha_challenge(resp_200))


if __name__ == "__main__":
    unittest.main()
