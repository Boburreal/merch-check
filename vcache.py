"""Visit export cache (encrypted, per project and month) so the bot does not download 3 months every time.
Finished months are downloaded once; the current month is topped up from the last stored day."""
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd

import store

TZ = ZoneInfo("Asia/Tashkent")
COLS = ['#', 'Дата', 'Тип визита', 'Фарм. пред', 'Контр-агент/Врач', 'Время завершения визита']
PROJ = {'tp': 1, 'mp': 4}


def _months(d1, d2):
    m = d1.replace(day=1)
    while m <= d2:
        yield m
        m = (m + dt.timedelta(days=32)).replace(day=1)


def _meta():
    m = store.load('v_meta')
    return dict(zip(m['name'], m['fetched'])) if len(m) else {}


def _save_meta(meta):
    store.save('v_meta', pd.DataFrame({'name': list(meta), 'fetched': list(meta.values())}))


def put(raw: pd.DataFrame, grp: str):
    """Merge a fresh export (any date range) into the monthly cache."""
    if not len(raw):
        return
    raw = raw[[c for c in COLS if c in raw]].copy()
    day = pd.to_datetime(raw['Дата'], format='%d.%m.%Y', errors='coerce')
    meta = _meta()
    now = dt.datetime.now(TZ).strftime('%Y-%m-%d')
    for ym, part in raw.groupby(day.dt.strftime('%Y-%m')):
        name = f'v_{grp}_{ym}'
        old = store.load(name)
        new = pd.concat([old, part]) if len(old) else part
        store.save(name, new.drop_duplicates('#', keep='last'))
        meta[name] = now
    _save_meta(meta)


def get(grp: str, d1: dt.date, d2: dt.date) -> pd.DataFrame:
    from export import fetch
    meta = _meta()
    today = dt.datetime.now(TZ).date()
    start = None
    for m in _months(d1, d2):
        name = f'v_{grp}_{m:%Y-%m}'
        end = (m + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        fetched = meta.get(name)
        if fetched and dt.date.fromisoformat(fetched) > end:
            continue                                   # finished month, stored after it ended
        if fetched:                                    # current month: top up from the last stored day
            old = store.load(name)
            last = pd.to_datetime(old['Дата'], format='%d.%m.%Y').max().date() if len(old) else m
            s = min(last, dt.date.fromisoformat(fetched))
        else:
            s = m
        start = s if start is None else min(start, s)
    if start is not None:
        put(fetch(PROJ[grp], start, min(d2, today)), grp)
    parts = [store.load(f'v_{grp}_{m:%Y-%m}') for m in _months(d1, d2)]
    parts = [p for p in parts if len(p)]
    v = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
    day = pd.to_datetime(v['Дата'], format='%d.%m.%Y', errors='coerce')
    return v[(day.dt.date >= d1) & (day.dt.date <= d2)]
