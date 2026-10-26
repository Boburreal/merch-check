"""Find how project-select switches project, and the MP visits export page (no data printed)."""
import re, json, html
from sales import login, BASE

s = login()
r = s.get(BASE + "/visits/reports", timeout=60)
for sn in re.findall(r'wire:snapshot="([^"]+)"', r.text):
    j = json.loads(html.unescape(sn))
    if j.get("memo", {}).get("name") == "project-select":
        print(f"::notice::project-select data={json.dumps(j['data'])[:300]}")
# options / clicks inside the project select block
i = r.text.find('project-select')
blk = r.text[max(0, i - 200): i + 4000]
opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>\s*([^<]+)<', blk)
clicks = re.findall(r'wire:(?:click|change|model[\w.]*)="([^"]+)"', blk)
print(f"::notice::options={opts[:15]} wire={clicks[:10]}"[:3000])
r2 = s.get(BASE + "/lists/visits", timeout=60)
names = []
for sn in re.findall(r'wire:snapshot="([^"]+)"', r2.text):
    try:
        j = json.loads(html.unescape(sn)); d = j.get("data", {})
        names.append(f"{j['memo']['name']} keys={list(d.keys())[:12] if isinstance(d, dict) else d}")
    except Exception as e:
        names.append("ERR")
ex = sorted(set(re.findall(r'wire:click(?:\.[a-z]+)?="([^"]+)"', r2.text)))[:15]
print(f"::notice::/lists/visits comps={names} clicks={ex}"[:3500])
