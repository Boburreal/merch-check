import datetime as dt, json
from merch import check_visit, pick_model
from export import fetch
v = fetch(1, dt.date(2026,11,3), dt.date(2026,11,3))
m = pick_model()
for _, r in v[v['#'].astype(int).isin({239627, 239609})].iterrows():
    res = check_visit(m, r['Фото 1'], r['Фото 2'])
    print(f"::notice::{r['#']} cat={res['category']} vitrina={res['vitrina']} kassa={res['kassa']} raw={json.dumps(res.get('raw'))[:300]}")
