"""One-off: doctors / work places lists and the recent pharmacy-location log (compact notices)."""
import re, datetime as dt
import pandas as pd
import store
from sales import login, switch_project, restore, BASE

s = login()
out = []
for p in (1, 4):
    switch_project(s, p)
    for path in ('/lists/doctors', '/lists/work_places'):
        r = s.get(BASE + path, timeout=60)
        heads = [re.sub(r'<[^>]+>|\s+', ' ', h).strip() for h in re.findall(r'<th[^>]*>(.*?)</th>', r.text, re.S)][2:]
        csrf = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", r.text) or re.search(r'data-csrf="([^"]+)"', r.text)
        n, sample = '?', ''
        try:
            data = {"draw": 1, "start": 0, "length": 2, "search[value]": "", "search[regex]": "false"}
            for i in range(len(heads) + 2):
                data[f"columns[{i}][data]"] = i
            x = s.post(BASE + path, data=data, timeout=120, headers={"X-CSRF-TOKEN": csrf.group(1),
                       "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json()
            n = x.get('recordsTotal')
            sample = str(x.get('data', [])[:1])[:700]
        except Exception as e:
            sample = 'ERR ' + str(e)[:100]
        out.append(f"P{p} {path} n={n} th={'|'.join(heads)} sample={sample}")
restore(s)
for o in out:
    print("::notice::" + o)

log = store.load('loc_log')
if len(log):
    w = pd.to_datetime(log['Аниқланди'], format='%d.%m.%Y %H:%M', errors='coerce')
    log['d'] = w.dt.strftime('%d.%m')
    rec = log[w >= pd.Timestamp(dt.date.today() - dt.timedelta(days=10))]
    t = rec.groupby(['d', 'Ўзгариш']).size().unstack(fill_value=0)
    print("::notice::LOC " + " || ".join(f"{d}: " + ", ".join(f"{k}={v}" for k, v in r.items() if v) for d, r in t.iterrows()))
