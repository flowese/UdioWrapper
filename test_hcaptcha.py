"""
Unit tests for UdioWrapper hCaptcha solver.
"""

import os
import sys
import time
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from udio_wrapper.hcaptcha_solver import HCaptchaSolver


def test_sitekey_extraction():
    """Test sitekey extraction from HTML."""
    solver = HCaptchaSolver()
    
    # Test data-sitekey pattern
    html = 'data-sitekey="4c672d35-0701-42b2-88c3-78380b0db560"'
    key = solver._extract_sitekey(html)
    assert key == "4c672d35-0701-42b2-88c3-78380b0db560", f"Expected sitekey, got {key}"
    
    # Test websiteKey pattern
    html = "websiteKey: '4c672d35-0701-42b2-88c3-78380b0db560'"
    key = solver._extract_sitekey(html)
    assert key == "4c672d35-0701-42b2-88c3-78380b0db560", f"Expected sitekey, got {key}"
    
    # Test fallback when no pattern matches
    html = "no captcha here"
    key = solver._extract_sitekey(html)
    assert key is None, f"Expected None, got {key}"
    
    print("test_sitekey_extraction: PASSED")


def test_cache_logic():
    """Test cache validation logic."""
    solver = HCaptchaSolver()
    
    # Not cached initially
    assert not solver._is_cached("value", 0), "Should not be cached when TTL is 0"
    
    # Cached with future TTL
    future_ttl = time.time() + 100
    assert solver._is_cached("value", future_ttl), "Should be cached when TTL is in future"
    
    # Not cached with past TTL
    past_ttl = time.time() - 100
    assert not solver._is_cached("value", past_ttl), "Should not be cached when TTL is in past"
    
    # None value should not be cached
    assert not solver._is_cached(None, future_ttl), "None value should not be cached"
    
    print("test_cache_logic: PASSED")


def test_fallback_sitekey():
    """Test fallback sitekey is used when extraction fails."""
    solver = HCaptchaSolver()
    
    # Mock requests.get to fail
    with patch('udio_wrapper.hcaptcha_solver.requests.get') as mock_get:
        mock_get.side_effect = Exception("Network error")
        key = solver.get_sitekey()
        assert key == solver.FALLBACK_SITEKEY, f"Expected fallback sitekey, got {key}"
        assert solver._sitekey_cache == solver.FALLBACK_SITEKEY, "Fallback should be cached"
    
    print("test_fallback_sitekey: PASSED")


def test_clear_cache():
    """Test cache clearing."""
    solver = HCaptchaSolver()
    
    # Set some cached values
    solver._token_cache = "test_token"
    solver._token_ttl = time.time() + 100
    solver._sitekey_cache = "test_sitekey"
    solver._sitekey_ttl = time.time() + 100
    
    solver.clear_cache()
    
    assert solver._token_cache is None, "Token cache should be cleared"
    assert solver._token_ttl == 0, "Token TTL should be reset"
    # Sitekey cache should NOT be cleared by clear_cache()
    assert solver._sitekey_cache == "test_sitekey", "Sitekey cache should not be cleared"
    
    print("test_clear_cache: PASSED")


def test_manual_input_fallback():
    """Test manual input fallback."""
    solver = HCaptchaSolver()
    
    # Mock input to return a token
    with patch('builtins.input', return_value="manual_token_123"):
        token = solver._manual_input()
        assert token == "manual_token_123", f"Expected manual token, got {token}"
    
    # Mock input to return empty (skip)
    with patch('builtins.input', return_value=""):
        token = solver._manual_input()
        assert token is None, f"Expected None for empty input, got {token}"
    
    # Mock input to raise EOFError
    with patch('builtins.input', side_effect=EOFError()):
        token = solver._manual_input()
        assert token is None, f"Expected None for EOFError, got {token}"
    
    # Mock input to raise KeyboardInterrupt
    with patch('builtins.input', side_effect=KeyboardInterrupt()):
        token = solver._manual_input()
        assert token is None, f"Expected None for KeyboardInterrupt, got {token}"
    
    print("test_manual_input_fallback: PASSED")


def test_udio_wrapper_import():
    """Test that UdioWrapper can be imported and instantiated."""
    from udio_wrapper import UdioWrapper
    
    # Should work without captcha keys (will use manual fallback)
    wrapper = UdioWrapper(auth_token="test_token")
    assert wrapper.auth_token == "test_token"
    assert wrapper._captcha_solver is not None
    
    # Should work with captcha_api_key
    wrapper2 = UdioWrapper(auth_token="test_token", captcha_api_key="test_key", captcha_service="capsolver")
    assert os.environ.get("CAPSOLVER_API_KEY") == "test_key"
    
    # Should work with 2captcha service
    wrapper3 = UdioWrapper(auth_token="test_token", captcha_api_key="test_key_2", captcha_service="2captcha")
    assert os.environ.get("CAPTCHA_API_KEY") == "test_key_2"
    
    print("test_udio_wrapper_import: PASSED")


def test_make_request_retry_logic():
    """Test that make_request has retry logic for captcha errors."""
    from udio_wrapper import UdioWrapper
    
    wrapper = UdioWrapper(auth_token="test_token")
    
    # Mock the captcha solver to return a token
    wrapper._captcha_solver.get_token = MagicMock(return_value="test_captcha_token")
    wrapper._captcha_solver.clear_cache = MagicMock()
    
    # Mock requests.post to return 500 then succeed
    mock_response_500 = MagicMock()
    mock_response_500.status_code = 500
    mock_response_500.raise_for_status.side_effect = Exception("500 Server Error")
    
    mock_response_ok = MagicMock()
    mock_response_ok.status_code = 200
    mock_response_ok.raise_for_status.return_value = None
    mock_response_ok.json.return_value = {"success": True}
    
    with patch('udio_wrapper.requests.post', side_effect=[mock_response_500, mock_response_ok]) as mock_post:
        with patch('udio_wrapper.time.sleep', return_value=None):
            response = wrapper.make_request("https://test.com/api", "POST", data={}, max_retries=1)
            # Should retry once and succeed on second attempt
            assert mock_post.call_count == 2, f"Expected 2 calls, got {mock_post.call_count}"
            assert response == mock_response_ok, "Should return successful response"
    
    print("test_make_request_retry_logic: PASSED")


def test_inject_captcha_header():
    """Test that captcha header is injected for POST requests."""
    from udio_wrapper import UdioWrapper
    
    wrapper = UdioWrapper(auth_token="test_token")
    
    # Mock get_token to return a token
    wrapper._captcha_solver.get_token = MagicMock(return_value="injected_token")
    
    headers = {"Content-Type": "application/json"}
    result_headers = wrapper._inject_captcha_header(headers)
    
    assert "h-captcha-response" in result_headers, "Should inject h-captcha-response header"
    assert result_headers["h-captcha-response"] == "injected_token", "Should use token from solver"
    assert result_headers["Content-Type"] == "application/json", "Should preserve original headers"
    
    # Should not inject if already present
    headers_with_captcha = {"h-captcha-response": "existing_token"}
    result_headers = wrapper._inject_captcha_header(headers_with_captcha)
    assert result_headers["h-captcha-response"] == "existing_token", "Should not overwrite existing token"
    
    print("test_inject_captcha_header: PASSED")


if __name__ == "__main__":
    test_sitekey_extraction()
    test_cache_logic()
    test_fallback_sitekey()
    test_clear_cache()
    test_manual_input_fallback()
    test_udio_wrapper_import()
    test_make_request_retry_logic()
    test_inject_captcha_header()
    print("\nAll tests PASSED!")