import requests
import os
import time

class UdioWrapper:
    API_BASE_URL = "https://udio.com"

    def __init__(self, auth_token, capsolver_api_key=None):
        self.auth_token = auth_token
        self.capsolver_api_key = capsolver_api_key or os.getenv("CAPSOLVER_API_KEY")
        self.all_track_ids = []

    def solve_hcaptcha(self, site_url, site_key):
        if not self.capsolver_api_key:
            print("Capsolver API key is missing.")
            return None
        
        payload = {
            "clientKey": self.capsolver_api_key,
            "task": {
                "type": "HCaptchaTaskProxyLess",
                "websiteURL": site_url,
                "websiteKey": site_key
            }
        }
        try:
            res = requests.post("https://capsolver.com", json=payload)
            task_id = res.json().get("taskId")
            if not task_id: return None
            
            while True:
                time.sleep(3)
                status_res = requests.post("https://capsolver.com", json={
                    "clientKey": self.capsolver_api_key,
                    "taskId": task_id
                })
                status_data = status_res.json()
                if status_data.get("status") == "ready":
                    return status_data.get("solution", {}).get("gRecaptchaResponse")
                elif status_data.get("status") == "failed":
                    return None
        except Exception:
            return None

    def make_request(self, url, method, data=None, headers=None):
        try:
            if method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.get(url, headers=headers)
            
            if response.status_code == 500 or "captcha" in response.text.lower():
                udio_hcaptcha_sitekey = "6lg0f68b-5712-4f51-b0e6-993d078e0103" 
                captcha_token = self.solve_hcaptcha("https://udio.com", udio_hcaptcha_sitekey)
                
                if captcha_token:
                    if headers is None: headers = {}
                    headers["x-hcaptcha-response"] = captcha_token
                    if data and isinstance(data, dict):
                        data["captchaToken"] = captcha_token

                    if method == 'POST':
                        response = requests.post(url, headers=headers, json=data)
                    else:
                        response = requests.get(url, headers=headers)

            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return None
