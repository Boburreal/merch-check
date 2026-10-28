"""Try the audio check on a few recent visits. Public log: numbers and statuses only (no speech content)."""
import datetime as dt, random
from zoneinfo import ZoneInfo
from sales import login, switch_project
import vcache, audio
from telegram import send_text

today = dt.datetime.now(ZoneInfo("Asia/Tashkent")).date()
out = []
for grp, proj, n in (('tp', 1, 6), ('mp', 4, 3)):
    v = vcache.get(grp, today - dt.timedelta(days=3), today)
    v = v[v['Тип визита'].str.contains('аптек', case=False, na=False)]
    ids = random.Random(7).sample(list(v['#'].astype(int)), min(n, len(v)))
    s = login(); switch_project(s, proj)
    try:
        for i in ids:
            r = audio.check(s, i, use_ai=True)
            ext = r['url'].split('?')[0].rsplit('.', 1)[-1] if r['url'] else '-'
            print(f"::notice::{grp} {i} ext={ext} dur={r['dur']} silence={r['silence_pct']}% status={r['status']} ai={'yes' if r['ai'] else 'no'} products={bool(r.get('products'))}")
            out.append((grp, i, r))
    finally:
        switch_project(s, 1)
lines = ["🎧 <b>Аудио синов</b> (тасодифий визитлар)"]
for grp, i, r in out:
    lines.append(f"• {grp.upper()} визит {i}: {r['dur']:.0f} с, жимлик {r['silence_pct']}% — <b>{r['status']}</b> {r['comment']}\n  {r['ai']}")
send_text("\n".join(lines))
