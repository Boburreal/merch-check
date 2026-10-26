"""Daily / update / weekly / monthly / yearly report -> Telegram.
MODE=daily   (17:30) today, check merch for all today's ТП visits
MODE=update  (08:30) yesterday again (late visits), check merch only for new visits
MODE=weekly  last Mon..Sun, merch from stored results
MODE=monthly previous month, merch from stored results
MODE=range   FROM..TO (manual)"""
import datetime as dt, json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import pandas as pd

from export import fetch
from analysis import prepare
from merch import check_visit, pick_model, comment, DailyQuotaExceeded, STATS
import store
from xlsx_report import build
from telegram import send_text, send_file

TZ = ZoneInfo("Asia/Tashkent")
MODE = os.environ.get("MODE", "daily")
MERCH_MIN = int(os.environ.get("MERCH_MINUTES", "80"))
ACC = ("Мерч бепул Google Gemini (Flash-Lite) ИИ билан текширилади. Синовда 30 визитдан 22–23 тасида "
       "сизнинг баҳойингиз билан мос келди (≈75%). Шубҳали қаторларни фото линки орқали текширинг.")
now = dt.datetime.now(TZ)
today = now.date()


def period():
    if MODE == "daily":
        return today, today, f"Кунлик ҳисобот — {today:%d.%m.%Y} (соат {now:%H:%M} ҳолатига)"
    if MODE == "update":
        y = today - dt.timedelta(days=1)
        return y, y, f"Кечаги визитлар (янгиланган) — {y:%d.%m.%Y}"
    if MODE == "weekly":
        mon = today - dt.timedelta(days=today.weekday() + 7)
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
    if len(todo):
        model = pick_model()
        stop = False

        def work(r):
            if stop or time.time() - t0 > MERCH_MIN * 60:
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


d1, d2, title = period()
tp = prepare(fetch(1, d1, d2), 'ТП')
tp = tp[~tp['Лавозим'].str.contains('Медицин')]
mp = prepare(fetch(4, d1, d2), 'МП')
print(f"::notice::{MODE} {d1}..{d2} tp={len(tp)} mp={len(mp)} tp_roles={tp['Лавозим'].value_counts().to_dict()} mp_roles={mp['Лавозим'].value_counts().to_dict() if len(mp) else {}}")

if MODE in ("daily", "update"):
    merch = merch_for_day(d1, tp)
else:
    merch = stored_merch(d1, d2)

path = f"/tmp/{title.split(' — ')[0].replace(' ', '_')}_{d1:%d.%m}-{d2:%d.%m.%Y}.xlsx"
build(path, title, tp, mp, merch if len(merch) else None, ACC)

# ---- Telegram summary ----
tpm = tp[tp['Лавозим'].str.contains('Торг')]
m = tpm[['id']].merge(merch, on='id', how='left') if len(merch) else tpm[['id']].assign(category=None)
chk = m['category'].isin(['merch', 'none', 'suspicious']).sum()
mb = (m['category'] == 'merch').sum()
vit = pd.to_numeric(m.get('vitrina'), errors='coerce').fillna(0).sum() if len(merch) else 0
kas = pd.to_numeric(m.get('kassa'), errors='coerce').fillna(0).sum() if len(merch) else 0
sus = (m['category'] == 'suspicious').sum()
pct = lambda a, b: f"{a / b * 100:.0f}%" if b else "—"
msg = [f"📊 <b>{title}</b>", "",
       f"<b>ТП</b>: {len(tp)} визит, {tp['ТП'].nunique()} ходим, уникальный объект {tp.obj.nunique()}",
       f"⚠️ Шубҳали визит: {int(tp['Шубҳали'].sum())} ({pct(tp['Шубҳали'].sum(), len(tp))})",
       f"🛒 Мерч: текширилди {chk}/{len(tpm)} → бор {mb} ({pct(mb, chk)}), Витрина {int(vit)}, Касса {int(kas)}, яқин план {sus}"]
if chk < len(tpm):
    msg.append(f"   ⏳ {len(tpm) - chk} та визит ҳали текширилмади (кейинги ишга туширишда текширилади)")
msg += ["", f"<b>МП</b>: {len(mp)} визит, {mp['МП'].nunique() if len(mp) else 0} ходим",
        f"⚠️ Шубҳали визит: {int(mp['Шубҳали'].sum()) if len(mp) else 0} ({pct(mp['Шубҳали'].sum() if len(mp) else 0, len(mp))})"]
if len(tp):
    top = tp.groupby('ТП')['Шубҳали'].mean().sort_values(ascending=False).head(3)
    msg += ["", "Шубҳали улуши энг юқори ТП:"] + [f"• {k}: {v * 100:.0f}%" for k, v in top.items()]
send_text("\n".join(msg))
send_file(path, title)
print("::notice::telegram=sent")
