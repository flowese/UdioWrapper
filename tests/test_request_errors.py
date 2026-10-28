"""Offline regression coverage for requests and public generation methods."""

import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import requests

from udio_wrapper import (
    UdioAuthenticationError,
    UdioChallengeError,
    UdioHTTPError,
    UdioWrapper,
)


API_URL = "https://www.udio.com/api/generate-proxy"


def response(status=200, payload=None, body=None):
    result = requests.Response()
    result.status_code = status
    result.url = API_URL
    result.request = requests.Request(
        "POST", API_URL, headers={"Cookie": "secret-cookie"}
    ).prepare()
    result._content = (
        body.encode("utf-8") if body is not None
        else json.dumps(payload if payload is not None else {}).encode("utf-8")
    )
    return result


class RequestErrorTests(unittest.TestCase):
    def setUp(self):
        self.wrapper = UdioWrapper("secret-cookie")

    def test_success_preserves_response_and_uses_default_timeout(self):
        upstream = response(payload={"track_ids": ["track-1"]})
        with patch("udio_wrapper.requests.post", return_value=upstream) as post:
            actual = self.wrapper.make_request(API_URL, "POST", {"prompt": "jazz"})
        self.assertIs(actual, upstream)
        post.assert_called_once_with(
            API_URL, headers=None, json={"prompt": "jazz"}, timeout=30
        )

    def test_custom_timeout_is_forwarded_to_get(self):
        wrapper = UdioWrapper("token", timeout=4.5)
        upstream = response()
        with patch("udio_wrapper.requests.get", return_value=upstream) as get:
            self.assertIs(wrapper.make_request(API_URL, "get"), upstream)
        get.assert_called_once_with(API_URL, headers=None, timeout=4.5)

    def test_invalid_timeouts_are_rejected_before_any_request(self):
        for timeout in (None, True, False, 0, -1, float("inf"), float("nan"), "30"):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    UdioWrapper("token", timeout=timeout)

    def test_unsupported_method_does_not_send_a_get(self):
        with patch("udio_wrapper.requests.get") as get:
            with self.assertRaises(ValueError):
                self.wrapper.make_request(API_URL, "DELETE")
        get.assert_not_called()

    def test_generic_http_errors_are_not_assumed_to_be_captcha(self):
        for status in (403, 429, 500, 502, 503):
            for body in ("Internal Server Error", '{"error": "service_unavailable"}'):
                with self.subTest(status=status, body=body):
                    upstream = response(status, body=body)
                    with patch("udio_wrapper.requests.post", return_value=upstream) as post:
                        with self.assertRaises(UdioHTTPError) as caught:
                            self.wrapper.make_request(API_URL, "POST")
                    self.assertIs(type(caught.exception), UdioHTTPError)
                    self.assertIs(caught.exception.response, upstream)
                    self.assertIs(caught.exception.request, upstream.request)
                    self.assertIn(str(status), str(caught.exception))
                    post.assert_called_once()

    def test_401_has_authentication_guidance(self):
        upstream = response(401)
        with patch("udio_wrapper.requests.post", return_value=upstream):
            with self.assertRaises(UdioAuthenticationError) as caught:
                self.wrapper.make_request(API_URL, "POST")
        self.assertIsInstance(caught.exception, requests.HTTPError)
        self.assertIs(caught.exception.response, upstream)
        self.assertIn("authentication", str(caught.exception))

    def test_explicit_json_challenges_have_manual_verification_guidance(self):
        payloads = (
            {"error": "captcha_required"},
            {"code": "HCAPTCHA_REQUIRED"},
            {"error_code": "human_verification_required"},
            {"error": {"code": "captcha_verification_required"}},
        )
        for status in (200, 403, 500):
            for payload in payloads:
                with self.subTest(status=status, payload=payload):
                    upstream = response(status, payload=payload)
                    with patch("udio_wrapper.requests.post", return_value=upstream) as post:
                        with self.assertRaises(UdioChallengeError) as caught:
                            self.wrapper.make_request(API_URL, "POST")
                    self.assertIsInstance(caught.exception, requests.HTTPError)
                    self.assertIs(caught.exception.response, upstream)
                    self.assertIn("normal browser", str(caught.exception))
                    self.assertIn("may not enable API access", str(caught.exception))
                    post.assert_called_once()

    def test_html_challenge_page_is_recognized_even_with_http_200(self):
        body = '<!DOCTYPE html><html><div class="widget h-captcha active"></div></html>'
        for status in (200, 403, 500):
            with self.subTest(status=status):
                upstream = response(status, body=body)
                with patch("udio_wrapper.requests.post", return_value=upstream):
                    with self.assertRaises(UdioChallengeError):
                        self.wrapper.make_request(API_URL, "POST")

    def test_similar_html_class_is_not_a_challenge(self):
        upstream = response(500, body='<html><div class="not-h-captcha"></div></html>')
        with patch("udio_wrapper.requests.post", return_value=upstream):
            with self.assertRaises(UdioHTTPError) as caught:
                self.wrapper.make_request(API_URL, "POST")
        self.assertIs(type(caught.exception), UdioHTTPError)

    def test_successful_prompt_mentioning_captcha_is_not_a_challenge(self):
        upstream = response(payload={
            "track_ids": ["track-1"],
            "prompt": "captcha_required <div class='h-captcha'> hCaptcha song",
        })
        with patch("udio_wrapper.requests.post", return_value=upstream):
            self.assertIs(self.wrapper.make_request(API_URL, "POST"), upstream)

    def test_plain_text_mention_is_not_proof_of_a_challenge(self):
        upstream = response(500, body="A captcha service is temporarily unavailable")
        with patch("udio_wrapper.requests.post", return_value=upstream):
            with self.assertRaises(UdioHTTPError) as caught:
                self.wrapper.make_request(API_URL, "POST")
        self.assertIs(type(caught.exception), UdioHTTPError)

    def test_large_json_is_not_reinterpreted_as_html(self):
        upstream = response(payload={
            "prompt": "<div class='h-captcha'>" + "x" * 10000,
            "track_ids": ["track-1"],
        })
        with patch("udio_wrapper.requests.post", return_value=upstream):
            self.assertIs(self.wrapper.make_request(API_URL, "POST"), upstream)

    def test_deep_malformed_error_json_still_raises_http_error(self):
        upstream = response(500, body="[" * 1500)
        with patch("udio_wrapper.requests.post", return_value=upstream):
            with self.assertRaises(UdioHTTPError) as caught:
                self.wrapper.make_request(API_URL, "POST")
        self.assertIs(type(caught.exception), UdioHTTPError)

    def test_error_inspection_is_limited_to_a_small_prefix(self):
        upstream = response(500, body=" " * 8192 + '<div class="h-captcha"></div>')
        with patch("udio_wrapper.requests.post", return_value=upstream):
            with self.assertRaises(UdioHTTPError) as caught:
                self.wrapper.make_request(API_URL, "POST")
        self.assertIs(type(caught.exception), UdioHTTPError)

    def test_public_generation_methods_propagate_challenge_without_polling(self):
        calls = (
            ("create_song", ("jazz",)),
            ("extend", ("jazz",)),
            ("add_outro", ("jazz",)),
        )
        for method, args in calls:
            with self.subTest(method=method):
                upstream = response(500, payload={"error": "captcha_required"})
                with patch("udio_wrapper.requests.post", return_value=upstream) as post:
                    with patch("udio_wrapper.requests.get") as get:
                        with self.assertRaises(UdioChallengeError):
                            getattr(self.wrapper, method)(*args)
                post.assert_called_once()
                get.assert_not_called()
                self.assertEqual(self.wrapper.all_track_ids, [])

    def test_all_generation_payloads_keep_their_existing_parameters(self):
        calls = (
            ("generate_song", ("jazz", 42, "lyrics"), {}),
            ("generate_extend_song", ("jazz", 42, "path", "id", "lyrics"), {
                "audio_conditioning_path": "path", "audio_conditioning_song_id": "id",
                "audio_conditioning_type": "continuation",
            }),
            ("generate_outro", ("jazz", 42, "path", "id", "lyrics"), {
                "audio_conditioning_path": "path", "audio_conditioning_song_id": "id",
                "audio_conditioning_type": "continuation", "crop_start_time": 0.9,
            }),
        )
        for method, args, options in calls:
            with self.subTest(method=method):
                upstream = response(payload={"track_ids": ["track-1"]})
                with patch("udio_wrapper.requests.post", return_value=upstream) as post:
                    self.assertEqual(getattr(self.wrapper, method)(*args), {"track_ids": ["track-1"]})
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs["json"], {
                    "prompt": "jazz", "samplerOptions": dict(seed=42, **options),
                    "lyricInput": "lyrics",
                })
                self.assertEqual(post.call_args.kwargs["timeout"], 30)

    def test_timeout_and_connection_failures_propagate_without_retry(self):
        for failure in (requests.Timeout("timeout"), requests.ConnectionError("offline")):
            with self.subTest(failure=type(failure).__name__):
                with patch("udio_wrapper.requests.post", side_effect=failure) as post:
                    with self.assertRaises(type(failure)) as caught:
                        self.wrapper.generate_song("jazz", -1)
                self.assertIs(caught.exception, failure)
                post.assert_called_once()

    def test_status_queries_propagate_error_instead_of_returning_none(self):
        upstream = response(503)
        with patch("udio_wrapper.requests.get", return_value=upstream) as get:
            with self.assertRaises(UdioHTTPError):
                self.wrapper.check_song_status(["track-1"])
        get.assert_called_once()

    def test_http_error_messages_and_output_do_not_expose_request_data(self):
        upstream = response(500, body="secret-body secret-prompt secret-cookie")
        upstream.url = API_URL + "?secret-query"
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            with patch("udio_wrapper.requests.post", return_value=upstream):
                with self.assertRaises(UdioHTTPError) as caught:
                    self.wrapper.make_request(
                        upstream.url, "POST", {"prompt": "secret-prompt"},
                        {"Cookie": "secret-cookie"},
                    )
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("secret-", str(caught.exception))

    def test_cookie_header_has_no_empty_leading_cookie(self):
        self.assertEqual(self.wrapper.get_headers()["Cookie"], "sb-api-auth-token=secret-cookie")


if __name__ == "__main__":
    unittest.main()
