"""Manager check on request (from the bot): one employee or a regional team, for a week or a month.
Подозрительные визиты (with reasons), мерч (Витрина/Касса, ИИ), охват закреплённых аптек -> Excel (RU) + Telegram summary."""
import datetime as dt, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import roster as R
import store

TZ = ZoneInfo("Asia/Tashkent")
MERCH_MIN = 20          # minutes of AI merch checking per request at most
MERCH_CAP = 400         # visits per request at most (keeps the free daily quota for the daily report)
MERCH_INFO = {'quota': False}
PERIODS = {'w0': 'Шу ҳафта', 'w1': 'Ўтган ҳафта', 'm0': 'Шу ой', 'm1': 'Ўтган ой'}
REG_ALIAS = {'ташкент шахар': 'г.Ташкент', 'тошкент шахар': 'г.Ташкент', 'г.ташкент': 'г.Ташкент',
             'ташкент вил': 'Ташкентская', 'тошкент вил': 'Ташкентская', 'т.обл': 'Ташкентская',
             'каракалпак': 'Р.Каракалпакстан', 'нукус': 'Р.Каракалпакстан', 'хоразм': 'Хорезмская', 'урганч': 'Хорезмская',
             'ургенч': 'Хорезмская', 'карши': 'Кашкадарьинская', 'қарши': 'Кашкадарьинская', 'термез': 'Сурхандарьинская',
             'термиз': 'Сурхандарьинская', 'гулистон': 'Сырдарьинская', 'гулистан': 'Сырдарьинская', 'навои': 'Навоийская',
             'навоий': 'Навоийская', 'жиззах': 'Джизакская', 'джизак': 'Джизакская', 'кўқон': 'Коканд', 'қўқон': 'Коканд',
             'коканд': 'Коканд', 'фаргона': 'Ферганская', 'фарғона': 'Ферганская', 'бухоро': 'Бухарская',
             'самарқанд': 'Самаркандская', 'андижон': 'Андижанская', 'наманган': 'Наманганская'}


def people():
    """Everyone in the roster, in a fixed order (button numbers refer to it)."""
    r = R.load()
    tp = r['tp'].assign(grp='ТП')[['name', 'region', 'key', 'grp']]
    mp = r['mp'].assign(grp='МП')[['name', 'region', 'key', 'grp']]
    p = pd.concat([tp, mp], ignore_index=True).drop_duplicates('key')
    return p.sort_values(['grp', 'key']).reset_index(drop=True)


def regions(p):
    return sorted(p['region'].unique())


def resolve(q: str):
    """Text -> list of targets: ('r', i) regional team or ('p', i) one person."""
    p = people()
    regs = regions(p)
    s = re.sub(r'\s+', ' ', q.lower().translate(R.LAT2CYR)).strip()
    out = []
    for k, v in REG_ALIAS.items():
        if k in s and v in regs and ('r', regs.index(v)) not in out:
            out.append(('r', regs.index(v)))
    if not out and len(s) >= 4:
        for i, reg in enumerate(regs):
            if reg.lower().replace('г.', '').startswith(s[:5]):
                out.append(('r', i))
    toks = [t for t in s.split() if len(t) >= 3]
    if toks:
        for i, r in p.iterrows():
            words = (r.key + ' ' + re.sub(r'[()]', ' ', r['name'].lower().translate(R.LAT2CYR))).split()
            if all(any(w.startswith(t) for w in words) for t in toks):
                out.append(('p', i))
    return out


def label(t):
    p = people()
    if t[0] == 'r':
        reg = regions(p)[t[1]]
        n = p[p.region == reg].groupby('grp').size().to_dict()
        return f"👥 {reg} жамоаси (ТП {n.get('ТП', 0)}, МП {n.get('МП', 0)})"
    r = p.iloc[t[1]]
    return f"👤 {r['name']} ({r.grp}, {r.region})"


def period(code, today=None):
    today = today or dt.datetime.now(TZ).date()
    mon = today - dt.timedelta(days=today.weekday())
    if code == 'w0':
        return mon, today
    if code == 'w1':
        return mon - dt.timedelta(days=7), mon - dt.timedelta(days=1)
    if code == 'm0':
        return today.replace(day=1), today
    last = today.replace(day=1) - dt.timedelta(days=1)
    return last.replace(day=1), last


