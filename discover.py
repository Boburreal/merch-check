import datetime as dt, pandas as pd, vcache, az
v = vcache.get('tp', dt.date(2026,10,20), dt.date(2026,10,27))
v = v.assign(day=pd.to_datetime(v['Дата'], format='%d.%m.%Y'))
v['who'] = v['Фарм. пред'].str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip()
v['reg'] = v['who'].map(az.short_region)
for d, g in v.groupby(v.day.dt.date):
    ph = g[g['Тип визита'].fillna('').str.contains('аптек|контрагент', case=False)]
    t = ph[ph['Фарм. пред'].str.contains('Торг', na=False)]
    c = t[t.reg.notna()].groupby('who').size()
    print(f"::notice::{d} all={len(g)} pharm={len(ph)} tp={len(t)} tp_regions={t.reg.notna().sum()} people>=2={int((c>=2).sum())} types={g['Тип визита'].value_counts().to_dict()}")
