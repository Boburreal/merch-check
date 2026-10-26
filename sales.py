"""Login to sales.asklepiygroup.uz with secrets and fetch pages/exports."""
import os, re, requests

BASE = "https://sales.asklepiygroup.uz"


def login() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 merch-check"
    r = s.get(f"{BASE}/login", timeout=60)
    token = re.search(r'name="_token" value="([^"]+)"', r.text).group(1)
    r = s.post(f"{BASE}/login", timeout=60, data={
        "_token": token, "email": os.environ["SALES_LOGIN"],
        "password": os.environ["SALES_PASSWORD"], "remember": "on"})
    if "/login" in r.url or 'name="password"' in r.text:
        raise SystemExit("Sales login failed (login/parolni tekshiring)")
    return s