# ---------------------------------------------------------------- merch for the selected ТП visits
def merch_for(tp: pd.DataFrame, d1, d2):
    from merch import check_visit, pick_model, comment, DailyQuotaExceeded
    days = [d1 + dt.timedelta(days=i) for i in range((d2 - d1).days + 1)]
    stored = {d: store.load(f"m_{d.isoformat()}") for d in days}
    have = set()
    for d, m in stored.items():
        if len(m):
            m = m[m['category'] != 'error']
            have |= set(m['id'].astype(int))
    todo = tp[~tp.id.isin(have)].head(MERCH_CAP)
    new, t0, stop = {}, time.time(), [False]
    try:
        model = pick_model() if len(todo) else None
    except DailyQuotaExceeded:
        stop[0] = True
        todo = todo[:0]
    if len(todo):

        def work(r):
            if stop[0] or time.time() - t0 > MERCH_MIN * 60:
                return None
            try:
                res = check_visit(model, r['Фото 1'], r['Фото 2'])
            except DailyQuotaExceeded:
                stop[0] = True
                return None
            except Exception as e:
                res = {"category": "error", "vitrina": 0, "kassa": 0, "raw": {"error": str(e)[:150]}}
            return r['day'].date(), {"id": r['id'], "category": res['category'], "vitrina": res['vitrina'], "kassa": res['kassa'],
                                     "comment": comment(res.get('raw')), "raw": json.dumps(res.get('raw'), ensure_ascii=False)}

        with ThreadPoolExecutor(3) as ex:
            for f in as_completed([ex.submit(work, r) for _, r in todo.iterrows()]):
                x = f.result()
                if x:
                    new.setdefault(x[0], []).append(x[1])
        for d, rows in new.items():           # saved per day, so the daily reports reuse them
            old = stored.get(d, pd.DataFrame())
            allm = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if len(old) else pd.DataFrame(rows)
            allm['id'] = allm['id'].astype(int)
            allm = allm.drop_duplicates('id', keep='last')
            store.save(f"m_{d.isoformat()}", allm)
            stored[d] = allm
    parts = [m for m in stored.values() if len(m)]
    m = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=['id', 'category', 'vitrina', 'kassa', 'comment'])
    m['id'] = m['id'].astype(int)
    print(f"::notice::merch todo={len(todo)} checked_now={sum(len(v) for v in new.values())} quota_stop={stop[0]}")
    MERCH_INFO['quota'] = stop[0]
    return m.drop_duplicates('id', keep='last')


# ---------------------------------------------------------------- coverage of attached pharmacies
def coverage(emp_key, visits, comp, hist=None):
    """hist: {pharmacy norm name -> last visit date in the last 3 months} for this employee."""
    from bot import norm
    hist = hist or {}
    reps_keys = comp['reps'].fillna('').map(lambda s: {R.key(x.strip()) for x in s.split(',') if x.strip()})
    att = comp[reps_keys.map(lambda ks: emp_key in ks)]
    vn = visits.assign(n=visits['obj'].map(norm))
    cnt = vn.groupby('n').agg(k=('id', 'size'), last=('day', 'max'))
    rows = []
    for r in att.itertuples():
        x = cnt.loc[norm(r.name)] if norm(r.name) in cnt.index else None
        rows.append({'id': r.id, 'name': r.name, 'district': r.district, 'att': True,
                     'k': int(x.k) if x is not None else 0, 'last': x['last'] if x is not None else None,
                     'h': hist.get(norm(r.name))})
    att_n = {norm(n) for n in att['name']}
    for n, x in cnt.iterrows():
        if n not in att_n:
            nm = vn[vn.n == n]['obj'].iloc[0]
            rows.append({'id': '', 'name': nm, 'district': '', 'att': False, 'k': int(x.k), 'last': x['last'], 'h': hist.get(n)})
    return pd.DataFrame(rows, columns=['id', 'name', 'district', 'att', 'k', 'last', 'h'])


# ---------------------------------------------------------------- audio recordings
AUDIO_CAP = 700         # recordings measured per request at most (free ffmpeg check)
AUDIO_AI_PER = 3        # recordings per employee also listened to by the AI (uses the free Gemini limit)
AUDIO_MIN = 20


