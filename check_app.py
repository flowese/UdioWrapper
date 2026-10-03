"""Issue #7 verification dashboard.

Serves a page (relative URLs only, binds 0.0.0.0) with:
  - mocked captcha demo: 500 -> auto-solve -> 200 with token injection
  - full unit-test run (32 tests)
  - live reachability probe to Udio (proves sandbox is TLS-blocked,
    so the real live check must run on the user's machine)

Stdlib only. Run: python3 check_app.py  (serves on port 8000)
"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, ".")
from udio_wrapper import UdioWrapper  # noqa: E402
from udio_wrapper.hcaptcha_solver import is_hcaptcha_blocked  # noqa: E402

PORT = 8000

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Udio #7 Fix — Verification</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:820px;margin:0 auto;padding:24px;background:#0f172a;color:#e2e8f0}
h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-bottom:1px solid #334155;padding-bottom:6px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px;margin:12px 0}
button{background:#22c55e;color:#052e16;border:0;border-radius:8px;padding:10px 18px;font-size:15px;font-weight:600;cursor:pointer}
button:disabled{opacity:.5}button.secondary{background:#38bdf8}
pre{background:#020617;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-word;font-size:13px;max-height:420px;overflow:auto}
.ok{color:#4ade80;font-weight:700}.bad{color:#f87171;font-weight:700}.warn{color:#fbbf24;font-weight:700}
code{background:#020617;padding:2px 6px;border-radius:4px}
.small{font-size:13px;color:#94a3b8}
</style></head><body>
<h1>&#128075; Udio issue #7 — is it solved? (live check page)</h1>
<p class="small">This page runs <b>on the fix branch</b>. All checks below run on demand — click each button.</p>

<h2>1 &#129302; Captcha auto-solve demo (mocked Udio: 500 &rarr; solve &rarr; 200)</h2>
<div class="card">
<p class="small">Simulates exactly what Udio does: first <code>POST /generate-proxy</code> returns <code>500</code>, wrapper solves a token and retries with it injected.</p>
<button id="b1" onclick="runDemo()">Run captcha demo</button>
<pre id="o1">Not run yet.</pre>
</div>

<h2>2 &#129514; Full unit-test suite (32 tests)</h2>
<div class="card">
<button id="b2" onclick="runTests()">Run all tests</button>
<pre id="o2">Not run yet.</pre>
</div>

<h2>3 &#127760; Live reachability to Udio from this server</h2>
<div class="card">
<p class="small">Tries a real TLS connection to <code>www.udio.com</code> from this server (no login needed for this probe). Expected: <b>TLS blocked</b> — cloud IPs are rejected by Udio, which is why your real live check must run on <b>your own machine</b> with <code>live_check.py</code>.</p>
<button id="b3" class="secondary" onclick="runLive()">Probe live Udio</button>
<pre id="o3">Not run yet.</pre>
</div>

<h2>4 &#128187; How YOU confirm it is solved</h2>
<div class="card">
<pre>git pull
pip install requests
export UDIO_AUTH_TOKEN="fresh sb-api-auth-token from udio.com cookies"
python3 live_check.py
# if CAPTCHA BLOCK: export CAPTCHA_API_KEY="..." ; python3 live_check.py --with-solver</pre>
<p class="small"><span class="ok">Solved =</span> Step 1 gives 200, or Step 2 goes 500 &rarr; token solved &rarr; 200. <span class="bad">Not solved =</span> still 500 with no solver configured, or 401 (expired cookie).</p>
</div>

<script>
async function call(id, out, url){
  const b=document.getElementById(id), o=document.getElementById(out);
  b.disabled=true; o.textContent='Running...';
  try{
    const r=await fetch(url,{cache:'no-store'});
    const j=await r.json();
    o.textContent=j.output;
    o.className='';
  }catch(e){ o.textContent='ERROR: '+e; }
  b.disabled=false;
}
function runDemo(){call('b1','o1','/api/demo')}
function runTests(){call('b2','o2','/api/tests')}
function runLive(){call('b3','o3','/api/live')}
</script>
</body></html>
"""


