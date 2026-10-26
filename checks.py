"""Extra fraud checks on prepared visits (ТП or МП):
- region_out : pharmacy coordinate lies in another region than the one the employee works in
- cluster    : 5+ pharmacies share one point (~10 m)
- multi      : 3+ different employees visited this pharmacy in the same month
- over7      : employee visited the same pharmacy more than 7 times in a month
- new person : employee not in the roster (region inferred, plan 15) - mentioned once
Every flagged case is remembered (offense log) so repeats are marked as repeats."""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import roster as R
import store

CLUSTER_N = 5
MULTI_N = 3
OVER_N = 7
BORDER_KM = 15
SAME = [{'Ферганская', 'Коканд'}, {'г.Ташкент', 'Ташкентская'}]
KNOWN = {'Андижанская', 'Бухарская', 'Джизакская', 'Кашкадарьинская', 'Навоийская', 'Наманганская', 'Самаркандская',
         'Сурхандарьинская', 'Сырдарьинская', 'Ташкентская', 'Ферганская', 'Хорезмская', 'Р.Каракалпакстан',
         'г.Ташкент', 'Коканд'}


def same_region(a, b):
    if a == b:
        return True
    return any(a in s and b in s for s in SAME)


class Geo:
    """Region of a coordinate = majority region of the 15 nearest pharmacies that have a region in the base."""

    def __init__(self, comp: pd.DataFrame):
        c = comp.copy()
        for k in ('lat', 'lon'):
            c[k] = pd.to_numeric(c[k], errors='coerce')
        c['id'] = c['id'].astype(int)
        self.comp = c
        ok = c.dropna(subset=['lat'])
        ok = ok[ok.lat.between(37.1, 45.6) & ok.lon.between(55.9, 73.2)]
        lab = ok[ok.region.isin(KNOWN)]
        self.tree = cKDTree(np.c_[lab.lat.values, lab.lon.values * np.cos(np.radians(41))]) if len(lab) else None
        self.lab = lab.region.values
        # "core" pharmacies: their own region label agrees with the majority of their 15 neighbours,
        # so pharmacies a rep placed in another region do not become reference points for that region
        _, nn = self.tree.query(np.c_[lab.lat.values, lab.lon.values * np.cos(np.radians(41))], k=15) if len(lab) else (None, None)
        maj = [pd.Series(self.lab[row]).value_counts().index[0] for row in nn] if len(lab) else []
        core = lab[[same_region(a, b) for a, b in zip(lab.region.values, maj)]]
        self.reg_trees = {}
        for reg in KNOWN:
            grp = [g for g in SAME if reg in g]
            regs = grp[0] if grp else {reg}
            sub = core[core.region.isin(regs)]
            if len(sub):
                self.reg_trees[reg] = cKDTree(np.c_[sub.lat.values, sub.lon.values * np.cos(np.radians(41))])
        k = ok.lat.round(4).astype(str) + ',' + ok.lon.round(4).astype(str)
        self.cl = dict(zip(ok.id, ok.assign(k=k).groupby('k')['id'].transform('nunique')))
        self.by_name = {}
        for r in c.itertuples(index=False):
            self.by_name.setdefault(str(r.name).strip().lower(), []).append(r)

    def region_of(self, lat, lon):
        if self.tree is None or pd.isna(lat):
            return None
        if not (37.1 <= lat <= 45.6 and 55.9 <= lon <= 73.2):
            return 'Ўзбекистондан ташқари'
        _, idx = self.tree.query([lat, lon * np.cos(np.radians(41))], k=15)
        vals = pd.Series(self.lab[idx]).value_counts()
        return vals.index[0]

    def km_to_region(self, lat, lon, reg):
        """Distance (km) from the point to the nearest base pharmacy of region reg."""
        tr = self.reg_trees.get(reg)
        if tr is None:
            return None
        d, _ = tr.query([lat, lon * np.cos(np.radians(41))])
        return d * 111.0

    def match(self, obj: str, region_hint: str):
        rows = self.by_name.get(str(obj).strip().lower(), [])
        if region_hint:
            r2 = [r for r in rows if r.region == region_hint]
            rows = r2 or rows
        return rows[0] if len(rows) == 1 or (rows and region_hint) else None


def work_region(t: pd.DataFrame, who: str, people: pd.DataFrame):
    """Region the employee works in (roster), else prefix code (ТП) or majority of visited pharmacies (МП)."""
    m = dict(zip(people['key'], people['region']))
    keys = t[who].map(R.key)
    reg = keys.map(m)
    new = reg.isna()
    if new.any():
        pref = t.loc[new, who].map(R.region_from_prefix)
        hint = t['Контр-агент/Врач'].fillna('').str.extract(r'\(([^()]*)\)\s*$')[0]
        maj = hint.where(hint.isin(KNOWN)).groupby(t[who]).agg(lambda s: s.mode().iat[0] if s.notna().any() else None)
        reg.loc[new] = pref.fillna(t.loc[new, who].map(maj))
    return reg.fillna('—'), new


