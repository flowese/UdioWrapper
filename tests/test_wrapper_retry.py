import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import udio_wrapper
from udio_wrapper import (
    UdioAPIError,
    UdioAuthError,
    UdioChallengeError,
    UdioError,
    UdioWrapper,
)

BANNED = ("2captcha", "capsolver", "nopecha", "solver_callback", "hcaptchasolver",
          "captchatoken", "h-captcha-response")


def make_response(status=200, text="", reason="OK", json_data=None):
    response = Mock()
    response.ok = 200 <= status < 400
    response.status_code = status
    response.reason = reason
    response.text = text
    if json_data is not None:
        response.json = lambda: json_data
    else:
        response.json = lambda: (_ for _ in ()).throw(ValueError("no json"))
    return response


class DiagnosisTests(unittest.TestCase):
    def test_500_is_challenge_block(self):
        self.assertTrue(UdioWrapper("t").is_challenge_block(make_response(500, "err")))

    def test_403_is_challenge_block(self):
        self.assertTrue(UdioWrapper("t").is_challenge_block(make_response(403, "err")))

    def test_503_is_challenge_block(self):
        self.assertTrue(UdioWrapper("t").is_challenge_block(make_response(503, "err")))

    def test_captcha_keyword_is_challenge_block(self):
        self.assertTrue(UdioWrapper("t").is_challenge_block(make_response(400, '{"error":"captcha required"}')))

    def test_bot_keyword_is_challenge_block(self):
        self.assertTrue(UdioWrapper("t").is_challenge_block(make_response(400, "bot detected")))

    def test_clean_200_is_not_challenge_block(self):
        self.assertFalse(UdioWrapper("t").is_challenge_block(make_response(200, "{}")))

    def test_none_is_not_challenge_block(self):
        self.assertFalse(UdioWrapper("t").is_challenge_block(None))

    def test_retryable_statuses(self):
        w = UdioWrapper("t")
        for code in (429, 500, 502, 503, 504):
            self.assertTrue(w.is_retryable_status(code))
        for code in (200, 400, 401, 403):
            self.assertFalse(w.is_retryable_status(code))


class GuidanceTests(unittest.TestCase):
    def test_challenge_guidance_mentions_browser_and_udio(self):
        text = UdioWrapper("t").get_challenge_guidance(500, "https://www.udio.com/api/generate-proxy").lower()
        self.assertIn("browser", text)
        self.assertIn("udio.com", text)

    def test_guidance_has_no_banned_automation_terms(self):
        w = UdioWrapper("t")
        text = (w.get_challenge_guidance() + w.get_auth_guidance()).lower()
        for term in BANNED:
            self.assertNotIn(term, text)

    def test_auth_guidance_mentions_cookie_and_udio(self):
        text = UdioWrapper("t").get_auth_guidance().lower()
        self.assertIn("udio.com", text)
        self.assertIn("cookie", text)