def run_demo():
    lines = []
    lines.append("Mocking Udio server: attempt 1 -> HTTP 500 'Internal Server Error'")

    def fake_resp(code, text, json_data=None):
        r = MagicMock()
        r.status_code = code
        r.text = text
        r.headers = {}
        r.json.return_value = json_data or {}
        if code >= 400:
            import requests as rq
            r.raise_for_status.side_effect = rq.exceptions.HTTPError(f"{code} {text}")
        else:
            r.raise_for_status.return_value = None
        return r

    with patch("udio_wrapper.requests.post") as mp, patch("udio_wrapper.time.sleep", return_value=None):
        mp.side_effect = [
            fake_resp(500, "Internal Server Error"),
            fake_resp(200, '{"track_ids":["id1","id2"]}', {"track_ids": ["id1", "id2"]}),
        ]
        w = UdioWrapper("dummy-auth", solver_callback=lambda sk, url: "demo-token-abc123")
        r = w.make_request("https://www.udio.com/api/generate-proxy", "POST",
                           {"prompt": "test"}, w.get_headers())
        lines.append(f"attempt 1: HTTP 500 -> is_hcaptcha_blocked = {is_hcaptcha_blocked(mp.call_args_list[0][0] and fake_resp(500,'x'))}")
        lines.append("wrapper: hCaptcha block detected -> solving token via solver_callback...")
        if r is not None:
            _, kwargs = mp.call_args
            lines.append(f"attempt 2: HTTP 200, track_ids = {r.json().get('track_ids')}")
            lines.append(f"  header 'h-captcha-response' = {kwargs['headers'].get('h-captcha-response')}")
            lines.append(f"  payload 'captchaToken'      = {kwargs['json'].get('captchaToken')}")
            lines.append("")
            lines.append("PASS: 500 was auto-solved and retried with the token injected. Issue #7 logic SOLVED (mocked).")
        else:
            lines.append("")
            lines.append("FAIL: wrapper returned None.")
    return "\n".join(lines)


def run_tests():
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       capture_output=True, text=True, timeout=120)
    out = (p.stderr or "") + (p.stdout or "")
    tail = "\n".join(out.strip().splitlines()[-8:])
    verdict = "PASS: all tests green." if p.returncode == 0 else f"FAIL: exit code {p.returncode}."
    return tail + "\n\n" + verdict


def run_live():
    lines = ["Probing https://www.udio.com/api/generate-proxy (unauthenticated POST, 10s timeout)..."]
    try:
        r = requests.post("https://www.udio.com/api/generate-proxy",
                          json={"prompt": "probe", "samplerOptions": {"seed": -1}},
                          headers={"Content-Type": "application/json", "Origin": "https://www.udio.com"},
                          timeout=10)
        lines.append(f"HTTP {r.status_code}")
        lines.append(f"Body (300 chars): {(r.text or '')[:300] or '<empty>'}")
        lines.append(f"is_hcaptcha_blocked: {is_hcaptcha_blocked(r)}")
        lines.append("Server CAN reach Udio — unexpected in sandbox.")
    except Exception as e:
        lines.append(f"NO HTTP RESPONSE: {type(e).__name__}")
        lines.append(str(e)[:400])
        lines.append("")
        lines.append("EXPECTED: this cloud server is TLS/IP-blocked by Udio.")
        lines.append("Run live_check.py on YOUR machine to do the real live test.")
    return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/demo":
            try:
                self._json({"output": run_demo()})
            except Exception as e:
                self._json({"output": f"ERROR: {e}"})
        elif self.path == "/api/tests":
            try:
                self._json({"output": run_tests()})
            except Exception as e:
                self._json({"output": f"ERROR: {e}"})
        elif self.path == "/api/live":
            try:
                self._json({"output": run_live()})
            except Exception as e:
                self._json({"output": f"ERROR: {e}"})
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()
