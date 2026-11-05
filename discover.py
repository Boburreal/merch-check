"""Read-only probe of the add_company wizard: only the 'next' (INN check) step is called, nothing is saved."""
import re, html, json
from bs4 import BeautifulSoup
from sales import login, BASE

s = login()
for inn in ('309877286', '309877286-1'):
    r = s.get(BASE + "/lists/companies/add_company", timeout=60)
    csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
    upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
    snap = next(html.unescape(x) for x in re.findall(r'wire:snapshot="([^"]+)"', r.text)
                if '"step":"inn"' in html.unescape(x))
    name = json.loads(snap)['memo']['name']
    body = {"_token": csrf, "components": [{"snapshot": snap, "updates": {"inn": inn}, "calls": [{"path": "", "method": "next", "params": []}]}]}
    x = s.post(upd, json=body, timeout=120, headers={"X-Livewire": "true", "Content-Type": "application/json",
                                                     "X-CSRF-TOKEN": csrf, "Referer": BASE + "/lists/companies/add_company"})
    j = x.json()['components'][0]
    data = json.loads(j['snapshot'])['data']
    soup = BeautifulSoup(j['effects'].get('html', ''), 'lxml')
    els = []
    for e in soup.find_all(['input', 'select', 'textarea', 'button']):
        wm = next((v for k, v in e.attrs.items() if k.startswith('wire:model')), '')
        wc = next((f"{k}={v}" for k, v in e.attrs.items() if k.startswith('wire:click')), '')
        lab = e.find_previous('label')
        o = ''
        if e.name == 'select':
            op = e.find_all('option'); o = f"[{len(op)}: " + "; ".join(z.get_text(strip=True) for z in op[:5]) + "]"
        els.append(f"{e.name}:{wm or e.get('name', '')}{(' '+wc) if wc else ''} '{lab.get_text(' ', strip=True)[:30] if lab else ''}'{o}")
    print(f"::notice::{name} INN {inn} [{x.status_code}] step={data.get('step')} keys={list(data)} text={soup.get_text(' ', strip=True)[:500]}")
    print(f"::notice::INN {inn} fields={json.dumps(data.get('fields'), ensure_ascii=False)[:900]} els={' | '.join(els)[:1500]}")