def enrich(t: pd.DataFrame, who: str, people: pd.DataFrame, comp: pd.DataFrame, label: str) -> pd.DataFrame:
    t = t.copy()
    t['Иш ҳудуди'], t['Янги'] = work_region(t, who, people)
    notes = {i: [] for i in t.index}
    for k in ('region_out', 'cluster', 'multi', 'over7'):
        t['f_' + k] = False
    pharm = t['Тип визита'].fillna('').str.contains('аптек', case=False)
    t['pkey'] = t['obj'].str.lower()
    if comp is not None and len(comp):
        geo = Geo(comp)
        hint = t['Контр-агент/Врач'].fillna('').str.extract(r'\(([^()]*)\)\s*$')[0].where(lambda s: s.isin(KNOWN))
        cache = {}
        for i in t.index[pharm]:
            ck = (t.at[i, 'obj'], hint[i])
            if ck not in cache:
                cache[ck] = geo.match(*ck) if t.at[i, 'obj'] else None
            r = cache[ck]
            if r is None or pd.isna(r.lat):
                continue
            t.at[i, 'pkey'] = f"id{r.id}"
            reg = geo.region_of(r.lat, r.lon)
            wr = t.at[i, 'Иш ҳудуди']
            if reg and wr != '—' and not same_region(reg, wr):
                km = geo.km_to_region(r.lat, r.lon, wr)
                if km is None or km > BORDER_KM:
                    t.at[i, 'f_region_out'] = True
                    extra = f" ({wr} даги энг яқин аптекадан {km:.0f} км)" if km is not None else ""
                    notes[i].append(f"Аптека координатаси {reg} ҳудудида, {label} эса {wr} да ишлайди{extra}")
            n = int(geo.cl.get(r.id, 0))
            if n >= CLUSTER_N:
                t.at[i, 'f_cluster'] = True
                notes[i].append(f"Аптека локацияси яна {n - 1} та аптека билан бир нуқтада (~10 м)")
    # month-level checks (pharmacy visits only)
    t['ym'] = t.day.dt.strftime('%Y-%m')
    p = t[pharm & (t['obj'] != '')]
    who_per = p.groupby(['ym', 'pkey'])[who].agg(lambda s: sorted(set(s)))
    for (ym, pk), names in who_per.items():
        if len(names) >= MULTI_N:
            idx = p.index[(p.ym == ym) & (p.pkey == pk)]
            t.loc[idx, 'f_multi'] = True
            for i in idx:
                notes[i].append(f"Бу ойда шу аптекага {len(names)} та {label} борган: " + ", ".join(names))
    cnt = p.groupby(['ym', who, 'pkey']).size()
    for (ym, w, pk), n in cnt[cnt > OVER_N].items():
        idx = p.index[(p.ym == ym) & (p[who] == w) & (p.pkey == pk)]
        t.loc[idx, 'f_over7'] = True
        for i in idx:
            notes[i].append(f"Бу ойда шу аптекага {n} марта визит (7 тадан кўп)")
    # first visit of a new employee - mention once
    first_new = t[t['Янги']].groupby(who).head(1).index
    for i in first_new:
        notes[i].append(f"Янги {label}: рўйхатда йўқ, ҳудуди {t.at[i, 'Иш ҳудуди']} деб олинди, кунлик план 15")
    for i, n in notes.items():
        if n:
            t.at[i, 'Изоҳ'] = "; ".join(([t.at[i, 'Изоҳ']] if t.at[i, 'Изоҳ'] else []) + n)
    for k in ('region_out', 'cluster', 'multi', 'over7'):
        t.loc[t['f_' + k], 'Шубҳали'] = True
    return t


TYPES = {'gap': 'тез ёпилган', 'loc': 'локация ўзгарган', 'photo': 'фото йўқ', 'same': 'фото бир хил',
         'reuse': 'фото қайта', 'dup': 'такрорий визит', 'hours': 'иш вақтидан ташқари', 'region_out': 'бошқа ҳудуд',
         'cluster': 'бир нуқтада 5+', 'multi': '3+ ходим', 'over7': '7+ визит', 'closeup': 'яқин план фото'}


def remember(t: pd.DataFrame, who: str, group: str):
    """Mark repeats using the persistent offense log, then add today's offenses to it."""
    log = store.load(f'offenses_{group}')
    if len(log):
        log['date'] = pd.to_datetime(log['date'])
    new_rows = []
    for k, name in TYPES.items():
        col = 'f_' + k
        if col not in t:
            continue
        for i in t.index[t[col]]:
            w, d = t.at[i, who], t.at[i, 'day']
            if len(log):
                prev = log[(log.who == w) & (log.type == k) & (log.date < d)]['date'].dt.strftime('%d.%m').unique()
                if len(prev):
                    t.at[i, 'Изоҳ'] += f" [такрорий: «{name}» олдин ҳам — {', '.join(sorted(prev)[-3:])}]"
            new_rows.append({'date': d.strftime('%Y-%m-%d'), 'who': w, 'type': k, 'obj': t.at[i, 'obj']})
    if new_rows:
        nd = pd.DataFrame(new_rows)
        if len(log):
            log['date'] = log['date'].dt.strftime('%Y-%m-%d')
            nd = pd.concat([log, nd])
        store.save(f'offenses_{group}', nd.drop_duplicates())
    return t