def audio_for(allv: pd.DataFrame):
    """Check the recordings of pharmacy visits; results stored per day (a_YYYY-MM-DD) and reused."""
    import random
    import audio
    from sales import login, switch_project
    ph = allv[allv['Тип визита'].fillna('').str.contains('аптек', case=False) | allv['Тип визита'].fillna('').str.contains('контрагент', case=False)]
    days = sorted({d.date() for d in ph['day']})
    stored = {d: store.load(f"a2_{d.isoformat()}") for d in days}
    have = {}
    for d, a in stored.items():
        for r in a.to_dict('records'):
            have[int(r['id'])] = r
    # AI sample: a few random recordings per employee that the AI has not heard yet
    rnd = random.Random(42)
    ai_ids = set()
    for who, g in ph.groupby('who'):
        heard = [i for i in g['id'] if have.get(int(i), {}).get('ai')]
        need = max(0, AUDIO_AI_PER - len(heard))
        cand = [int(i) for i in g['id'] if not have.get(int(i), {}).get('ai')]
        ai_ids |= set(rnd.sample(cand, min(need, len(cand))))
    todo = ph[~ph['id'].astype(int).isin(set(have)) | ph['id'].astype(int).isin(ai_ids)].head(AUDIO_CAP)
    new, t0 = {}, time.time()
    for grp, proj in (('ТП', 1), ('МП', 4)):
        part = todo[todo['grp'] == grp] if 'grp' in todo else todo.iloc[0:0]
        if not len(part):
            continue
        s = login(); switch_project(s, proj)
        try:
            def work(r):
                if time.time() - t0 > AUDIO_MIN * 60:
                    return None
                try:
                    x = audio.check(s, int(r['id']), use_ai=int(r['id']) in ai_ids)
                except Exception as e:
                    print("::warning::audio " + str(e)[:120]); return None
                return r['day'].date(), x
            with ThreadPoolExecutor(4) as ex:
                for f in as_completed([ex.submit(work, r) for _, r in part.iterrows()]):
                    x = f.result()
                    if x:
                        new.setdefault(x[0], []).append(x[1])
        finally:
            switch_project(s, 1)
    for d, rows in new.items():
        old = stored.get(d, pd.DataFrame())
        allr = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if len(old) else pd.DataFrame(rows)
        allr['id'] = allr['id'].astype(int)
        allr = allr.drop_duplicates('id', keep='last')
        store.save(f"a2_{d.isoformat()}", allr)
        for r in allr.to_dict('records'):
            have[int(r['id'])] = r
    print(f"::notice::audio todo={len(todo)} done_now={sum(len(v) for v in new.values())} ai={len(ai_ids)}")
    rows = [have[int(i)] for i in ph['id'] if int(i) in have]
    return pd.DataFrame(rows, columns=['id', 'url', 'dur', 'silence_pct', 'status', 'comment', 'ai', 'products'])


