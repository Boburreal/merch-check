"""Print the structure of the Sales report pages (links, forms, export buttons) - no data."""
import re
from urllib.parse import urljoin
from sales import login, BASE

s = login()
home = s.get(BASE + "/", timeout=60)
print(f"::notice::login ok, landed on {home.url}")
links = sorted(set(re.findall(r'href="([^"#]+)"', home.text)))
links = [l for l in links if "sales.asklepiygroup.uz" in l or l.startswith("/")]
print("::notice::LINKS " + " | ".join(l.replace(BASE, "") for l in links)[:3500])
cand = [l for l in links if re.search(r"report|otchet|visit|statist", l, re.I)]
for l in cand[:6]:
    r = s.get(urljoin(BASE, l), timeout=60)
    forms = re.findall(r"<form[^>]*>", r.text)
    ex = re.findall(r'(?:href|wire:click|onclick|action)="([^"]*(?:xport|xcel|csv|download)[^"]*)"', r.text, re.I)
    names = sorted(set(re.findall(r'(?:name|wire:model(?:\.live)?(?:\.defer)?)="([^"]+)"', r.text)))
    print(f"::notice::PAGE {l.replace(BASE,'')} forms={forms[:3]} export={ex[:6]} fields={names[:25]}"[:3800])
