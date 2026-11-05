"""Read-only probe: add_company step-2 HTML (nothing saved) + users list -> encrypted drop for Claude."""
import re, html, json, os, base64, hashlib
from cryptography.fernet import Fernet
from sales import login, BASE, current_project

s = login()
out = {"project": current_project(s)}
r = s.get(BASE + "/lists/companies/add_company", timeout=60)
csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
snap = next(html.unescape(x) for x in re.findall(r'wire:snapshot="([^"]+)"', r.text) if '"step":"inn"' in html.unescape(x))
H = {"X-Livewire": "true", "Content-Type": "application/json", "X-CSRF-TOKEN": csrf, "Referer": BASE + "/lists/companies/add_company"}
x = s.post(upd, json={"_token": csrf, "components": [{"snapshot": snap, "updates": {"inn": "309877286-1"}, "calls": [{"path": "", "method": "next", "params": []}]}]}, headers=H, timeout=120).json()
c = x["components"][0]
out["step2_html"] = c["effects"].get("html", "")
out["step2_snapshot"] = c["snapshot"]
out["page_html"] = r.text
# users list
u = s.get(BASE + "/lists/users", timeout=60)
out["users_page"] = u.text[-20000:]
tok = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", u.text)
heads = [re.sub(r'<[^>]+>|\s+', ' ', h).strip() for h in re.findall(r'<th[^>]*>(.*?)</th>', u.text, re.S)]
out["users_heads"] = heads
if tok:
    data = {"draw": 1, "start": 0, "length": 3000, "search[value]": "", "search[regex]": "false"}
    for i in range(len(heads)):
        data[f"columns[{i}][data]"] = i
    out["users"] = s.post(BASE + "/lists/users", data=data, timeout=300, headers={"X-CSRF-TOKEN": tok.group(1),
                          "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json()
k = os.environ["ROSTER_KEY"].encode()
f = Fernet(base64.urlsafe_b64encode(hashlib.sha256(k).digest()))
os.makedirs("drop", exist_ok=True)
open("drop/baza_probe.fer", "wb").write(f.encrypt(json.dumps(out, ensure_ascii=False).encode()))
print(f"::notice::probe ok users={len(out.get('users', {}).get('data', []))} heads={heads}")
