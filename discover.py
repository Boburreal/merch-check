import datetime as dt, pandas as pd, vcache, store
from export import fetch
for d in (dt.date(2026,10,26), dt.date(2026,10,27)):
    live = fetch(1, d, d)
    print(f"::notice::live {d}: {len(live)} rows, types={live['Тип визита'].value_counts().to_dict() if len(live) else {}}")
m = store.load('v_meta'); print("::notice::meta " + str(m.to_dict('records'))[:600])
c = store.load('v_tp_2026-10'); print(f"::notice::cache tp oct rows={len(c)} days={pd.to_datetime(c['Дата'],format='%d.%m.%Y').dt.day.value_counts().sort_index().to_dict()}")
