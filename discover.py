"""Print structure of the field-activity report page (component names, filters, export calls) - no data."""
import re, json, html
from sales import login, BASE

s = login()
for path in ["/reports/daily-field-activity", "/visits/reports"]:
    r = s.get(BASE + path, timeout=60)
    snaps = re.findall(r'wire:snapshot="([^"]+)"', r.text)
    comps = []
    for sn in snaps:
        j = json.loads(html.unescape(sn))
        data = j.get("data", {})
        comps.append(f"{j['memo']['name']} keys={list(data.keys())[:15]} filter={json.dumps(data.get('filter'))[:300]}")
    clicks = sorted(set(re.findall(r'wire:click(?:\.[a-z]+)?="([^"]+)"', r.text)))[:20]
    tabs = re.findall(r'<a[^>]*(?:tab|nav-link)[^>]*>\s*([^<]{3,60})<', r.text)[:10]
    upd = re.findall(r'data-update-uri="([^"]+)"', r.text)
    print(f"::notice::PAGE {path} comps={comps} clicks={clicks} tabs={tabs} upd={upd}"[:4000])
