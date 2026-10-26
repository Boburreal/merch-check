"""Visit analysis: Факт / Уникальный / шубҳали flags with a plain-language comment per visit."""
import pandas as pd

GAP_MIN = 1
ROLE_RE = r'\s*\((Торг Пред Рус|Торг Пред|Рег\.Роп РУС|Рег\.Роп|Медицинский представитель|Мед\.? ?пред[^()]*)\)\s*$'
FLAGS = {'gap': f'Тез ёпилган (≤{GAP_MIN} дақ)', 'loc': 'Локацияси ўзгарган аптека', 'photo': 'Фото йўқ',
         'same': 'Фото1=Фото2', 'reuse': 'Фото қайта ишл.', 'dup': 'Такрорий визит',
         'hours': 'Иш вақтидан ташқари'}


def prepare(raw: pd.DataFrame, who: str = 'ТП', loc_log: pd.DataFrame | None = None) -> pd.DataFrame:
    t = raw.copy()
    role = t['Фарм. пред'].str.extract(r'\(([^()]*)\)\s*$')[0]
    t['Лавозим'] = role.fillna('—').str.replace(' РУС', '').str.replace(' Рус', '')
    name = t['Фарм. пред'].str.replace(ROLE_RE, '', regex=True)
    t[who] = name.str.replace(ROLE_RE, '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    t['Регион'] = t[who].str.extract(r'^\(([^)]*)\)')[0].fillna('—')
    t['dt'] = pd.to_datetime(t['Время завершения визита'], format='%d.%m.%Y %H:%M', errors='coerce')
    t['day'] = pd.to_datetime(t['Дата'], format='%d.%m.%Y')
    t['obj'] = t['Контр-агент/Врач'].fillna('').str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip()
    t['id'] = t['#'].astype(int)
    t = t.sort_values([who, 'day', 'dt', 'id']).reset_index(drop=True)

    note = [[] for _ in range(len(t))]
    f = {k: pd.Series(False, index=t.index) for k in FLAGS}
    g = t.groupby([who, 'day'])
    prev_dt, prev_obj = g['dt'].shift(), g['obj'].shift()
    gap = (t.dt - prev_dt).dt.total_seconds() / 60
    m = (gap <= GAP_MIN) & (prev_obj != t.obj)
    f['gap'] = m
    for i in t.index[m]:
        note[i].append(f"Олдинги визит ({prev_dt[i]:%H:%M}, «{prev_obj[i][:40]}») дан {int(gap[i])} дақиқа кейин ёпилган")
    # pharmacy location changed (from the hourly snapshot log) on the visit day or up to 3 days before
    f['loc'] = pd.Series(False, index=t.index)
    if loc_log is not None and len(loc_log):
        lg = loc_log.copy()
        lg['when'] = pd.to_datetime(lg['Аниқланди'], format='%d.%m.%Y %H:%M', errors='coerce')
        lg = lg[lg['Ўзгариш'].isin(['Локация ўчирилди', 'Локация қўйилди', 'Локация кўчирилди'])]
        by_name = {k: g for k, g in lg.groupby(lg['Аптека'].str.strip().str.lower())}
        for i in t.index:
            g = by_name.get(t.at[i, 'obj'].lower())
            if g is None or pd.isna(t.at[i, 'dt']):
                continue
            hit = g[(g.when >= t.at[i, 'dt'] - pd.Timedelta(days=3)) & (g.when <= t.at[i, 'dt'] + pd.Timedelta(hours=2))]
            for r in hit.itertuples(index=False):
                f['loc'][i] = True
                d = f", {r[8]} км" if r[8] not in (None, '', 'nan', 'None') else ''
                note[i].append(f"Аптека локацияси ўзгартирилган: {r[7].lower()}{d} ({r[0]})")
    p1 = t['Фото 1'].fillna('').str.startswith('http')
    p2 = t['Фото 2'].fillna('').str.startswith('http')
    m = ~(p1 & p2)
    f['photo'] = m
    for i in t.index[m]:
        note[i].append("Фото йўқ (" + ", ".join(n for n, ok in [("Фото 1", p1[i]), ("Фото 2", p2[i])] if not ok) + ")")
    m = p1 & (t['Фото 1'] == t['Фото 2'])
    f['same'] = m
    for i in t.index[m]:
        note[i].append("Фото 1 ва Фото 2 бир хил файл")
    allp = pd.concat([t.loc[p1, ['Фото 1', 'id']].rename(columns={'Фото 1': 'u'}),
                      t.loc[p2, ['Фото 2', 'id']].rename(columns={'Фото 2': 'u'})]).drop_duplicates()
    cnt = allp.groupby('u')['id'].nunique()
    reused = set(cnt[cnt > 1].index)
    if reused:
        owners = allp[allp.u.isin(reused)].groupby('u')['id'].apply(list).to_dict()
        for i in t.index:
            for c in ('Фото 1', 'Фото 2'):
                u = t.at[i, c]
                if u in reused:
                    others = [x for x in owners[u] if x != t.at[i, 'id']]
                    f['reuse'][i] = True
                    note[i].append(f"{c} бошқа визитда ҳам ишлатилган (#{', #'.join(map(str, others[:3]))})")
    m = t.duplicated([who, 'day', 'obj'], keep='first') & (t.obj != '')
    f['dup'] = m
    for i in t.index[m]:
        note[i].append("Шу куни шу объектга такрорий визит")
    h = t.dt.dt.hour
    m = t.dt.notna() & ((h < 8) | (h >= 20))
    f['hours'] = m
    for i in t.index[m]:
        note[i].append(f"Иш вақтидан ташқари ёпилган ({t.dt[i]:%H:%M})")
    for k, v in f.items():
        t['f_' + k] = v
    t['Шубҳали'] = [len(n) > 0 for n in note]
    t['Изоҳ'] = ["; ".join(n) for n in note]
    return t