# ---------------------------------------------------------------- the check
def run(target, code):
    T0 = time.time()
    step = lambda m: print(f"::notice::{int(time.time() - T0)}s {m}", flush=True)
    from export import fetch
    from analysis import prepare
    from checks import enrich, TYPES
    from ru import translate_workbook
    from telegram import send_text, send_file

    p = people()
    d1, d2 = period(code)
    if target[0] == 'r':
        reg = regions(p)[target[1]]
        team = p[p.region == reg]
        title = f"{reg} жамоаси"
    else:
        team = p.iloc[[target[1]]]
        title = team['name'].iloc[0]
    keys = set(team.key)
    ros = R.load()
    comp = store.load('companies_last')
    for k in ('name', 'district', 'reps'):
        comp[k] = comp[k].fillna('').astype(str)
    loc_log = store.load('loc_log')

    step('start')
    parts = {}
    for grp, proj in (('ТП', 1), ('МП', 4)):
        if not (team.grp == grp).any():
            continue
        t = prepare(fetch(proj, d1, d2), grp, loc_log)
        if grp == 'ТП':
            t = t[~t['Лавозим'].str.contains('Медицин')]
        t = enrich(t, grp, ros['tp'] if grp == 'ТП' else ros['mp'], comp, grp)      # whole base: cluster/multi checks
        t = t[t[grp].map(R.key).isin(keys)].copy()
        t['who'] = t[grp]
        t['grp'] = grp
        parts[grp] = t
    step('fetched')
    tp = parts.get('ТП', pd.DataFrame())
    merch = merch_for(tp, d1, d2) if len(tp) else pd.DataFrame(columns=['id', 'category', 'vitrina', 'kassa', 'comment'])
    if len(tp):
        m = tp[['id']].merge(merch, on='id', how='left')
        tp['cat'] = m['category'].values
        tp['vit'] = pd.to_numeric(m['vitrina'], errors='coerce').fillna(0).astype(int).values
        tp['kas'] = pd.to_numeric(m['kassa'], errors='coerce').fillna(0).astype(int).values
        tp['mcom'] = m['comment'].fillna('').values
        tp['mraw'] = m['raw'].fillna('').values if 'raw' in m else ''
        close = tp['cat'].eq('suspicious')
        tp.loc[close, 'Шубҳали'] = True
        tp.loc[close, 'Изоҳ'] = (tp.loc[close, 'Изоҳ'] + '; Мерч фотоси яқин пландан (аптека кўринмайди)').str.strip('; ')
        parts['ТП'] = tp
    allv = pd.concat(parts.values(), ignore_index=True) if parts else pd.DataFrame()
    AU = audio_for(allv) if len(allv) else pd.DataFrame(columns=['id', 'url', 'dur', 'silence_pct', 'status', 'comment', 'ai', 'products'])
    step('audio')
    if len(AU):
        a = allv[['id']].merge(AU.assign(id=AU['id'].astype(int)), on='id', how='left')
        allv['a_status'] = a['status'].values
        bad = allv['a_status'].isin(['Подозрительная', 'Нет записи'])
        allv.loc[bad, 'Шубҳали'] = True
        why = ('Аудиозапись: ' + a['status'].fillna('') + ' — ' + a['comment'].fillna('')).values
        allv.loc[bad, 'Изоҳ'] = (allv.loc[bad, 'Изоҳ'].fillna('') + '; ' + pd.Series(why, index=allv.index)[bad]).str.strip('; ')
    else:
        allv['a_status'] = None

    # ---------- summary per employee
    # last visit of each employee to each pharmacy in the last 3 months (from the visit cache)
    from bot import norm
    import vcache
    hist = {}
    h2 = dt.datetime.now(TZ).date(); h1 = h2 - dt.timedelta(days=92)
    for grp, g in (('tp', 'ТП'), ('mp', 'МП')):
        if not (team.grp == g).any():
            continue
        try:
            hv = vcache.get(grp, h1, h2)
        except Exception as e:
            print("::warning::history " + str(e)[:120]); continue
        if not len(hv):
            continue
        hv = hv.assign(k=hv['Фарм. пред'].str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).map(R.key),
                       n=hv['Контр-агент/Врач'].fillna('').str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).map(norm),
                       d=pd.to_datetime(hv['Дата'], format='%d.%m.%Y', errors='coerce'))
        hv = hv[hv.k.isin(keys)]
        for (k, n), d in hv.groupby(['k', 'n'])['d'].max().items():
            hist.setdefault(k, {})[n] = d
    step('history')
    summ, cov_rows = [], []
    for r in team.itertuples():
        v = allv[allv['who'].map(R.key) == r.key] if len(allv) else allv
        row = {'Сотрудник': r.name, 'Должность': r.grp, 'Регион': r.region, 'Визитов': len(v),
               'Рабочих дней': v['day'].nunique() if len(v) else 0,
               'Уникальных объектов': v['obj'].nunique() if len(v) else 0,
               'Подозрительных': int(v['Шубҳали'].sum()) if len(v) else 0}
        row['% подозр.'] = round(row['Подозрительных'] / row['Визитов'] * 100) if row['Визитов'] else 0
        for k, nm in TYPES.items():
            row[nm] = int(v['f_' + k].sum()) if len(v) and ('f_' + k) in v else 0
        if r.grp == 'ТП' and len(v):
            c = v['cat']
            row.update({'Мерч проверено': int(c.isin(['merch', 'none', 'suspicious']).sum()),
                        'Витрина': int(v['vit'].sum()), 'Касса': int(v['kas'].sum()),
                        'Без мерча': int(c.eq('none').sum()), 'Крупный план': int(c.eq('suspicious').sum()),
                        'Не проверено': int((~c.isin(['merch', 'none', 'suspicious'])).sum())})
        cv = coverage(r.key, v if len(v) else pd.DataFrame(columns=['obj', 'id', 'day']), comp, hist.get(r.key))
        att = cv[cv.att]
        row.update({'Закреплено аптек': len(att), 'Посещено закреплённых': int((att.k > 0).sum()),
                    'Не посещено': int((att.k == 0).sum()),
                    'Охват %': round((att.k > 0).mean() * 100) if len(att) else 0,
                    'Посещено незакреплённых': int((~cv.att).sum()),
                    'Аптек с 7+ визитами': int((cv.k > 7).sum())})
        if len(v):
            st = v['a_status']
            row.update({'Записей проверено': int(st.notna().sum()), 'Без записи': int(st.eq('Нет записи').sum()),
                        'Подозр. записей': int(st.eq('Подозрительная').sum())})
        summ.append(row)
        cov_rows.append(cv.assign(emp=r.name))
    S = pd.DataFrame(summ)
    C = pd.concat(cov_rows, ignore_index=True) if cov_rows else pd.DataFrame()

    # ---------- Excel
    path = f"/tmp/Проверка {title.replace('/', '-')} {d1:%d.%m}-{d2:%d.%m.%Y}.xlsx"
    step('summary')
    wb = Workbook()
    hdr = PatternFill('solid', fgColor='1F4E78'); red = PatternFill('solid', fgColor='F8CBAD')
    yel = PatternFill('solid', fgColor='FFF2CC'); grn = PatternFill('solid', fgColor='E2EFDA')

    def table(ws, df, start=1, widths=None):
        for j, c in enumerate(df.columns, 1):
            x = ws.cell(start, j, c); x.font = Font(bold=True, color='FFFFFF'); x.fill = hdr
            x.alignment = Alignment(wrap_text=True, vertical='center')
        for i, row in enumerate(df.itertuples(index=False), start + 1):
            for j, val in enumerate(row, 1):
                if val is None or val is pd.NaT or (isinstance(val, float) and pd.isna(val)):
                    val = None
                elif isinstance(val, (pd.Timestamp, dt.date)):
                    val = val.strftime('%d.%m.%Y')
                elif hasattr(val, 'item'):
                    val = val.item()
                c = ws.cell(i, j, val)
                if isinstance(val, str) and val.startswith('http'):         # photo links: clickable
                    c.hyperlink = val
                    c.value = 'Фото 1' if df.columns[j - 1] == 'Фото 1' else 'Фото 2' if df.columns[j - 1] == 'Фото 2' else ('Слушать' if df.columns[j - 1] == 'Запись' else 'Открыть фото')
                    c.font = Font(color='0563C1', underline='single')
        for j, c in enumerate(df.columns, 1):
            ws.column_dimensions[get_column_letter(j)].width = (widths or {}).get(c, max(10, min(40, len(str(c)) + 2)))
        ws.freeze_panes = ws.cell(start + 1, 2)

    ws = wb.active; ws.title = 'Сводка'
    ws['A1'] = f"Проверка: {title}"; ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = f"Период: {d1:%d.%m.%Y} – {d2:%d.%m.%Y} ({PERIODS[code].lower()})"
    table(ws, S, 4, {'Сотрудник': 32, 'Регион': 18})
    for i in range(5, 5 + len(S)):
        pc = ws.cell(i, list(S.columns).index('% подозр.') + 1)
        pc.fill = red if (pc.value or 0) >= 20 else yel if (pc.value or 0) >= 10 else grn
        oc = ws.cell(i, list(S.columns).index('Охват %') + 1)
        oc.fill = red if (oc.value or 0) < 50 else yel if (oc.value or 0) < 80 else grn

    ws = wb.create_sheet('Подозрительные визиты')
    if len(allv):
        sv = allv[allv['Шубҳали']].sort_values(['who', 'dt'])
        D = pd.DataFrame({'Дата': sv['day'], 'Время': sv['dt'].dt.strftime('%H:%M'), 'Сотрудник': sv['who'],
                          'Тип визита': sv['Тип визита'], 'Объект': sv['Контр-агент/Врач'], 'Адрес': sv.get('Адрес'),
                          'Причина': sv['Изоҳ'], 'Фото 1': sv['Фото 1'], 'Фото 2': sv['Фото 2']})
        table(ws, D, 1, {'Сотрудник': 30, 'Объект': 34, 'Адрес': 30, 'Причина': 70, 'Фото 1': 10, 'Фото 2': 10})
        for i in range(2, len(D) + 2):
            ws.cell(i, 7).alignment = Alignment(wrap_text=True, vertical='top')

    if len(tp):
        ws = wb.create_sheet('Мерч')
        res = tp['cat'].map({'merch': 'Мерч есть', 'none': 'Нет мерча', 'suspicious': 'Крупный план (не засчитан)',
                             'no_photo': 'Нет фото'}).fillna('Не проверено')
        def merch_photo(r):
            """Link to the photo on which the AI saw both products (Риномакс + Форсил)."""
            try:
                ph = json.loads(r['mraw']).get('photos', []) if r['mraw'] else []
            except Exception:
                ph = []
            urls = [u for u in (r['Фото 1'], r['Фото 2']) if isinstance(u, str) and u.startswith('http')]
            for i, x in enumerate(ph):
                if x.get('rinomaks') and x.get('forsil') and i < len(urls):
                    return urls[i]
            return None
        M = pd.DataFrame({'Дата': tp['day'], 'Время': tp['dt'].dt.strftime('%H:%M'), 'ТП': tp['who'],
                          'Аптека': tp['Контр-агент/Врач'], 'Результат': res,
                          'Фото с мерчем': [merch_photo(r) for _, r in tp.iterrows()],
                          'Витрина': tp['vit'], 'Касса': tp['kas'],
                          'Что увидел ИИ': tp['mcom'], 'Фото 1': tp['Фото 1'], 'Фото 2': tp['Фото 2']}).sort_values(['ТП', 'Дата'])
        table(ws, M, 1, {'ТП': 30, 'Аптека': 34, 'Результат': 24, 'Фото с мерчем': 14, 'Что увидел ИИ': 60, 'Фото 1': 10, 'Фото 2': 10})

    if len(AU):
        ws = wb.create_sheet('Аудиозаписи')
        A = allv[['id', 'day', 'dt', 'who', 'Контр-агент/Врач']].merge(AU.assign(id=AU['id'].astype(int)), on='id', how='inner')
        A = A.sort_values(['who', 'day', 'dt'])
        AA = pd.DataFrame({'Дата': A['day'], 'Время': A['dt'].dt.strftime('%H:%M'), 'Сотрудник': A['who'], 'Аптека': A['Контр-агент/Врач'],
                           'Длительность, сек': pd.to_numeric(A['dur'], errors='coerce').round(0),
                           'Тишина, %': pd.to_numeric(A['silence_pct'], errors='coerce'), 'Статус': A['status'], 'Причина': A['comment'],
                           'Что услышал ИИ': A['ai'].fillna(''), 'Запись': A['url'].fillna('')})
        table(ws, AA, 1, {'Сотрудник': 30, 'Аптека': 34, 'Статус': 16, 'Причина': 40, 'Что услышал ИИ': 70, 'Запись': 12})
        for i, st in enumerate(AA['Статус'], 2):
            if st in ('Подозрительная', 'Нет записи'):
                for j in range(1, 11):
                    ws.cell(i, j).fill = red if st == 'Нет записи' else yel
        for i in range(2, len(AA) + 2):
            ws.cell(i, 9).alignment = Alignment(wrap_text=True, vertical='top')

    ws = wb.create_sheet('Охват аптек')
    if len(C):
        # visited first (most visits on top), then not visited - the longest-abandoned at the bottom
        C = C.assign(_v=C['k'] > 0, _h=pd.to_datetime(C['h']).fillna(pd.Timestamp('1900-01-01')))
        C = C.sort_values(['emp', '_v', 'k', 'att', '_h'], ascending=[True, False, False, False, False])
        today = pd.Timestamp(dt.datetime.now(TZ).date())
        ago = [None if pd.isna(x) else int(x) for x in (today - pd.to_datetime(C['h'])).dt.days]
        V = pd.DataFrame({'Сотрудник': C['emp'], 'ID аптеки': C['id'], 'Аптека': C['name'], 'Район': C['district'],
                          'Закреплена': C['att'].map({True: 'да', False: 'нет'}), 'Визитов': C['k'], 'Последний визит': C['last'],
                          'Последний визит за 3 мес.': pd.to_datetime(C['h']),
                          'Дней назад': ago,
                          'Статус': [('нет визитов 3 мес.' if pd.isna(h) else 'не посещена в периоде') if a and k == 0
                                     else ('не закреплена' if not a else 'ок') for a, k, h in zip(C['att'], C['k'], C['h'])]})
        table(ws, V, 1, {'Сотрудник': 30, 'Аптека': 40, 'Район': 22, 'Последний визит за 3 мес.': 14, 'Статус': 22})
        for i, (a, k) in enumerate(zip(C['att'], C['k']), 2):
            f = red if a and k == 0 else yel if not a else None
            if f:
                for j in range(1, 11):
                    ws.cell(i, j).fill = f

    ws = wb.create_sheet('Пояснение')
    for i, t in enumerate([
        f"Проверка: {title}, период {d1:%d.%m.%Y} – {d2:%d.%m.%Y}.",
        "Подозрительные визиты — визиты хотя бы с одним признаком: быстро закрыт (≤1 мин), нет фото / одинаковые / повторно "
        "использованные фото, повторный визит в тот же день, вне рабочего времени, изменена локация аптеки, координата аптеки вне "
        "региона работы, 5+ аптек в одной точке, 3+ сотрудника в одной аптеке за месяц, 7+ визитов в одну аптеку, крупный план мерча. "
        "Это не доказательство обмана, а повод проверить — причина указана у каждого визита.",
        "Мерч (только ТП): Риномакс ХОТ и Форсил на ОДНОМ фото; Витрина — на витрине/полке, Касса — у кассы. "
        "Проверяет ИИ (Google Gemini), точность ≈75% — сомнительные строки проверяйте по ссылке на фото.",
        "Аудиозаписи: у каждого визита в аптеку записывается разговор. Бесплатно проверяется каждая запись: есть ли она, "
        "длительность, доля тишины. «Подозрительная» — короче 30 сек, 85%+ тишины или почти без звука. Несколько записей каждого "
        "сотрудника дополнительно прослушивает ИИ (есть ли диалог с фармацевтом, о чём разговор, какие препараты названы). "
        "Это повод послушать запись, а не доказательство.",
        "Охват: закреплённые аптеки — из базы Sales (поле «Фарм. пред» у аптеки). Красным — закреплённые, но не посещённые за период; "
        "жёлтым — посещённые, но не закреплённые за сотрудником.",
    ], 1):
        ws.cell(i, 1, t).alignment = Alignment(wrap_text=True, vertical='top')
    ws.column_dimensions['A'].width = 120
    wb.save(path)
    translate_workbook(path)          # «Причина» comes from the analysis in Uzbek -> Russian

    # ---------- Telegram summary (Uzbek)
    L = [f"🔍 <b>Текширув: {title}</b>", f"📅 {d1:%d.%m}–{d2:%d.%m.%Y} ({PERIODS[code].lower()})", ""]
    for d in S.sort_values('% подозр.', ascending=False).to_dict('records'):
        line = (f"• <b>{d['Сотрудник']}</b> ({d['Должность']}): {d['Визитов']} визит, шубҳали {d['Подозрительных']} "
                f"({d['% подозр.']}%), қамров {d['Посещено закреплённых']}/{d['Закреплено аптек']} ({d['Охват %']}%)")
        if pd.notna(d.get('Записей проверено')) and d.get('Записей проверено'):
            line += f", аудио: шубҳали {int(d.get('Подозр. записей') or 0)}, ёзувсиз {int(d.get('Без записи') or 0)}"
        if d['Должность'] == 'ТП' and pd.notna(d.get('Мерч проверено')):
            line += f", мерч: витрина {int(d.get('Витрина') or 0)}, касса {int(d.get('Касса') or 0)}"
        L.append(line)
    if len(tp):
        left = int((~tp['cat'].isin(['merch', 'none', 'suspicious', 'no_photo'])).sum())
        if left:
            why = ("бугунги бепул ИИ лимити тугади" if MERCH_INFO['quota'] else
                   f"бир сўровда кўпи билан {MERCH_CAP} та визит / {MERCH_MIN} дақиқа текширилади")
            L += ["", f"⚠️ {left} та визитнинг мерчи ҳали текширилмаган ({why}). Улар ҳар кунги ҳисобот пайтида аста-секин "
                      "текширилади; эртага шу текширувни қайта сўрасангиз, тўлиқроқ бўлади."]
    send_text("\n".join(L))
    send_file(path, f"Текширув: {title}, {d1:%d.%m}–{d2:%d.%m.%Y}")
    print(f"::notice::check done {title} {d1}..{d2} visits={len(allv)}")
