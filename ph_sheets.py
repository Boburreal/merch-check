"""Pharmacy visit tables Bobur wants (instead of the old location checks):
1. Ходим × аптека  - how many times each ТП/МП visited each pharmacy
2. Аптека × ходимлар - how many and which ТП/МП visit each pharmacy
3. Бир нуқтада 7+ аптека - pharmacies whose base location is one point (~10 m) shared by 7+ pharmacies, and who visited them"""
import pandas as pd

CLUSTER_N = 7


def _pharm(t):
    return t[t['Тип визита'].fillna('').str.contains('аптек', case=False) & (t['obj'].fillna('') != '')]


def tables(t: pd.DataFrame, who: str):
    p = _pharm(t)
    if not len(p):
        return None, None, None
    days = lambda s: ', '.join(sorted(pd.to_datetime(s).dt.strftime('%d.%m').unique()))
    a = (p.groupby([who, 'pkey'])
         .agg(**{'Ҳудуд': ('Иш ҳудуди', 'first'), 'Аптека': ('Контр-агент/Врач', 'first'),
                 'Визит сони': ('id', 'size'), 'Саналар': ('day', days)})
         .reset_index().drop(columns='pkey')
         .sort_values([who, 'Визит сони'], ascending=[True, False]))
    a = a[[who, 'Ҳудуд', 'Аптека', 'Визит сони', 'Саналар']]

    def people(g):
        c = g[who].value_counts()
        return '; '.join(f"{n} ({k})" for n, k in c.items())
    b = (p.groupby('pkey')
         .apply(lambda g: pd.Series({'Аптека': g['Контр-агент/Врач'].iloc[0], f'{who} сони': g[who].nunique(),
                                     f'Қайси {who} (визит сони)': people(g), 'Жами визит': len(g)}), include_groups=False)
         .reset_index(drop=True)
         .sort_values([f'{who} сони', 'Жами визит'], ascending=False))

    c = None
    if 'pt' in p and 'pt_n' in p:
        q = p[pd.to_numeric(p['pt_n'], errors='coerce').fillna(0) >= CLUSTER_N]
        if len(q):
            c = (q.groupby(['pt', 'pkey'])
                 .agg(**{'Шу нуқтадаги аптекалар (базада)': ('pt_n', 'first'), 'Аптека': ('Контр-агент/Врач', 'first'),
                         f'Ким борган': (who, lambda s: ', '.join(sorted(set(s)))), 'Визит сони': ('id', 'size')})
                 .reset_index().drop(columns='pkey').rename(columns={'pt': 'Нуқта (координата)'}))
            c['Харита'] = 'https://maps.google.com/?q=' + c['Нуқта (координата)']
            c = c.sort_values(['Шу нуқтадаги аптекалар (базада)', 'Нуқта (координата)'], ascending=[False, True])
    return a, b, c


def write(wb, t: pd.DataFrame, who: str, prefix: str = ''):
    from xlsx_report import _sheet
    a, b, c = tables(t, who)
    if a is None:
        return
    _sheet(wb, f'{prefix}{who} × аптека', a, total=False,
           widths={who: 32, 'Ҳудуд': 16, 'Аптека': 45, 'Визит сони': 10, 'Саналар': 60})
    _sheet(wb, f'{prefix}Аптека × {who}', b, total=False,
           widths={'Аптека': 45, f'{who} сони': 9, f'Қайси {who} (визит сони)': 90, 'Жами визит': 10})
    if c is not None and len(c):
        _sheet(wb, f'{prefix}Бир нуқтада 7+ аптека', c, total=False, links=('Харита',),
               widths={'Нуқта (координата)': 22, 'Шу нуқтадаги аптекалар (базада)': 14, 'Аптека': 45,
                       'Ким борган': 60, 'Визит сони': 10, 'Харита': 9})
