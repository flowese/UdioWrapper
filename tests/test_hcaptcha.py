from unittest.mock import Mock, patch
from udio_wrapper.hcaptcha_solver import HCaptchaSolver, is_hcaptcha_blocked

def test_hcaptcha_solver_import():
    """Test that HCaptchaSolver can be imported."""
    solver = HCaptchaSolver()
    assert solver is not None
        
def test_is_hcaptcha_blocked_detection():
    """Test that is_hcaptcha_blocked correctly identifies captcha responses."""
    
    # Mock a 500 response with hCaptcha indicators
    fake_response_500 = Mock()
    fake_response_500.status_code = 500
    fake_response_500.text = "hcaptcha challenge failed"  # Simulate hCaptcha response
    
    # Mock a normal 500 response without hCaptcha indicators
    normal_500 = Mock()
    normal_500.status_code = 500
    normal_500.text = "Internal Server Error"
    
    # Normal response
    success_response = Mock()
    success_response.status_code = 200
    
    # Test that our fake 500 response is considered captcha blocked
    result = is_hcaptcha_blocked(fake_response_500)
    assert result is True, "hCaptcha 500 response should be considered as captcha-blocked"
    
    # Test normal 500 response - should not be captcha blocked
    result = is_hcaptcha_blocked(normal_500)
    assert result is False, "Normal 500 response should not be considered as captcha-blocked"
    
    # Test successful response - should not be captcha blocked
    result = is_hcaptcha_blocked(success_response)
    assert result is False, "Successful response should not be considered as captcha-blocked"

def test_solver_initialization():
    """Test that HCaptchaSolver can be initialized."""
    # Test with 2captcha service
    solver_2captcha = HCaptchaSolver(service="2captcha")
    assert solver_2captcha is not None
    
    # Test with capsolver service
    solver_capsolver = HCaptchaSolver(service="capsolver")
    assert solver_capsolver is not None
    
    # Test with no service
    solver_none = HCaptchaSolver()
    assert solver_none is not None

def test_get_token_flow():
    """Test the token caching mechanism."""
    solver = HCaptchaSolver(api_key="test_key", service="capsolver")
    
    # Check that we start with no token
    assert solver.get_token() is None
    
    # Simulate getting a token (this will call the real method but we mocked the internal fetch)
    with patch.object(solver, '_fetch_captcha_token', return_value="mock_token") as mock_fetch:
        token = solver.get_token()
        assert token == "mock_token"
        # Second call should return cached token (but only if within TTL)
        token2 = solver.get_token()
        assert token2 == "mock_token"
        # Should have called fetch only once
        assert mock_fetch.call_count == 1
