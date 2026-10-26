"""Structure of company list page (no data values printed)."""
import re, json, html
from sales import login, switch_project, BASE

s = login()
switch_project(s, 1)
for path in ["/lists/companies", "/map"]:
    r = s.get(BASE + path, timeout=60)
    comps = []
    for sn in re.findall(r'wire:snapshot="([^"]+)"', r.text):
        try:
            j = json.loads(html.unescape(sn)); d = j.get("data", {})
            keys = list(d.keys())[:20] if isinstance(d, dict) else []
            comps.append(f"{j['memo']['name']} keys={keys}")
        except Exception:
            comps.append("ERR")
    clicks = sorted(set(re.findall(r'wire:click(?:\.[a-z]+)?="([^"]+)"', r.text)))[:20]
    ths = re.findall(r'<th[^>]*>\s*([^<]{2,40})<', r.text)[:25]
    hrefs = sorted(set(re.findall(r'href="([^"]*(?:export|excel|csv|download|history|log)[^"]*)"', r.text, re.I)))[:10]
    apis = sorted(set(re.findall(r'["\'](/api/[^"\']+)["\']', r.text)))[:10]
    print(f"::notice::{path} comps={comps} clicks={clicks} th={ths} hrefs={hrefs} apis={apis}"[:3800])
