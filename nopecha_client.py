#!/usr/bin/env python3
"""
NoPechA hCaptcha Solver Client
================================

通用 hCaptcha/recaptcha 解决器 SDK
用于绕过 UdioWrapper 的 hCaptcha 反爬检测

Installation:
    pip install requests
    
Usage:
    from nopecha_client import NoPechAClient
    
    client = NoPechAClient(api_key="your_api_key")
    token = client.solve_hcaptcha(sitekey="sitekey_value", pageurl="https://www.udio.com/")
    print(f"Solved! Token: {token}")

API Keys:
    Get your API key from: https://nopecha.com/pricing

Cost Analysis:
    $1 USD = ~90,000 captcha solutions
    Average cost per solution: ~$0.000011
    Expected monthly usage (10 songs/day): ~$0.007/month
"""

import os
import time
import json
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    import requests
    from requests.exceptions import RequestException, Timeout
except ImportError:
    raise ImportError("Please install requests: pip install requests")


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class CaptchaResult:
    """hCaptcha/Recaptcha 解决结果"""
    success: bool
    token: Optional[str] = None
    error_message: Optional[str] = None
    response_time: float = 0.0
    sitekey: Optional[str] = None
    
    def __str__(self):
        if self.success:
            return f"✅ Solved in {self.response_time:.2f}s | Token: {self.token[:20]}..."
        else:
            return f"❌ Failed: {self.error_message}"


class NoPechAClient:
    """
    NoPechA API Client
    ===================
    
    提供 hCaptcha 和 Recaptcha 自动解决功能
    支持重试逻辑、配额管理、超时控制
    """
    
    BASE_URL = "https://api.nopecha.com"
    CAPTCHA_API = f"{BASE_URL}/solve"
    QUOTA_API = f"{BASE_URL}/quota"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        enable_logging: bool = True
    ):
        self.api_key = api_key or os.getenv("NOPECHA_API_KEY")
        if not self.api_key:
            raise ValueError(
                "NoPechA API key is required! "
                "Pass it to constructor OR set environment variable: "
                "export NOPECHA_API_KEY='ghp_your_key'"
            )
        
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (X-Custom-NopechaClient/1.0)'
        })
        
        if not enable_logging:
            logging.getLogger().setLevel(logging.WARNING)
        
        logger.info(f"NoPechA client initialized successfully. Max retries: {max_retries}")
    
    def solve_hcaptcha(
        self,
        sitekey: str,
        pageurl: str,
        callback_url: Optional[str] = None,
        invisible: bool = False
    ) -> CaptchaResult:
        """Solve hCaptcha challenge using NoPechA AI solver"""
        if not self.api_key:
            return CaptchaResult(success=False, error_message="No API key available")
        
        start_time = time.time()
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"Attempting to solve hCaptcha (attempt {attempt}/{self.max_retries})")
                
                payload = {
                    'token': self.api_key,
                    'type': 'hcaptcha',
                    'sitekey': sitekey,
                    'pageurl': pageurl
                }
                
                if callback_url:
                    payload['callback'] = callback_url
                
                if invisible:
                    payload['invisible'] = 'true'
                
                response = self.session.post(self.CAPTCHA_API, json=payload, timeout=self.timeout)
                
                if response.status_code == 200:
                    result_data = response.json()
                    
                    if result_data.get('status') == 'success' and result_data.get('token'):
                        response_time = time.time() - start_time
                        
                        logger.info(f"hCaptcha solved successfully! Time: {response_time:.2f}s")
                        
                        return CaptchaResult(
                            success=True,
                            token=result_data['token'],
                            response_time=response_time,
                            sitekey=sitekey
                        )
                    else:
                        error_msg = result_data.get('error', 'Unknown error')
                        logger.warning(f"NoPechA returned error: {error_msg}")
                
                elif response.status_code == 429:
                    wait_time = self.retry_delay * attempt * 2
                    logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                    
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error(error_msg)
            
            except Timeout:
                last_error = "Request timeout"
                logger.warning(f"Timeout on attempt {attempt}. Retrying...")
            except RequestException as e:
                last_error = f"Network error: {str(e)[:200]}"
                logger.warning(f"Network error on attempt {attempt}. Retrying...")
            
            if attempt < self.max_retries:
                time.sleep(self.retry_delay * attempt)
        
        final_error = last_error or "Maximum retries exceeded"
        total_time = time.time() - start_time
        
        logger.error(f"All retries failed after {total_time:.2f}s. Last error: {final_error}")
        
        return CaptchaResult(
            success=False,
            error_message=f"hCaptcha solve failed: {final_error}",
            response_time=total_time,
            sitekey=sitekey
        )
    
    def get_quota(self) -> Dict[str, Any]:
        """Check remaining quota and account status"""
        try:
            response = self.session.get(self.QUOTA_API, params={'token': self.api_key}, timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Quota check failed: {response.status_code}")
                return {'error': f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Quota check exception: {e}")
            return {'error': str(e)}
    
    def test_connection(self) -> bool:
        """Quick connection test"""
        try:
            quota = self.get_quota()
            if 'error' not in quota:
                logger.info("✓ NoPechA connection successful!")
                return True
            else:
                logger.error(f"✗ Connection test failed: {quota.get('error')}")
                return False
        except Exception as e:
            logger.error(f"✗ Connection test exception: {e}")
            return False
    
    def close(self):
        """Clean up session resources"""
        self.session.close()
        logger.info("NoPechA client session closed")


def create_client(api_key: Optional[str] = None, **kwargs) -> NoPechAClient:
    """Factory function to create NoPechA client easily"""
    return NoPechAClient(api_key=api_key, **kwargs)


if __name__ == "__main__":
    print("=" * 60)
    print("NoPechA Client Demo")
    print("=" * 60)
    
    api_key = os.getenv("NOPECHA_API_KEY")
    
    if not api_key:
        print("\n⚠️ Please set NOPECHA_API_KEY environment variable:")
        print("   export NOPECHA_API_KEY='ghp_your_actual_key_here'\n")
    else:
        print(f"\n✓ API key found ({len(api_key)} chars)")
        
        client = create_client()
        
        if client.test_connection():
            print("\n✅ Ready to solve captchas!")
        else:
            print("\n❌ Connection failed. Check API key validity.")
        
        client.close()
