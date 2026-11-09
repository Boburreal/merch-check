"""Reports -> Telegram (runs on GitHub Actions + free Gemini; Claude is not used).
MODE=daily   17:30  month-to-date ТП file (Факт визит и мерч format) + МП file (Итог format); merch checked for today
MODE=update  08:30  same files again for yesterday (late visits added, their merch checked)
MODE=weekly  Sun 23:00  separate full analysis of the week (ТП and МП)
MODE=monthly 1st 09:00  separate analysis of last month - only employees with suspicious cases
MODE=range   FROM..TO   manual analysis file"""
import datetime as dt, json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import pandas as pd
import sys as _sys, traceback as _tb


def _hook(t, v, tb):                     # errors are visible in the run annotations (logs are not readable)
    print("::error::" + "".join(_tb.format_exception(t, v, tb))[-900:].replace(chr(10), " | "))
    _sys.__excepthook__(t, v, tb)


_sys.excepthook = _hook

from analysis import prepare
from merch import check_visit, pick_model, comment, DailyQuotaExceeded, STATS
import store
import locations
from xlsx_report import build
import roster as R
from checks import enrich, remember
import tp_file, mp_file
from ru import translate_workbook
from telegram import send_text, send_file

TZ = ZoneInfo("Asia/Tashkent")
MODE = os.environ.get("MODE", "daily")
MERCH_MIN = int(os.environ.get("MERCH_MINUTES", "25"))   # today's visits before the report is sent
ACC = ("Мерч бепул Google Gemini (Flash-Lite) ИИ билан текширилади. Синовда 30 визитдан 22–23 тасида "
       "сизнинг баҳойингиз билан мос келди (≈75%). Шубҳали қаторларни фото линки орқали текширинг.")
now = dt.datetime.now(TZ)
START = time.time()            # one merch time budget for the whole run (today + backlog)
today = dt.date.fromisoformat(os.environ['TODAY']) if os.environ.get('TODAY') else now.date()
# scheduled runs come from two clocks (Cloudflare Worker on time + GitHub schedule as backup): send only once
AUTO = os.environ.get('AUTO') == '1'
SENT_KEY = f"{MODE}:{today.isoformat()}"
if AUTO:
    _sent = store.load('sent')
    if len(_sent) and SENT_KEY in set(_sent['key']):
        print(f"::notice::{SENT_KEY} already sent - skipped")
        raise SystemExit(0)


def period():
    if MODE == "daily":
        return today, today, f"Кунлик ҳисобот — {today:%d.%m.%Y} (соат {now:%H:%M} ҳолатига)"
    if MODE == "update":
        y = today - dt.timedelta(days=1)
        return y, y, f"Кечаги визитлар (янгиланган) — {y:%d.%m.%Y}"
    if MODE == "weekly":
        mon = today - dt.timedelta(days=today.weekday())   # runs on Sunday evening: this Mon..Sun
        if today.weekday() != 6:                            # started late (Monday or later): the last full week
            mon -= dt.timedelta(days=7)
        return mon, mon + dt.timedelta(days=6), f"Ҳафталик ҳисобот — {mon:%d.%m}–{mon + dt.timedelta(days=6):%d.%m.%Y}"
    if MODE == "monthly":
        last = today.replace(day=1) - dt.timedelta(days=1)
        return last.replace(day=1), last, f"Ойлик ҳисобот — {last:%m.%Y}"
    d1 = dt.date.fromisoformat(os.environ["FROM"]); d2 = dt.date.fromisoformat(os.environ["TO"])   # range / merch
    return d1, d2, f"Ҳисобот — {d1:%d.%m.%Y}–{d2:%d.%m.%Y}"


def alive_models():
    """Up to 4 free Gemini models that still have quota today (raises DailyQuotaExceeded if none)."""
    import merch as M
    first = pick_model()
    rest = [m for m in M._CHAIN if m not in M._DEAD and m != first]
    return [first] + rest[:7]


