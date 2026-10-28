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

from export import fetch
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
MERCH_MIN = int(os.environ.get("MERCH_MINUTES", "80"))
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
        return mon, mon + dt.timedelta(days=6), f"Ҳафталик ҳисобот — {mon:%d.%m}–{mon + dt.timedelta(days=6):%d.%m.%Y}"
    if MODE == "monthly":
        last = today.replace(day=1) - dt.timedelta(days=1)
        return last.replace(day=1), last, f"Ойлик ҳисобот — {last:%m.%Y}"
    d1 = dt.date.fromisoformat(os.environ["FROM"]); d2 = dt.date.fromisoformat(os.environ["TO"])
    return d1, d2, f"Ҳисобот — {d1:%d.%m.%Y}–{d2:%d.%m.%Y}"


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
        model = pick_model() if len(todo) else None
    except DailyQuotaExceeded:
        print(f"::warning::merch {day}: free AI limit used up today, {len(todo)} visits left for the next run")
        todo = todo[:0]
    if len(todo):
        stop = False

        def work(r):
            if stop or time.time() - START > MERCH_MIN * 60:
                return None
            try:
                res = check_visit(model, r['Фото 1'], r['Фото 2'])
            except DailyQuotaExceeded:
                return 'QUOTA'
            except Exception as e:
                res = {"category": "error", "vitrina": 0, "kassa": 0, "raw": {"error": str(e)[:150]}}
            return {"id": r['id'], "category": res['category'], "vitrina": res['vitrina'], "kassa": res['kassa'],
                    "comment": comment(res.get('raw')), "raw": json.dumps(res.get('raw'), ensure_ascii=False)}

        with ThreadPoolExecutor(3) as ex:
            futs = [ex.submit(work, r) for _, r in todo.iterrows()]
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
try:
    locations.snapshot()          # fresh pharmacy-location snapshot so today's changes are in the log
except Exception as e:
    print(f"::warning::snapshot failed: {str(e)[:150]}")
loc_log = store.load('loc_log')
comp = store.load('companies_last')
tp_people, mp_people, seed = load_people()

if MODE in ("daily", "update"):
    f1 = d1.replace(day=1)                                   # month-to-date files
else:
    f1 = d1
_raw_tp = fetch(1, f1, d2)
tp = prepare(_raw_tp, 'ТП', loc_log)
tp = tp[~tp['Лавозим'].str.contains('Медицин')]
_raw_mp = fetch(4, f1, d2)
mp = prepare(_raw_mp, 'МП', loc_log)
try:                                   # warm the bot's visit cache (pharmacy history answers faster)
    import vcache
    if f1.day == 1:                    # only whole months from the 1st (cache assumes no gaps)
        vcache.put(_raw_tp, 'tp'); vcache.put(_raw_mp, 'mp')
except Exception as e:
    print("::warning::vcache " + str(e)[:150])
tp = enrich(tp, 'ТП', tp_people, comp, 'ТП')
mp = enrich(mp, 'МП', mp_people, comp, 'МП')
print(f"::notice::{MODE} {f1}..{d2} tp={len(tp)} mp={len(mp)}")

if MODE in ("daily", "update"):
    merch_for_day(d2, tp)
    # backlog: earlier days of the month whose visits were not checked yet (e.g. the free AI limit ran out)
    for back in sorted({x.date() for x in tp.day} - {d2}, reverse=True):
        if time.time() - START > MERCH_MIN * 60:
            break
        try:
            merch_for_day(back, tp)
        except Exception as e:
            print("::warning::backlog " + str(e)[:150]); break
merch = stored_merch(f1, d2)
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
for p, cap in files:
    translate_workbook(p)          # files are delivered in Russian
    send_file(p, cap)
if AUTO:
    _sent = store.load('sent')
    _row = pd.DataFrame({'key': [SENT_KEY]})
    store.save('sent', pd.concat([_sent, _row]).tail(400) if len(_sent) else _row)
print("::notice::telegram=sent")
if MODE == "update":                    # Аудиозаписи file: yesterday's block (6 ТП x 2 recordings)
    try:
        import az
        az.run([d2])
    except Exception as e:
        print("::warning::az " + str(e)[:200])
