import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
from udio_wrapper import UdioWrapper


class TestUdioWrapper(unittest.TestCase):

    def setUp(self):
        self.wrapper = UdioWrapper(auth_token="test_token", captcha_token="test_captcha")

    def test_init_and_headers(self):
        headers = self.wrapper.get_headers()
        self.assertEqual(headers["Cookie"], "; sb-api-auth-token=test_token")
        self.assertEqual(headers["h-captcha-response"], "test_captcha")
        self.assertEqual(headers["x-captcha-token"], "test_captcha")

    @patch("requests.post")
    def test_generate_song_includes_captcha(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"track_ids": ["123", "456"]}
        mock_post.return_value = mock_resp

        res = self.wrapper.generate_song("a funky beat", 42)
        self.assertIsNotNone(res)
        self.assertEqual(res["track_ids"], ["123", "456"])

        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs["json"]["captchaToken"], "test_captcha")
        self.assertEqual(call_kwargs["json"]["hCaptchaToken"], "test_captcha")

    @patch("requests.post")
    def test_server_500_error_handled_gracefully(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error - hCaptcha required"
        mock_post.return_value = mock_resp

        res = self.wrapper.make_request("https://www.udio.com/api/generate-proxy", "POST", {})
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