def merch_for_day(day: dt.date, tp: pd.DataFrame) -> pd.DataFrame:
    """Load stored results for the day and check visits that are not checked yet."""
    name = f"m_{day.isoformat()}"
    old = store.load(name)
    done = set(old['id'].astype(int)) if len(old) else set()
    if len(old):
        old = old[old['category'] != 'error']
        done = set(old['id'].astype(int))
    todo = tp[(tp.day.dt.date == day) & ~tp.id.isin(done) & tp['Лавозим'].str.contains('Торг')]
    rows, t0 = [], time.time()
    try:
        models = alive_models() if len(todo) else []
    except DailyQuotaExceeded:
        print(f"::warning::merch {day}: free AI limit used up today, {len(todo)} visits left for the next run")
        todo = todo[:0]
    if len(todo):
        stop = False
        nthreads = min(12, 3 * max(1, len(models)))       # each free model has its own per-minute limit

        def work(arg):
            i, r = arg
            if stop or time.time() - START > MERCH_MIN * 60:
                return None
            try:
                res = check_visit(models[i % len(models)], r['Фото 1'], r['Фото 2'])
            except DailyQuotaExceeded:
                return 'QUOTA'
            except Exception as e:
                res = {"category": "error", "vitrina": 0, "kassa": 0, "raw": {"error": str(e)[:150]}}
            return {"id": r['id'], "category": res['category'], "vitrina": res['vitrina'], "kassa": res['kassa'],
                    "comment": comment(res.get('raw')), "raw": json.dumps(res.get('raw'), ensure_ascii=False)}

        with ThreadPoolExecutor(nthreads) as ex:
            futs = [ex.submit(work, (i, r)) for i, (_, r) in enumerate(todo.iterrows())]
            for f in as_completed(futs):
                x = f.result()
                if x == 'QUOTA':
                    stop = True
                elif x:
                    rows.append(x)
        print(f"::notice::merch {day}: todo={len(todo)} checked={len(rows)} stats={STATS} quota_stop={stop}")
    new = pd.DataFrame(rows)
    allm = pd.concat([old, new], ignore_index=True) if len(old) else new
    if len(allm):
        allm['id'] = allm['id'].astype(int)
        allm = allm.drop_duplicates('id', keep='last')
        store.save(name, allm)
    return allm


def stored_merch(d1, d2):
    parts = [store.load(f"m_{(d1 + dt.timedelta(days=i)).isoformat()}") for i in range((d2 - d1).days + 1)]
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.DataFrame(columns=['id', 'category', 'vitrina', 'kassa', 'comment'])
    m = pd.concat(parts, ignore_index=True)
    m['id'] = m['id'].astype(int)
    return m


def merch_summary(tp, merch):
    """Aggregate merch stats only (no personal data in public logs)."""
    if not len(merch):
        return
    m = tp[['id']].merge(merch, on='id', how='inner')
    num = lambda c: pd.to_numeric(m[c], errors='coerce').fillna(0)   # same counting as tp_file
    print(f"::notice::merch summary: tp_visits={len(tp)} checked={len(m)} cats={m['category'].value_counts().to_dict()} "
          f"vitrina={int(num('vitrina').sum())} kassa={int(num('kassa').sum())}")


