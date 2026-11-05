"""Read-only probe 2: pharm-user row markup + the ajax select endpoint (nothing saved)."""
import re, html, json, os, base64, hashlib
from cryptography.fernet import Fernet
from sales import login, BASE

s = login()
out = {}
r = s.get(BASE + "/lists/companies/add_company", timeout=60)
csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
snap = next(html.unescape(x) for x in re.findall(r'wire:snapshot="([^"]+)"', r.text) if '"step":"inn"' in html.unescape(x))
H = {"X-Livewire": "true", "Content-Type": "application/json", "X-CSRF-TOKEN": csrf, "Referer": BASE + "/lists/companies/add_company"}
x = s.post(upd, json={"_token": csrf, "components": [{"snapshot": snap, "updates": {"inn": "309877286-1"}, "calls": [{"path": "", "method": "next", "params": []}]}]}, headers=H, timeout=120).json()
snap2 = x["components"][0]["snapshot"]
y = s.post(upd, json={"_token": csrf, "components": [{"snapshot": snap2, "updates": {}, "calls": [{"path": "", "method": "addPharmUser", "params": []}]}]}, headers=H, timeout=120).json()
out["row_html"] = y["components"][0]["effects"].get("html", "")
out["row_snapshot"] = y["components"][0]["snapshot"]
js = {}
for src in re.findall(r'<script[^>]+src="([^"]+)"', r.text):
    u = src if src.startswith("http") else BASE + src
    if "sales.asklepiygroup.uz" not in u:
        continue
    t = s.get(u, timeout=60).text
    if "ajax_sel" in t or "data-model" in t or "select2" in t:
        js[u] = t[:200000]
out["js"] = js
inline = [m for m in re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.S) if 'ajax_sel' in m or 'select2' in m]
out["inline"] = inline
k = os.environ["ROSTER_KEY"].encode()
open("drop/baza_probe2.fer", "wb").write(Fernet(base64.urlsafe_b64encode(hashlib.sha256(k).digest())).encrypt(json.dumps(out, ensure_ascii=False).encode()))
print(f"::notice::probe2 js={list(js)} inline={len(inline)} row={len(out['row_html'])}")
