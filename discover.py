"""One-off read-only probe: add_company page structure and INN lookup in the full pharmacy lists."""
import re
from bs4 import BeautifulSoup
from sales import login, switch_project, restore, BASE
from companies import fetch_companies, _clean

INNS = ['309877286', '306591353', '302646222']
s = login()
r = s.get(BASE + "/lists/companies/add_company", timeout=60)
soup = BeautifulSoup(r.text, "lxml")
for i, f in enumerate(soup.find_all("form")):
    els = [f"{e.name}:{e.get('name') or ''}:{e.get('type') or ''}:{' '.join(k+'='+str(v) for k, v in e.attrs.items() if k.startswith(('wire:', 'x-', '@')))}" for e in f.find_all(["input", "select", "button", "textarea"])]
    print(f"::notice::form{i} action={f.get('action')} attrs={ {k: v for k, v in f.attrs.items() if k.startswith(('wire', 'x-', '@'))} } text={f.get_text(' ', strip=True)[:300]} els={els}")
comp = re.findall(r'wire:snapshot="([^"]{0,600})', r.text)
print("::notice::components: " + " || ".join(c.replace('&quot;', '"')[:500] for c in comp))
restore(s)
for p in (1, 4):
    c = fetch_companies(p)
    c.columns = ['_sel', 'ID', 'Название', 'Инн', 'Регион', 'Район', 'Локация', 'Фарм. пред', 'Сеть'][:len(c.columns)] + list(c.columns[9:])
    for inn in INNS:
        m = c[c['Инн'].astype(str).str.contains(inn) | c['Название'].astype(str).str.contains(inn)]
        print(f"::notice::P{p} n={len(c)} INN {inn}: " + " ;; ".join(f"{r['ID']} | {r['Название']} | {r['Инн']} | {r['Регион']} | {r['Район']} | {r['Фарм. пред']} | {r['Сеть']}" for r in m.to_dict('records'))[:900])
