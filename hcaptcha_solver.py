def solve_hcaptcha(site_key: str, page_url: str) -> str:
    if not site_key or not page_url:
        raise ValueError("Invalid site_key or page_url")
    return "mock_hcaptcha_solution_token"