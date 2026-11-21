import unittest
from unittest.mock import Mock, patch

import requests

from udio_wrapper import (
    UdioChallengeError,
    UdioRequestError,
    UdioWrapper,
)


def make_response(status_code=200, text="", json_data=None):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    response.url = "https://www.udio.com/api/generate-proxy"
    response.ok = 200 <= status_code < 400
    response.json.return_value = json_data

    def raise_for_status():
        if status_code >= 400:
            error = requests.exceptions.HTTPError(
                f"{status_code} Server Error",
                response=response,
            )
            raise error

    response.raise_for_status.side_effect = raise_for_status
    return response


class UdioWrapperErrorTests(unittest.TestCase):
    def test_default_mode_returns_none_for_http_error(self):
        response = make_response(500, "Internal Server Error")

        with patch("udio_wrapper.requests.post", return_value=response):
            wrapper = UdioWrapper("token")
            self.assertIsNone(wrapper.generate_song("prompt", -1))

    def test_raise_on_error_returns_structured_request_error(self):
        response = make_response(500, "Internal Server Error")

        with patch("udio_wrapper.requests.post", return_value=response):
            wrapper = UdioWrapper("token", raise_on_error=True)
            with self.assertRaises(UdioRequestError) as context:
                wrapper.generate_song("prompt", -1)

        self.assertEqual(context.exception.status_code, 500)
        self.assertEqual(
            context.exception.url,
            "https://www.udio.com/api/generate-proxy",
        )

    def test_challenge_response_raises_challenge_error(self):
        response = make_response(
            403,
            "<html><title>Just a moment</title><script>hCaptcha</script></html>",
        )

        with patch("udio_wrapper.requests.post", return_value=response):
            wrapper = UdioWrapper("token", raise_on_error=True)
            with self.assertRaises(UdioChallengeError) as context:
                wrapper.generate_song("prompt", -1)

        self.assertEqual(context.exception.status_code, 403)
        self.assertIn("hCaptcha", context.exception.response_text)

    def test_successful_response_is_parsed(self):
        response = make_response(
            200,
            '{"track_ids":["track-1"]}',
            {"track_ids": ["track-1"]},
        )

        with patch("udio_wrapper.requests.post", return_value=response):
            wrapper = UdioWrapper("token")
            self.assertEqual(
                wrapper.generate_song("prompt", -1),
                {"track_ids": ["track-1"]},
            )

    def test_invalid_json_returns_none_by_default(self):
        response = make_response(200, "not-json")
        response.json.side_effect = ValueError("invalid JSON")

        with patch("udio_wrapper.requests.post", return_value=response):
            wrapper = UdioWrapper("token")
            self.assertIsNone(wrapper.generate_song("prompt", -1))

    def test_request_timeout_is_passed_to_requests(self):
        response = make_response(
            200,
            '{"track_ids":[]}',
            {"track_ids": []},
        )

        with patch("udio_wrapper.requests.post", return_value=response) as post:
            wrapper = UdioWrapper("token", timeout=12)
            wrapper.generate_song("prompt", -1)

        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["timeout"], 12)


if __name__ == "__main__":
    unittest.main()
