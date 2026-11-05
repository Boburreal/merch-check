"""Read-only probe 3: /ajax/search lists (categories, pharm users per category, regions) in both projects."""
import re, json, os, base64, hashlib
from cryptography.fernet import Fernet
from sales import login, switch_project, restore, BASE

s = login()
out = {}
def search(model, field="name", flt=None, q=""):
    res, page = [], 1
    while page < 40:
        p = {"q": q, "page": page, "model": model, "field": field, "location": "/lists/companies/add_company"}
        if flt is not None:
            p["filter"] = json.dumps(flt)
        j = s.get(BASE + "/ajax/search", params=p, timeout=60, headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json()
        d = j.get("data", [])
        res += d
        if not d or not (j.get("next_page_url") or (j.get("current_page", 0) < j.get("last_page", 0))):
            break
        page += 1
    return res
for p in (1, 4):
    switch_project(s, p)
    cats = search("App\\Models\\Category")
    out[f"p{p}_cats"] = cats
    out[f"p{p}_users"] = {str(c["id"]): search("App\\Models\\User", flt=[["pharm"], ["category_id", "=", str(c["id"])]]) for c in cats}
    out[f"p{p}_regions"] = search("App\\Models\\Region")
restore(s)
k = os.environ["ROSTER_KEY"].encode()
open("drop/baza_probe3.fer", "wb").write(Fernet(base64.urlsafe_b64encode(hashlib.sha256(k).digest())).encrypt(json.dumps(out, ensure_ascii=False).encode()))
print("::notice::probe3 " + " ".join(f"{k}={len(v)}" for k, v in out.items()))