class RetryBehaviorTests(unittest.TestCase):
    @patch("udio_wrapper.requests.post")
    def test_transient_500_then_200_succeeds(self, post):
        post.side_effect = [make_response(500, "err", "ISE"), make_response(200, "{}", "OK", {"track_ids": ["a"]})]
        with patch("udio_wrapper.time.sleep"):
            w = UdioWrapper("t")
            result = w.generate_song("hi", -1)
        self.assertEqual(result, {"track_ids": ["a"]})
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            data = call.kwargs.get("json", {}) or {}
            self.assertNotIn("captchaToken", data)
            self.assertNotIn("captchaToken", str(call.kwargs.get("headers")))

    @patch("udio_wrapper.requests.post")
    def test_persistent_500_returns_none_and_prints_guidance(self, post):
        post.return_value = make_response(500, "Internal Server Error", "ISE")
        out = io.StringIO()
        with patch("udio_wrapper.time.sleep"), redirect_stdout(out):
            w = UdioWrapper("t")
            result = w.generate_song("hi", -1)
        self.assertIsNone(result)
        self.assertIn("udio.com", out.getvalue().lower())
        self.assertEqual(post.call_count, 3)

    @patch("udio_wrapper.requests.post")
    def test_401_fails_fast_single_call(self, post):
        post.return_value = make_response(401, '{"error":"Unauthorized"}', "Unauthorized")
        with redirect_stdout(io.StringIO()):
            w = UdioWrapper("t")
            result = w.generate_song("hi", -1)
        self.assertIsNone(result)
        self.assertEqual(post.call_count, 1)

    @patch("udio_wrapper.requests.post")
    def test_429_retries_then_succeeds(self, post):
        post.side_effect = [make_response(429, "rate", "Too Many"), make_response(200, "{}", "OK", {"ok": True})]
        with patch("udio_wrapper.time.sleep"):
            w = UdioWrapper("t")
            result = w.generate_song("hi", -1)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(post.call_count, 2)

    @patch("udio_wrapper.requests.post")
    def test_network_error_retries(self, post):
        post.side_effect = [udio_wrapper.requests.exceptions.ConnectionError("boom"),
                            make_response(200, "{}", "OK", {"ok": 1})]
        with patch("udio_wrapper.time.sleep"):
            w = UdioWrapper("t")
            result = w.generate_song("hi", -1)
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(post.call_count, 2)

    @patch("udio_wrapper.requests.post")
    def test_raise_on_error_raises_challenge_error(self, post):
        post.return_value = make_response(500, "Internal Server Error", "ISE")
        with patch("udio_wrapper.time.sleep"), redirect_stdout(io.StringIO()):
            w = UdioWrapper("t", raise_on_error=True)
            with self.assertRaises(UdioChallengeError):
                w.generate_song("hi", -1)

    @patch("udio_wrapper.requests.post")
    def test_raise_on_error_raises_auth_error(self, post):
        post.return_value = make_response(401, "Unauthorized", "Unauthorized")
        with redirect_stdout(io.StringIO()):
            w = UdioWrapper("t", raise_on_error=True)
            with self.assertRaises(UdioAuthError):
                w.generate_song("hi", -1)

    def test_no_solver_attributes(self):
        w = UdioWrapper("t")
        for name in ("captcha_solver", "solver_callback", "captcha_token", "hcaptcha_token"):
            self.assertFalse(hasattr(w, name))

    def test_exceptions_hierarchy(self):
        self.assertTrue(issubclass(UdioAuthError, UdioError))
        self.assertTrue(issubclass(UdioChallengeError, UdioError))
        self.assertTrue(issubclass(UdioAPIError, UdioError))


class HeaderCookieTests(unittest.TestCase):
    def test_cookie_name_configurable(self):
        w = UdioWrapper("tok", cookie_name="sb-ssr-production-auth-token")
        self.assertEqual(w.get_headers()["Cookie"], "sb-ssr-production-auth-token=tok")

    def test_cookie_no_leading_semicolon(self):
        w = UdioWrapper("tok")
        self.assertFalse(w.get_headers()["Cookie"].startswith(";"))

    def test_headers_include_accept_language(self):
        self.assertIn("Accept-Language", UdioWrapper("t").get_headers())


class HardeningTests(unittest.TestCase):
    def test_process_songs_empty_track_ids(self):
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(UdioWrapper("t").process_songs([], "x"))

    def test_check_song_status_empty_ids(self):
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(UdioWrapper("t").check_song_status([]))

    def test_sanitize_filename_strips_illegal_chars(self):
        w = UdioWrapper("t")
        self.assertEqual(w._sanitize_filename('a\\b/c:d*e?f"g<h>i|j'), "abcdefghij")

    def test_sanitize_filename_length_cap(self):
        w = UdioWrapper("t")
        self.assertLessEqual(len(w._sanitize_filename("x" * 500)), 120)

    def test_sanitize_filename_blank_becomes_track(self):
        w = UdioWrapper("t")
        self.assertEqual(w._sanitize_filename("   "), "track")

    @patch("udio_wrapper.requests.post")
    def test_create_song_returns_none_on_missing_track_ids(self, post):
        post.return_value = make_response(200, "{}", "OK", {})
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(UdioWrapper("t").create_song("hi"))

    @patch("udio_wrapper.requests.get")
    def test_check_song_status_bad_json(self, get):
        get.return_value = make_response(200, "not json", "OK")
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(UdioWrapper("t").check_song_status(["a"]))

    @patch("udio_wrapper.requests.get")
    def test_process_songs_skips_moderation_and_missing_path(self, get):
        status = make_response(200, "{}", "OK", {
            "songs": [
                {"id": "1", "finished": True, "moderation": True, "song_path": "http://x"},
                {"id": "2", "finished": True},
            ]
        })
        get.return_value = status
        with redirect_stdout(io.StringIO()):
            result = UdioWrapper("t").process_songs(["1", "2"], "x", poll_interval=0)
        self.assertEqual(result, [])

    @patch("udio_wrapper.requests.get")
    def test_download_song_returns_none_on_failure(self, get):
        get.side_effect = udio_wrapper.requests.exceptions.ConnectionError("down")
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(UdioWrapper("t").download_song("http://x", "t", folder="z_tmp_dl"))


if __name__ == "__main__":
    unittest.main()
