"""Regression tests for generate-proxy / hCaptcha handling (Fixes #7)."""

from unittest.mock import Mock, patch

import pytest
import requests

from udio_wrapper import UdioWrapper, UdioChallengeError, UdioAuthError, CaptchaRequiredError


def test_cookie_has_no_leading_semicolon():
    w = UdioWrapper("tok")
    assert w.get_headers()["Cookie"] == "sb-api-auth-token=tok"


def test_cookie_name_supports_ssr_token():
    w = UdioWrapper("tok", cookie_name="sb-ssr-production-auth-token")
    assert w.get_headers()["Cookie"] == "sb-ssr-production-auth-token=tok"


def test_generate_proxy_500_raises_challenge():
    w = UdioWrapper("tok", max_retries=0)
    resp = Mock()
    resp.status_code = 500
    resp.url = "https://www.udio.com/api/generate-proxy"
    resp.text = "Internal Server Error"
    err = requests.exceptions.HTTPError("500", response=resp)
    with patch("udio_wrapper.requests.post", side_effect=err):
        with pytest.raises(UdioChallengeError, match="human verification|hCaptcha"):
            w.make_request("https://www.udio.com/api/generate-proxy", "POST", {}, w.get_headers())


def test_generate_proxy_500_retry_transient():
    w = UdioWrapper("tok", max_retries=1, retry_backoff=0.01)
    resp = Mock()
    resp.status_code = 500
    resp.url = "https://www.udio.com/api/generate-proxy"
    resp.text = "Internal Server Error"
    err = requests.exceptions.HTTPError("500", response=resp)
    ok = Mock()
    ok.raise_for_status = Mock()
    ok.status_code = 200
    with patch("udio_wrapper.requests.post", side_effect=[err, ok]) as p:
        r = w.make_request("https://www.udio.com/api/generate-proxy", "POST", {"prompt": "x"}, w.get_headers())
        assert r is ok
        assert p.call_count == 2


def test_hcaptcha_token_injected():
    w = UdioWrapper("tok", hcaptcha_token="manual-token", max_retries=0)
    ok = Mock()
    ok.raise_for_status = Mock()
    ok.status_code = 200
    with patch("udio_wrapper.requests.post", return_value=ok) as p:
        w.make_request("https://www.udio.com/api/generate-proxy", "POST", {"prompt": "hi"}, w.get_headers())
        kwargs = p.call_args[1]
        assert kwargs["json"]["captchaToken"] == "manual-token"
        assert kwargs["json"]["hcaptchaToken"] == "manual-token"
        assert kwargs["headers"]["x-captcha-token"] == "manual-token"


def test_401_raises_auth_error():
    w = UdioWrapper("tok", max_retries=0)
    resp = Mock()
    resp.status_code = 401
    resp.url = "https://www.udio.com/api/songs?songIds=a"
    resp.text = "Unauthorized"
    err = requests.exceptions.HTTPError("401", response=resp)
    with patch("udio_wrapper.requests.get", side_effect=err):
        with pytest.raises(UdioAuthError):
            w.make_request("https://www.udio.com/api/songs?songIds=a", "GET", None, w.get_headers(True))


def test_generate_song_propagates_challenge_not_silent_none():
    w = UdioWrapper("tok", max_retries=0)
    with patch.object(w, "make_request", side_effect=UdioChallengeError("challenge")):
        with pytest.raises(UdioChallengeError):
            w.generate_song("prompt", -1)


def test_backwards_compat_alias():
    assert CaptchaRequiredError is UdioChallengeError


def test_response_json_invalid_returns_none():
    w = UdioWrapper("tok")
    m = Mock()
    m.json.side_effect = ValueError("bad")
    assert w._response_json(m) is None


def test_generate_proxy_uses_valid_auth_cookie_and_payload():
    wrapper = UdioWrapper("token")
    response = Mock()
    response.json.return_value = {"track_ids": ["track"]}
    with patch("udio_wrapper.requests.post", return_value=response) as post:
        assert wrapper.generate_song("jazz", 12, "lyrics") == {"track_ids": ["track"]}
    assert wrapper.get_headers()["Cookie"] == "sb-api-auth-token=token"
    post.assert_called_once_with(
        "https://www.udio.com/api/generate-proxy",
        headers=wrapper.get_headers(),
        json={"prompt": "jazz", "samplerOptions": {"seed": 12}, "lyricInput": "lyrics"},
    )
