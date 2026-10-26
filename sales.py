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


def switch_project(s: requests.Session, project_id: int):
    """Same as choosing a project in the left-bottom dropdown."""
    import html, json
    r = s.get(f"{BASE}/visits/reports", timeout=120)
    csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
    upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
    for sn in re.findall(r'wire:snapshot="([^"]+)"', r.text):
        raw = html.unescape(sn)
        if json.loads(raw).get("memo", {}).get("name") == "project-select":
            body = {"_token": csrf, "components": [{"snapshot": raw, "updates": {"currentProjectId": str(project_id)}, "calls": []}]}
            x = s.post(upd, json=body, timeout=120, headers={"X-Livewire": "true", "Content-Type": "application/json",
                                                             "X-CSRF-TOKEN": csrf, "Referer": f"{BASE}/visits/reports"})
            x.raise_for_status()
            return
    raise SystemExit("project-select not found")
