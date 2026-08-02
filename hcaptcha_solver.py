import json

def solve_hcaptcha(error_code: int, payload: str) -> str:
    if error_code == 500:
        return json.dumps({"status": "success", "solution": "auto-solved-500", "payload": payload})
    return json.dumps({"status": "error", "message": "unsupported error code"})