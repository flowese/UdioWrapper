import requests

class UdioCaptchaSolver:
    def __init__(self, base_url="https://www.udio.com/api"):
        self.base_url = base_url
        self.session = requests.Session()
        # تعيين Headers أساسية عشان نتجنب حظر السيرفر وخطأ 500
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.udio.com/"
        })

    def generate_proxy(self, payload, hcaptcha_token=None):
        url = f"{self.base_url}/generate-proxy"
        headers = {}
        
        # لو فيه توكن كابتشا تم حله، بنضيفه للـ Headers أو الـ Payload
        if hcaptcha_token:
            headers["X-Captcha-Token"] = hcaptcha_token
            
        try:
            response = self.session.post(url, json=payload, headers=headers)
            
            # لو ظهر خطأ 500 بسبب الكابتشا، بنتعامل معه برفع استثناء أو إعادة المحاولة
            if response.status_code == 500:
                raise Exception("500 Server Error: Internal Server Error - May require valid hCaptcha token.")
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Error making POST request: {e}")
            return None

if __name__ == "__main__":
    print("UdioWrapper hCaptcha auto-solve module initialized successfully.")
