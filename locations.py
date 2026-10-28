"""Pharmacy location monitoring.
Sales keeps no history of pharmacy coordinates, so we take a snapshot of /lists/companies every hour
and log every change (location removed / added / moved). Static checks flag suspicious coordinates."""
import datetime as dt
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

import store

TZ = ZoneInfo("Asia/Tashkent")
MOVE_M = 30            # smaller moves are GPS noise
CLUSTER_N = 3          # >= this many pharmacies on one point (~10 m) is suspicious
FAR_KM = 100           # pharmacy this far from the median of its region
UZ = dict(lat=(37.1, 45.6), lon=(55.9, 73.2))


def hav(a1, o1, a2, o2):
    p = np.pi / 180
    return 2 * 6371000 * np.arcsin(np.sqrt(np.sin((a2 - a1) * p / 2) ** 2 +
                                           np.cos(a1 * p) * np.cos(a2 * p) * np.sin((o2 - o1) * p / 2) ** 2))


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    tx = lambda s: s.fillna('').astype(str).str.replace(r'<[^>]+>', '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    ll = raw['location'].fillna('').astype(str).str.extract(r'll=(-?[\d.]+)%2C(-?[\d.]+)')
    return pd.DataFrame({
        'id': raw['id'].astype(int), 'name': tx(raw['name']), 'region': tx(raw['region_id']),
        'district': tx(raw['district_id']), 'reps': tx(raw['users']),
        'lat': pd.to_numeric(ll[1], errors='coerce'), 'lon': pd.to_numeric(ll[0], errors='coerce')})


def diff(prev: pd.DataFrame, cur: pd.DataFrame, t_prev: str, t_now: str) -> pd.DataFrame:
    if not len(prev):
        return pd.DataFrame()
    for c in ('lat', 'lon'):
        prev[c] = pd.to_numeric(prev[c], errors='coerce')
    prev['id'] = prev['id'].astype(int)
    m = cur.merge(prev[['id', 'lat', 'lon', 'name']], on='id', how='outer', suffixes=('', '_old'), indicator='status')
    out = []
    for r in m.itertuples(index=False):
        had, has = pd.notna(r.lat_old), pd.notna(r.lat)
        if r.status == 'left_only':
            kind, dist = 'Янги аптека қўшилди', np.nan
        elif r.status == 'right_only':
            kind, dist = 'Аптека базадан ўчирилди', np.nan
        elif had and not has:
            kind, dist = 'Локация ўчирилди', np.nan
        elif has and not had:
            kind, dist = 'Локация қўйилди', np.nan
        elif had and has:
            dist = float(hav(r.lat_old, r.lon_old, r.lat, r.lon))
            if dist < MOVE_M:
                continue
            kind = 'Локация кўчирилди'
        else:
            continue
        out.append({'Вақт оралиғи': f"{t_prev} – {t_now}", 'Аниқланди': t_now, 'ID': r.id,
                    'Аптека': r.name if isinstance(r.name, str) and r.name else r.name_old,
                    'Вилоят': r.region, 'Туман': r.district, 'Бириктирилган ТП': r.reps, 'Ўзгариш': kind,
                    'Масофа (км)': round(dist / 1000, 2) if pd.notna(dist) else None,
                    'Эски координата': f"{r.lat_old:.6f},{r.lon_old:.6f}" if had else '',
                    'Янги координата': f"{r.lat:.6f},{r.lon:.6f}" if has else ''})
    return pd.DataFrame(out)


def static_flags(c: pd.DataFrame) -> pd.DataFrame:
    x = c.dropna(subset=['lat']).copy()
    notes = {i: [] for i in x.index}
    bad = ~x.lat.between(*UZ['lat']) | ~x.lon.between(*UZ['lon'])
    for i in x.index[bad]:
        notes[i].append("Координата Ўзбекистондан ташқарида (нотўғри киритилган)")
    ok = x[~bad & (x.region != '')]
    med = ok.groupby('region')[['lat', 'lon']].median()
    j = ok.join(med, on='region', rsuffix='_r')
    km = hav(j.lat, j.lon, j.lat_r, j.lon_r) / 1000
    for i in j.index[km > FAR_KM]:
        notes[i].append(f"Ўз вилоятидаги аптекалардан {km[i]:.0f} км узоқда ({x.at[i, 'region']})")
    x['k'] = x.lat.round(4).astype(str) + ',' + x.lon.round(4).astype(str)
    grp = x.groupby('k')['id'].transform('nunique')
    for i in x.index[grp >= CLUSTER_N]:
        notes[i].append(f"Яна {int(grp[i]) - 1} та аптека билан бир нуқтада (~10 м)")
    x['Изоҳ'] = [", ".join(notes[i]) for i in x.index]
    x = x[x['Изоҳ'] != '']
    return pd.DataFrame({'ID': x.id, 'Аптека': x.name, 'Вилоят': x.region, 'Туман': x.district,
                         'Бириктирилган ТП': x.reps, 'Координата': x.lat.map('{:.6f}'.format) + ',' + x.lon.map('{:.6f}'.format),
                         'Изоҳ (нима учун шубҳали)': x['Изоҳ'],
                         'Харита': 'https://yandex.uz/maps/?pt=' + x.lon.astype(str) + ',' + x.lat.astype(str) + '&z=18&l=map'})


def alert_reset(ch: pd.DataFrame):
    """A location deleted through the bot was set again -> tell Bobur right away."""
    if not len(ch):
        return
    gone = store.load('loc_deleted')
    if not len(gone):
        return
    back = ch[ch['Ўзгариш'].isin(['Локация қўйилди', 'Локация кўчирилди']) & ch['ID'].astype(str).isin(set(gone['id'].astype(str)))]
    if not len(back):
        return
    try:
        from telegram import send_text
        for r in back.to_dict('records'):
            g = gone[gone['id'].astype(str) == str(r['ID'])].iloc[-1]
            send_text(f"📍 <b>{r['Аптека']}</b> (ID {r['ID']}) — {g['when']} да бот орқали ўчирилган локация "
                      f"қайта қўйилди ({r['Аниқланди']} да аниқланди). Бириктирилган: {r['Бириктирилган ТП'] or '—'}")
    except Exception as e:
        print("::warning::alert failed " + str(e)[:150])


def snapshot():
    """Hourly job: take a snapshot and append detected changes to the log."""
    from companies import fetch_companies
    raw = pd.concat([fetch_companies(1), fetch_companies(4)], ignore_index=True)
    cur = clean(raw).drop_duplicates('id')
    now = dt.datetime.now(TZ).strftime('%d.%m.%Y %H:%M')
    prev = store.load('companies_last')
    meta = store.load('companies_meta')
    t_prev = meta['time'].iloc[0] if len(meta) else ''
    ch = diff(prev, cur, t_prev, now)
    if len(ch) > 800:
        # a real day never changes this many pharmacies: one of the lists was read under the wrong project
        print(f"::warning::snapshot {now}: {len(ch)} changes look like a glitch - not logged, previous snapshot kept")
        return
    if len(ch):
        log = store.load('loc_log')
        store.save('loc_log', pd.concat([log, ch.astype(str)], ignore_index=True) if len(log) else ch)
    alert_reset(ch)
    store.save('companies_last', cur)
    store.save('companies_meta', pd.DataFrame({'time': [now]}))
    print(f"::notice::snapshot {now}: companies={len(cur)} with_coords={cur.lat.notna().sum()} changes={len(ch)}"
          + (f" kinds={ch['Ўзгариш'].value_counts().to_dict()}" if len(ch) else ""))


def repair(stamps):
    """Drop log entries of glitched snapshots and take a clean base snapshot without logging."""
    from companies import fetch_companies
    log = store.load('loc_log')
    if len(log):
        bad = log['Аниқланди'].isin(stamps)
        store.save('loc_log', log[~bad])
        print(f"::notice::loc_log: removed {int(bad.sum())} glitch rows, kept {int((~bad).sum())}")
    cur = clean(pd.concat([fetch_companies(1), fetch_companies(4)], ignore_index=True)).drop_duplicates('id')
    store.save('companies_last', cur)
    store.save('companies_meta', pd.DataFrame({'time': [dt.datetime.now(TZ).strftime('%d.%m.%Y %H:%M')]}))
    print(f"::notice::base snapshot reset: companies={len(cur)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "repair":
        repair(sys.argv[2:])
    else:
        snapshot()