MON = {1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
       9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'}


def load_people():
    try:
        r = R.load()
        return r['tp'], r['mp'], r.get('seed_merch')
    except Exception as e:
        print(f"::warning::roster not available ({str(e)[:80]}) - everyone treated as new, plan 15")
        empty = pd.DataFrame(columns=['name', 'region', 'plan', 'key'])
        return empty, empty, None


d1, d2, title = period()
if MODE == "update":                # pharmacy coordinates (for "7+ pharmacies at one point") - once a day, in the morning
    try:
        locations.snapshot()
    except Exception as e:
        print(f"::warning::snapshot failed: {str(e)[:150]}")
loc_log = pd.DataFrame()             # Bobur 06.11: location-change checks are not needed
comp = store.load('companies_last')
tp_people, mp_people, seed = load_people()

if MODE in ("daily", "update"):
    f1 = d1.replace(day=1)                                   # month-to-date files
else:
    f1 = d1
import vcache                            # cached month-to-date: finished months once, current month topped up daily
tp = prepare(vcache.get('tp', f1, d2), 'ТП', loc_log)
tp = tp[~tp['Лавозим'].str.contains('Медицин')]
mp = prepare(vcache.get('mp', f1, d2), 'МП', loc_log)
tp = enrich(tp, 'ТП', tp_people, comp, 'ТП')
mp = enrich(mp, 'МП', mp_people, comp, 'МП')
print(f"::notice::{MODE} {f1}..{d2} tp={len(tp)} mp={len(mp)}")
if MODE == "recheck":                   # re-check visits where only the counter (no vitrina) was seen
    import merch as _M
    models = alive_models()
    n = fixed = 0
    for day in sorted({x.date() for x in tp.day}):
        m = store.load(f"m_{day.isoformat()}")
        if not len(m):
            continue
        m['id'] = m['id'].astype(int)
        if 'pv' not in m:
            m['pv'] = ''
        vv = pd.to_numeric(m['vitrina'], errors='coerce').fillna(0)
        kk = pd.to_numeric(m['kassa'], errors='coerce').fillna(0)
        done2 = m['pv'].astype(str).eq('2') if 'pv' in m else pd.Series(False, index=m.index)
        # only one place found (Витрина without Касса or Касса without Витрина) -> may be mixed up; check again once
        ids = set(m[(m['category'] == 'merch') & ((vv == 0) | (kk == 0)) & ~done2]['id'])
        part = tp[tp.id.isin(ids)]
        for i, (_, r) in enumerate(part.iterrows()):
            try:
                res = check_visit(models[i % len(models)], r['Фото 1'], r['Фото 2'])
            except Exception as e:
                print("::warning::recheck " + str(e)[:100]); continue
            n += 1
            if res['category'] != 'error':
                k = m['id'] == r['id']
                old_v, old_k = int(float(m.loc[k, 'vitrina'].iloc[0] or 0)), int(float(m.loc[k, 'kassa'].iloc[0] or 0))
                if (int(res['vitrina']), int(res['kassa'])) != (old_v, old_k):
                    fixed += 1
                m.loc[k, ['category', 'vitrina', 'kassa', 'comment', 'raw', 'pv']] = [str(res['category']), str(res['vitrina']), str(res['kassa']),
                                                                                    comment(res.get('raw')), json.dumps(res.get('raw'), ensure_ascii=False), '2']
        store.save(f"m_{day.isoformat()}", m)
    print(f"::notice::recheck {d1}..{d2}: rechecked={n} changed={fixed}")
    raise SystemExit(0)
if MODE == "merch":                     # only check merch photos of earlier days (no report)
    START = time.time(); MERCH_MIN = int(os.environ.get("BACKLOG_MINUTES", "300"))
    for back in sorted({x.date() for x in tp.day}, reverse=True):
        if time.time() - START > MERCH_MIN * 60:
            break
        merch_for_day(back, tp)
    merch_summary(tp, stored_merch(f1, d2))
    raise SystemExit(0)
if MODE in ("daily", "update") and not len(tp[tp.day.dt.date == d2]) and not len(mp[mp.day.dt.date == d2]):
    send_text(f"📊 <b>{title}</b>\nБу кунда ТП ва МП визитлари йўқ (дам олиш куни бўлса керак).")
    print("::notice::no visits - message sent")
    raise SystemExit(0)

if MODE in ("daily", "update"):
    START = time.time()                 # the merch budget starts now (export/snapshot time does not count)
    if MODE == "daily" and AUTO:        # Bobur wants the evening file by 17:45-17:55: stop checking merch at 17:47
        left = (dt.datetime.combine(now.date(), dt.time(17, 47), TZ) - dt.datetime.now(TZ)).total_seconds() / 60
        MERCH_MIN = max(12, min(MERCH_MIN, int(left)))   # started late: still check merch, a file without it is useless
        print(f"::notice::merch budget {MERCH_MIN} min (deadline 17:47)")
    merch_for_day(d2, tp)
merch = stored_merch(f1, d2)
merch_summary(tp, merch)
m = tp[['id']].merge(merch, on='id', how='left') if len(merch) else tp[['id']].assign(category=None)
tp['f_closeup'] = m['category'].eq('suspicious').values
tp.loc[tp['f_closeup'], 'Шубҳали'] = True
tp.loc[tp['f_closeup'], 'Изоҳ'] = (tp.loc[tp['f_closeup'], 'Изоҳ'] + '; Мерч фотоси яқин пландан (аптека кўринмайди)').str.strip('; ')
tp = remember(tp, 'ТП', 'tp')
mp = remember(mp, 'МП', 'mp')

loc_changes = pd.DataFrame()
if len(loc_log):
    w = pd.to_datetime(loc_log['Аниқланди'], format='%d.%m.%Y %H:%M', errors='coerce').dt.date
    loc_changes = loc_log[(w >= f1) & (w <= d2)]

pct = lambda a, b: f"{a / b * 100:.0f}%" if b else "—"
files = []
if MODE in ("daily", "update"):
    mname = f"{MON[d2.month]} {d2.year}"
    p1 = f"/tmp/Факт визит и мерч {MON[d2.month]} (01-{d2:%d.%m.%Y}).xlsx"
    days, tpx = tp_file.build(p1, f"Факт визит ва мерч — {mname} (01–{d2:%d.%m.%Y})", tp, merch, seed, tp_people, loc_changes)
    p2 = f"/tmp/МП визит 01-{d2:%d.%m.%y}.xlsx"
    mp_file.build(p2, f"МП визит — {mname} (01–{d2:%d.%m.%Y})", mp, mp_people)
    files = [(p1, "ТП: " + title), (p2, "МП: " + title)]
    dd = days[days.day.dt.date == d2]
    td = tpx[tpx.day.dt.date == d2]
    md = mp[mp.day.dt.date == d2]
    chk = td['cat'].isin(['merch', 'none', 'suspicious']).sum()
    msg = [f"📊 <b>{title}</b>", "",
           f"<b>ТП</b>: {dd['ТП'].nunique()} киши ишлади. План {int(dd['План'].sum())} → факт {int(dd['Факт'].sum())} ({pct(dd['Факт'].sum(), dd['План'].sum())})",
           f"🛒 Витрина {int(dd['Витрина'].sum())} ({pct(dd['Витрина'].sum(), dd['План'].sum())}), Касса {int(dd['Касса'].sum())} ({pct(dd['Касса'].sum(), dd['План'].sum())})"
           + (f" — {len(td) - chk} та визит ҳали текширилмади" if chk < len(td) else ""),
           f"⚠️ Шубҳали визит: {int(td['Шубҳали'].sum())} ({pct(td['Шубҳали'].sum(), len(td))})", "",
           f"<b>МП</b>: {md['МП'].nunique()} киши, {len(md)} визит (аптека {int(md['Тип визита'].str.contains('аптек', case=False).sum())}, "
           f"доктор {int(md['Тип визита'].str.contains('врач', case=False).sum())}), шубҳали {int(md['Шубҳали'].sum())}"]
    new_tp = sorted(td.loc[td['Янги'], 'ТП'].unique()); new_mp = sorted(md.loc[md['Янги'], 'МП'].unique())
    if new_tp or new_mp:
        msg += ["", "🆕 Янги ходим: " + ", ".join(new_tp + new_mp)]
    lc = loc_changes[pd.to_datetime(loc_changes['Аниқланди'], format='%d.%m.%Y %H:%M', errors='coerce').dt.date == d2] if len(loc_changes) else loc_changes
    if len(lc):
        msg += ["", "📍 Бугун аптека локацияси ўзгарди: " + ", ".join(f"{k} {v}" for k, v in lc['Ўзгариш'].value_counts().items())]
    if len(td):
        top = td.groupby('ТП')['Шубҳали'].mean().sort_values(ascending=False).head(3)
        msg += ["", "Шубҳали улуши энг юқори ТП:"] + [f"• {k}: {v * 100:.0f}%" for k, v in top.items() if v > 0]
elif MODE == "weekly":              # same Excel format as the daily files (Факт визит и мерч + МП визит), for the whole week
    wk = f"{d1:%d.%m}-{d2:%d.%m.%Y}"
    p1 = f"/tmp/Факт визит и мерч неделя ({wk}).xlsx"
    days, tpx = tp_file.build(p1, f"Факт визит ва мерч — ҳафта ({wk})", tp, merch, seed, tp_people, loc_changes,
                              period_label=wk)
    p2 = f"/tmp/МП визит неделя ({wk}).xlsx"
    mp_file.build(p2, f"МП визит — ҳафта ({wk})", mp, mp_people)
    files = [(p1, "ТП: " + title), (p2, "МП: " + title)]
    plan, fact = int(days['План'].sum()), int(days['Факт'].sum())
    vit, kas = int(days['Витрина'].sum()), int(days['Касса'].sum())
    tp_uniq = int(tp.drop_duplicates('Контр-агент/Врач').shape[0])
    mtype = mp['Тип визита'].fillna('').str.lower()
    mp_doc, mp_ph = mp[mtype.str.contains('врач')], mp[~mtype.str.contains('врач')]
    uq = lambda d: len(d.drop_duplicates('Контр-агент/Врач'))
    short = ["ТП", f"Факт визит {fact}", f"Уникальный {tp_uniq}", "",
             "МП Контрагент", f"Факт визит {len(mp_ph)}", f"Уникальный {uq(mp_ph)}", "",
             "МП Врач", f"Факт визит {len(mp_doc)}", f"Уникальный {uq(mp_doc)}"]
    msg = [f"📊 <b>{title}</b>", "",
           f"<b>ТП</b>: {tp['ТП'].nunique()} киши ишлади. План {plan} → факт визит {fact} ({pct(fact, plan)})",
           f"Уникальный: <b>{tp_uniq}</b>",
           f"🛒 Витрина {vit} ({pct(vit, plan)}), Касса {kas} ({pct(kas, plan)})",
           f"⚠️ Шубҳали визит: {int(tp['Шубҳали'].sum())} ({pct(tp['Шубҳали'].sum(), len(tp))})", "",
           f"<b>МП</b>: {mp['МП'].nunique()} киши, жами {len(mp)} визит, шубҳали {int(mp['Шубҳали'].sum())}",
           f"🏥 Аптека: визит {len(mp_ph)}, уникальный {uq(mp_ph)}",
           f"👨‍⚕️ Врач: визит {len(mp_doc)}, уникальный {uq(mp_doc)}"]
    top = tp.groupby('ТП')['Шубҳали'].mean().sort_values(ascending=False).head(5)
    msg += ["", "Шубҳали улуши энг юқори ТП:"] + [f"• {k}: {v * 100:.0f}%" for k, v in top.items() if v > 0]
else:
    if MODE == "monthly":
        bad_tp = tp.groupby('ТП')['Шубҳали'].sum(); bad_tp = bad_tp[bad_tp > 0].index
        bad_mp = mp.groupby('МП')['Шубҳали'].sum(); bad_mp = bad_mp[bad_mp > 0].index
        tp_r, mp_r = tp[tp['ТП'].isin(bad_tp)], mp[mp['МП'].isin(bad_mp)]
        note = "Фақат шубҳали ҳолати бўлган ходимлар. "
    else:
        tp_r, mp_r, note = tp, mp, ""
    p1 = f"/tmp/ТП анализ {d1:%d.%m}-{d2:%d.%m.%Y}.xlsx"
    build(p1, f"ТП — {title}", tp_r, None, merch if len(merch) else None, note + ACC, loc_changes, None)
    p2 = f"/tmp/МП анализ {d1:%d.%m}-{d2:%d.%m.%Y}.xlsx"
    build(p2, f"МП — {title}", mp_r.iloc[0:0], mp_r, None, note, loc_changes, None)
    files = [(p1, "ТП: " + title), (p2, "МП: " + title)]
    chk = tp[['id']].merge(merch, on='id', how='inner')['category'].isin(['merch', 'none', 'suspicious']).sum() if len(merch) else 0
    msg = [f"📊 <b>{title}</b>", "",
           f"<b>ТП</b>: {len(tp)} визит, {tp['ТП'].nunique()} киши, шубҳали {int(tp['Шубҳали'].sum())} ({pct(tp['Шубҳали'].sum(), len(tp))}), мерч текширилди {chk}",
           f"<b>МП</b>: {len(mp)} визит, {mp['МП'].nunique()} киши, шубҳали {int(mp['Шубҳали'].sum())} ({pct(mp['Шубҳали'].sum(), len(mp))})"]
    if MODE == "monthly":
        msg += [f"Шубҳали ҳолати бор: ТП {len(bad_tp)} киши, МП {len(bad_mp)} киши"]
    top = tp.groupby('ТП')['Шубҳали'].mean().sort_values(ascending=False).head(5)
    msg += ["", "Шубҳали улуши энг юқори ТП:"] + [f"• {k}: {v * 100:.0f}%" for k, v in top.items() if v > 0]

send_text("\n".join(msg))
if MODE == "weekly":              # short copy-paste text, separate message
    send_text("\n".join(short))
if os.environ.get('ONLY_TP'):
    files = files[:1]
if os.environ.get('ONLY_MP'):
    files = files[1:]
for p, cap in files:
    translate_workbook(p)          # files are delivered in Russian
    send_file(p, cap)
if AUTO:
    _sent = store.load('sent')
    _row = pd.DataFrame({'key': [SENT_KEY]})
    store.save('sent', pd.concat([_sent, _row]).tail(400) if len(_sent) else _row)
print("::notice::telegram=sent")
if MODE in ("daily", "update"):         # Аудиозаписи: the day's block (daily adds today's, update refills / adds yesterday's)                    # Аудиозаписи file: yesterday's block (6 ТП x 2 recordings)
    try:
        import az
        az.run([d2])
    except Exception as e:
        print("::warning::az " + str(e)[:200])
if MODE in ("daily", "update") and not os.environ.get('NO_BACKLOG'):
    # after the report is delivered: earlier days of the month not checked yet (free AI limit permitting)
    BACK_MIN = int(os.environ.get("BACKLOG_MINUTES", "15"))
    START = time.time(); MERCH_MIN = BACK_MIN
    for back in sorted({x.date() for x in tp.day} - {d2}, reverse=True):
        if time.time() - START > MERCH_MIN * 60:
            break
        try:
            merch_for_day(back, tp)
        except Exception as e:
            print("::warning::backlog " + str(e)[:150]); break
