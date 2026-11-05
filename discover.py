"""One-off: find the doctors list in Sales and summarise the recent pharmacy-location log."""
import re, datetime as dt
import pandas as pd
import store
from sales import login, switch_project, restore, BASE

s = login()
for p in (1, 4):
    switch_project(s, p)
    home = s.get(BASE + "/", timeout=60).text
    links = sorted(set(re.findall(r'href="(?:https://sales\.asklepiygroup\.uz)?(/lists/[a-z_\-]+)"', home)))
    print(f"::notice::project {p} links: {' '.join(links)}")
    for path in links:
        if 'compan' in path:
            continue
        r = s.get(BASE + path, timeout=60)
        heads = [re.sub(r'<[^>]+>|\s+', ' ', h).strip() for h in re.findall(r'<th[^>]*>(.*?)</th>', r.text, re.S)]
        title = re.search(r'<title>(.*?)</title>', r.text, re.S)
        print(f"::notice::{p} {path} [{r.status_code}] {title.group(1).strip() if title else ''} | th: {' | '.join(heads)[:400]}")
restore(s)

log = store.load('loc_log')
if len(log):
    w = pd.to_datetime(log['Аниқланди'], format='%d.%m.%Y %H:%M', errors='coerce')
    log['d'] = w.dt.strftime('%d.%m')
    rec = log[w >= pd.Timestamp(dt.date.today() - dt.timedelta(days=10))]
    t = rec.groupby(['d', 'Ўзгариш']).size().unstack(fill_value=0)
    for d, r in t.iterrows():
        print(f"::notice::loc {d}: " + ", ".join(f"{k}={v}" for k, v in r.items() if v))
    print(f"::notice::loc total rows={len(log)} cols={list(log.columns)}")
