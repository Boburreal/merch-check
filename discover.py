"""One-off: the 'add pharmacy' form and an INN search in both projects (read only, nothing is saved)."""
import re
from bs4 import BeautifulSoup
from sales import login, switch_project, restore, BASE
from companies import COLS

INNS = ['309877286', '306591353', '302646222']
s = login()
out = []
for p in (1, 4):
    switch_project(s, p)
    lst = s.get(BASE + "/lists/companies", timeout=60).text
    adds = sorted(set(re.findall(r'href="([^"]*companies[^"]*(?:create|add|new)[^"]*)"', lst)))
    out.append(f"P{p} add links: {adds}")
    url = adds[0] if adds else BASE + "/lists/companies/create"
    url = url if url.startswith("http") else BASE + url
    r = s.get(url, timeout=60)
    soup = BeautifulSoup(r.text, "lxml")
    f = soup.find("main") or soup.find("div", class_=re.compile("content")) or soup.body
    fl = []
    for el in f.find_all(["input", "select", "textarea"]):
        n = el.get("name") or el.get("wire:model") or el.get("id")
        if not n or n in ("_token",):
            continue
        lab = ''
        if el.get("id"):
            l = soup.find("label", attrs={"for": el["id"]})
            lab = l.get_text(" ", strip=True) if l else ''
        extra = ''
        if el.name == 'select':
            opts = el.find_all("option")
            extra = f"[{len(opts)}: " + "; ".join(o.get_text(strip=True) for o in opts[:6]) + "]"
        req = '*' if el.has_attr('required') else ''
        fl.append(f"{n}{req}({el.name}/{el.get('type','')}){'='+lab if lab else ''}{extra}")
    out.append(f"P{p} create [{r.status_code}] url={r.url} forms={len(soup.find_all('form'))} wire={sorted(set(re.findall(r'wire:model[.a-z]*="([^"]+)"', r.text)))[:40]} fields: " + " | ".join(fl))
    tok = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", s.get(BASE + "/lists/companies", timeout=60).text).group(1)
    for inn in INNS:
        data = {"draw": 1, "start": 0, "length": 50, "search[value]": inn, "search[regex]": "false"}
        for i in range(len(COLS)):
            data[f"columns[{i}][data]"] = i; data[f"columns[{i}][searchable]"] = "true"
        j = s.post(BASE + "/lists/companies", data=data, timeout=120, headers={"X-CSRF-TOKEN": tok,
                   "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json()
        rows = j.get('data', [])
        txt = lambda v: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(v or ''))).strip()
        out.append(f"P{p} INN {inn}: {len(rows)} -> " + " ;; ".join(
            " / ".join(txt(v) for k, v in (r.items() if isinstance(r, dict) else enumerate(r)) if k not in ('action', 0, '_sel', 'location')) for r in rows)[:600])
restore(s)
for o in out: print("::notice::" + o[:1500])
