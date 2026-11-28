import unittest
from unittest.mock import patch, MagicMock

from udio_wrapper import UdioWrapper

class TestUdioWrapperHeaders(unittest.TestCase):
    def setUp(self):
        self.auth_token = "test-token-123"
        self.wrapper = UdioWrapper(self.auth_token)

    def test_get_headers_cookie_format(self):
        """Ensure the Cookie header does not contain a leading semicolon."""
        headers = self.wrapper.get_headers()
        self.assertIn("Cookie", headers)
        self.assertEqual(headers["Cookie"], f"sb-api-auth-token={self.auth_token}")

    @patch("udio_wrapper.__init__.requests.post")
    def test_make_request_post_success(self, mock_post):
        """make_request should return the response object on success."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        url = "https://example.com/api"
        data = {"key": "value"}
        headers = {"Header": "value"}

        response = self.wrapper.make_request(url, "POST", data=data, headers=headers)

        mock_post.assert_called_once_with(url, headers=headers, json=data)
        self.assertIs(response, mock_response)

    @patch("udio_wrapper.__init__.requests.post")
    def test_make_request_post_failure(self, mock_post):
        """make_request should return None on exception."""
        mock_post.side_effect = Exception("Network error")
        response = self.wrapper.make_request("https://example.com", "POST")
        self.assertIsNone(response)

if __name__ == "__main__":
    unittest.main()
