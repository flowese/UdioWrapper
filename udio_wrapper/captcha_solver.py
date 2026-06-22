# Fix for Issue #7: 500 Server Error - Auto Solve hcapcha

"""
Captcha solver module for handling hCaptcha challenges on Udio.
Supports multiple captcha solving services.
"""

import time
import requests
from typing import Optional, Dict, Any


class CaptchaSolverError(Exception):
    """Exception raised when captcha solving fails."""
    pass


class CaptchaSolver:
    """
    Handles automatic hCaptcha solving using third-party services.
    Supports 2captcha, anticaptcha, and capsolver.
    """
    
    SUPPORTED_SERVICES = ['2captcha', 'anticaptcha', 'capsolver']
    
    # Udio's hCaptcha site key (extracted from their frontend)
    UDIO_SITEKEY = "4c672d35-0701-42b2-88c3-78380b0db560"
    UDIO_URL = "https://www.udio.com"
    
    def __init__(self, api_key: str, service: str = '2captcha', timeout: int = 120):
        """
        Initialize the captcha solver.
        
        Args:
            api_key: API key for the captcha solving service
            service: Name of the service ('2captcha', 'anticaptcha', 'capsolver')
            timeout: Maximum time to wait for solution in seconds
        """
        if service not in self.SUPPORTED_SERVICES:
            raise ValueError(f"Unsupported service: {service}. Use one of: {self.SUPPORTED_SERVICES}")
        
        self.api_key = api_key
        self.service = service
        self.timeout = timeout
        self.session = requests.Session()
    
    def solve_hcaptcha(self, sitekey: Optional[str] = None, url: Optional[str] = None) -> str:
        """
        Solve an hCaptcha challenge.
        
        Args:
            sitekey: The hCaptcha site key (defaults to Udio's key)
            url: The page URL where captcha appears (defaults to Udio URL)
            
        Returns:
            The captcha solution token
            
        Raises:
            CaptchaSolverError: If solving fails
        """
        sitekey = sitekey or self.UDIO_SITEKEY
        url = url or self.UDIO_URL
        
        if self.service == '2captcha':
            return self._solve_2captcha(sitekey, url)
        elif self.service == 'anticaptcha':
            return self._solve_anticaptcha(sitekey, url)
        elif self.service == 'capsolver':
            return self._solve_capsolver(sitekey, url)
    
    def _solve_2captcha(self, sitekey: str, url: str) -> str:
        """Solve hCaptcha using 2captcha service."""
        # Submit captcha task
        submit_url = "https://2captcha.com/in.php"
        submit_params = {
            'key': self.api_key,
            'method': 'hcaptcha',
            'sitekey': sitekey,
            'pageurl': url,
            'json': 1
        }
        
        try:
            response = self.session.post(submit_url, data=submit_params, timeout=30)
            result = response.json()
            
            if result.get('status') != 1:
                raise CaptchaSolverError(f"2captcha submit error: {result.get('request', 'Unknown error')}")
            
            task_id = result['request']
            
            # Poll for result
            result_url = "https://2captcha.com/res.php"
            result_params = {
                'key': self.api_key,
                'action': 'get',
                'id': task_id,
                'json': 1
            }
            
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                time.sleep(5)  # Wait before polling
                
                response = self.session.get(result_url, params=result_params, timeout=30)
                result = response.json()
                
                if result.get('status') == 1:
                    return result['request']
                elif result.get('request') == 'CAPCHA_NOT_READY':
                    continue
                else:
                    raise CaptchaSolverError(f"2captcha result error: {result.get('request', 'Unknown error')}")
            
            raise CaptchaSolverError("2captcha timeout waiting for solution")
            
        except requests.RequestException as e:
            raise CaptchaSolverError(f"2captcha request failed: {str(e)}")
    
    def _solve_anticaptcha(self, sitekey: str, url: str) -> str:
        """Solve hCaptcha using Anti-Captcha service."""
        # Create task
        create_url = "https://api.anti-captcha.com/createTask"
        task_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "HCaptchaTaskProxyless",
                "websiteURL": url,
                "websiteKey": sitekey
            }
        }
        
        try:
            response = self.session.post(create_url, json=task_payload, timeout=30)
            result = response.json()
            
            if result.get('errorId', 0) != 0:
                raise CaptchaSolverError(f"Anti-Captcha error: {result.get('errorDescription', 'Unknown error')}")
            
            task_id = result['taskId']
            
            # Poll for result
            result_url = "https://api.anti-captcha.com/getTaskResult"
            result_payload = {
                "clientKey": self.api_key,
                "taskId": task_id
            }
            
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                time.sleep(5)
                
                response = self.session.post(result_url, json=result_payload, timeout=30)
                result = response.json()
                
                if result.get('errorId', 0) != 0:
                    raise CaptchaSolverError(f"Anti-Captcha error: {result.get('errorDescription', 'Unknown error')}")
                
                if result.get('status') == 'ready':
                    return result['solution']['gRecaptchaResponse']
                
            raise CaptchaSolverError("Anti-Captcha timeout waiting for solution")
            
        except requests.RequestException as e:
            raise CaptchaSolverError(f"Anti-Captcha request failed: {str(e)}")
    
    def _solve_capsolver(self, sitekey: str, url: str) -> str:
        """Solve hCaptcha using CapSolver service."""
        create_url = "https://api.capsolver.com/createTask"
        task_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": url,
                "websiteKey": sitekey
            }
        }
        
        try:
            response = self.session.post(create_url, json=task_payload, timeout=30)
            result = response.json()
            
            if result.get('errorId', 0) != 0:
                raise CaptchaSolverError(f"CapSolver error: {result.get('errorDescription', 'Unknown error')}")
            
            task_id = result['taskId']
            
            # Poll for result
            result_url = "https://api.capsolver.com/getTaskResult"
            result_payload = {
                "clientKey": self.api_key,
                "taskId": task_id
            }
            
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                time.sleep(3)
                
                response = self.session.post(result_url, json=result_payload, timeout=30)
                result = response.json()
                
                if result.get('errorId', 0) != 0:
                    raise CaptchaSolverError(f"CapSolver error: {result.get('errorDescription', 'Unknown error')}")
                
                if result.get('status') == 'ready':
                    return result['solution']['gRecaptchaResponse']
                
            raise CaptchaSolverError("CapSolver timeout waiting for solution")
            
        except requests.RequestException as e:
            raise CaptchaSolverError(f"CapSolver request failed: {str(e)}")