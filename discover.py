import os, requests, store, pandas as pd
from sales import login
ids = {239627, 239609}
import datetime as dt
from export import fetch
v = fetch(1, dt.date(2026,11,3), dt.date(2026,11,3))
s = login()
os.makedirs('/tmp/ph', exist_ok=True)
for _, r in v[v['#'].astype(int).isin(ids)].iterrows():
    for k in ('Фото 1', 'Фото 2'):
        u = r.get(k)
        if isinstance(u, str) and u.startswith('http'):
            open(f"/tmp/ph/{r['#']}_{k[-1]}.jpg", 'wb').write(s.get(u, timeout=60).content)
print("::notice::saved " + str(sorted(os.listdir('/tmp/ph'))))
m = store.load('m_2026-11-03')
print("::notice::cols " + str(list(m.columns)))
