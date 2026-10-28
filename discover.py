import pandas as pd, store
v = store.load('v_tp_2026-10')
v = v[v['Фарм. пред'].str.contains('Торг', na=False)]
v['d'] = pd.to_datetime(v['Дата'], format='%d.%m.%Y').dt.date
tot = chk = 0; out = []
for d, g in v.groupby('d'):
    if d.day > 27: continue
    m = store.load(f"m_{d.isoformat()}")
    ok = set(m[m['category'].isin(['merch', 'none', 'suspicious', 'no_photo'])]['id'].astype(int)) if len(m) else set()
    c = int(g['#'].astype(int).isin(ok).sum()); tot += len(g); chk += c
    out.append(f"{d:%d.%m}:{c}/{len(g)}")
print("::notice::merch coverage " + " ".join(out) + f" | TOTAL {chk}/{tot}")
