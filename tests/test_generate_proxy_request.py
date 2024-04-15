from unittest.mock import Mock, patch

from udio_wrapper import UdioWrapper


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


def test_generate_song_returns_none_for_request_failure():
    wrapper = UdioWrapper("token")
    with patch.object(wrapper, "make_request", return_value=None):
        assert wrapper.generate_song("jazz", -1) is None


def test_generate_song_returns_none_for_invalid_json_response():
    wrapper = UdioWrapper("token")
    response = Mock()
    response.json.side_effect = ValueError("invalid JSON")
    with patch.object(wrapper, "make_request", return_value=response):
        assert wrapper.generate_song("jazz", -1) is None
