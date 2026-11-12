"""Bobur's daily «Аудиозаписи (<Месяц>-26)» file, filled automatically.
Every day: 6 ТП from different regions (not checked yet this month), 2 pharmacy visits each;
Аптека, Длительность записи, Комментария (AI listened, in Bobur's wording) and Ссылка are filled.
Newest day on top, same layout and styles as his file. The file lives encrypted in the store (az_file)."""
import copy, datetime as dt, io, random, re, tempfile
from zoneinfo import ZoneInfo
import pandas as pd
from openpyxl import load_workbook

import store
import audio
from sales import BASE

TZ = ZoneInfo("Asia/Tashkent")
PER_DAY, PER_TP = 6, 2
STORE = {'tp': 'az_file', 'mp': 'az_file_mp'}
LABEL = {'tp': 'ТП', 'mp': 'МП'}
FULL2SHORT = {'Бухарская': 'Бухара', 'Джизакская': 'Джизак', 'Навоийская': 'Наваи', 'Р.Каракалпакстан': 'Нукус',
              'Самаркандская': 'Самарканд', 'Сурхандарьинская': 'Термез', 'Наманганская': 'Наманган', 'Хорезмская': 'Ургенч',
              'Ферганская': 'Фергана', 'Коканд': 'Коканд', 'Кашкадарьинская': 'Карши', 'Андижанская': 'Андижан',
              'Сырдарьинская': 'Сырдарья', 'Ташкентская': 'Таш обл'}   # МП: all regions except the city of Ташкент
SHORT = {'бух': 'Бухара', 'джиз': 'Джизак', 'дж': 'Джизак', 'нав': 'Наваи', 'нук': 'Нукус', 'сам': 'Самарканд',
         'тер.в': 'Термез', 'тер.з': 'Термез', 'тер': 'Термез', 'нам': 'Наманган', 'ург': 'Ургенч', 'фер': 'Фергана',
         'кок': 'Коканд', 'кар': 'Карши'}            # Bobur's file covers these regions only (no Ташкент)
MON = {1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
       9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'}

PROMPT = """This is an audio recording made by a pharmaceutical sales representative (ТП) during a visit to a pharmacy in
Uzbekistan (Uzbek, Russian or Tajik speech; often street or shop noise). Our products: Риномакс, Форсил, Риноксил,
Мирамистин, Эрегра, Тивомакс, Триомакс, Альцетро, Авирол.
Step 1 - listen to the WHOLE recording and write a faithful short transcript with speaker turns R: (rep) and P: (pharmacist/other),
[...] for unclear parts, "[no speech]" only if nobody talks. Do NOT invent words.
Step 2 - ONLY from that transcript write the manager's check comment in Uzbek Cyrillic: say WHAT THE CONVERSATION WAS ABOUT,
short and concrete (1-2 sentences), for example:
- which of our products were named and what was said about them ("Риномакс ва Форсил ҳақида гапирилди, Форсил тугаган"),
- stock / remains asked ("Остатка олинди: Форсил 13 та, Риноксил 25 та"), sales discussed ("Товарлар сотилиши таҳлил қилинди"),
- an order or promotion / акция / бонус discussed ("Акция ҳақида гапирилди (5+1)", "Заявка олинди"), merchandising ("Мерч ҳақида гапирилди"),
- if the talk is NOT about our work, name its topic: "Иш ҳақида эмас: шахсий суҳбат (оила, соғлиқ ҳақида)", "Иш ҳақида эмас: бошқа мижоз билан савдо",
- "Маълумот йўқ (овоз йўқ / фақат шовқин)" when nobody talks or nothing can be understood.
Write only what is really heard; never guess.
Rules: the comment may name a product ONLY if that product is audible in your transcript; "Маълумот йўқ" ONLY if the transcript is "[no speech]".
Return ONLY JSON {"transcript": "...", "comment": "...", "speech_seconds": number}"""


STEMS = {'Риномакс': ('rinomaks', 'rinomax', 'риномакс', 'риномакс'), 'Форсил': ('forsil', 'fortsil', 'форсил', 'форцил'),
         'Риноксил': ('rinoksil', 'rinoxil', 'риноксил'), 'Мирамистин': ('miramistin', 'мирамистин'),
         'Эрегра': ('eregra', 'эрегра'), 'Тивомакс': ('tivomaks', 'tivomax', 'тивомакс'),
         'Триомакс': ('triomaks', 'triomax', 'триомакс'), 'Альцетро': ('altsetro', 'alcetro', 'альцетро', 'алцетро'),
         'Авирол': ('avirol', 'авирол')}
NOSPEECH = 'Маълумот йўқ (овоз йўқ / фақат шовқин)'
UNSURE = 'Текширилмади (ИИ келишмади)'


def _words(t):
    t = re.sub(r'\[[^\]]*\]', ' ', str(t or ''))
    t = re.sub(r'\b[RP]:', ' ', t)
    return re.findall(r'\w+', t.lower())


def speechless(a):
    w = _words(a.get('transcript'))
    return len(w) < 4 or (a.get('speech_seconds') is not None and float(a.get('speech_seconds') or 0) < 3 and len(w) < 10)


def repetitive(a):
    from collections import Counter
    w = _words(a.get('transcript'))
    return len(w) >= 12 and Counter(w).most_common(1)[0][1] / len(w) > 0.35


def judge(answers):
    """Comment for one recording from up to two independent model answers.
    'no data' only when TWO different models both heard no speech; a product is named only if it is in the transcript."""
    if not answers:
        return 'Текширилмади (ИИ лимити)'
    good = [a for a in answers if not speechless(a) and not repetitive(a)]
    silent = [a for a in answers if speechless(a)]
    if not good:
        if len(silent) == len(answers) and len(answers) >= 2:
            return NOSPEECH
        return UNSURE if len(answers) >= 2 else 'Текширилмади (ИИ лимити)'
    best = max(good, key=lambda a: len(_words(a.get('transcript'))))
    tr = ' '.join(str(x.get('transcript') or '') for x in good).lower()
    com = str(best.get('comment') or '').strip()
    if com.startswith('Маълумот йўқ'):
        com = 'Суҳбат бўлган, лекин аниқ мавзуси эшитилмади'
    for prod, stems in STEMS.items():
        if prod.lower() in com.lower() and not any(st in tr for st in stems):
            return 'Суҳбат бўлган, лекин компания маҳсулотлари аниқ эшитилмади'
    return com


def short_region(name: str):
    m = re.match(r'^\(([^)]*)\)', str(name).strip())
    return SHORT.get(m.group(1).strip().lower()) if m else None


def load_file(grp='tp'):
    data = store.load_bytes(STORE[grp])
    if not data and grp == 'tp':             # first run: Bobur's file, encrypted with the roster key
        import os, roster as R
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'az_base.enc')
        data = R._fernet().decrypt(open(p, 'rb').read()) if os.path.exists(p) else None
    if not data and grp == 'mp':             # МП file starts from the ТП file's layout (styles), without its rows
        base = load_file('tp')
        if base is None:
            return None
        ws = base.active
        heads = [r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == 'Менеджер']
        if len(heads) > 1:
            ws.delete_rows(heads[1], ws.max_row - heads[1] + 1)
        base._az_tmpl = ws.max_row               # the one left block is only a style template, removed after the first write
        return base
    return load_workbook(io.BytesIO(data)) if data else None


def save_file(wb, grp='tp'):
    b = io.BytesIO(); wb.save(b)
    store.save_bytes(STORE[grp], b.getvalue())


def blocks(ws):
    """[(day 'dd.mm', [manager names])] from the file, newest first."""
    out, cur = [], None
    for r in ws.iter_rows(min_row=1, max_col=2):
        if r[1].value == 'Менеджер':
            cur = (str(r[0].value).strip(), []); out.append(cur)
        elif cur and r[1].value:
            cur[1].append(str(r[1].value).strip())
    return out


def _relink(ws):
    """openpyxl does not move hyperlinks when rows move: rebuild them from the link texts in column H."""
    ws._hyperlinks = []
    for row in ws.iter_rows(min_col=8, max_col=8):
        c = row[0]
        if isinstance(c.value, str) and c.value.startswith('http'):
            c.hyperlink = c.value


def prune(ws, month: int) -> int:
    """Keep only the day blocks of `month` (each month is a separate file). Returns removed blocks."""
    heads = [r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == 'Менеджер']
    if not heads:
        return 0
    ranges = []
    for i, h in enumerate(heads):
        end = (heads[i + 1] - 1) if i + 1 < len(heads) else ws.max_row
        try:
            m = int(str(ws.cell(h, 1).value).strip()[3:5])
        except Exception:
            continue
        if m != month:
            ranges.append((h, end))
    if len(ranges) == len(heads):            # never leave the file without a block (styles are copied from it)
        ranges = ranges[1:]
    for a, b in sorted(ranges, reverse=True):
        ws.delete_rows(a, b - a + 1)
    _relink(ws)
    return len(ranges)


def drop_day(ws, dd: str) -> bool:
    """Remove the block of day 'dd.mm' (manual redo); never removes the last remaining block."""
    heads = [r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == 'Менеджер']
    if len(heads) < 2:
        return False
    for i, h in enumerate(heads):
        if str(ws.cell(h, 1).value).strip() == dd:
            end = (heads[i + 1] - 1) if i + 1 < len(heads) else ws.max_row
            ws.delete_rows(h, end - h + 1); _relink(ws)
            return True
    return False


def key(name):
    import roster as R
    return R.key(name)


def pick(day: dt.date, visits: pd.DataFrame, checked: set, last_seen: dict, seed: int, grp='tp', regions=None):
    """6 people from different regions who visited pharmacies that day; first those not checked this month.
    ТП: region from the name prefix '(ург)'; МП: region from the roster (full name -> short)."""
    rnd = random.Random(seed)
    v = visits[visits['day'].dt.date == day].copy()
    v['who'] = v['Фарм. пред'].str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip()
    if grp == 'tp':
        v = v[v['Фарм. пред'].str.contains('Торг', na=False)]
        v['reg'] = v['who'].map(short_region)
    else:
        v['reg'] = v['who'].map(lambda w: FULL2SHORT.get((regions or {}).get(key(w))))
    v = v[v['reg'].notna()]
    import os as _os
    _rg = (_os.environ.get('AZ_REGION') or '').strip().lower()
    if _rg:                                   # manual run for one region only
        v = v[v['reg'].str.lower().str.startswith(_rg[:5])]
    cnt = v.groupby('who').size()
    people = [w for w in cnt.index if cnt[w] >= PER_TP]
    fresh = [w for w in people if key(w) not in checked]
    old = sorted([w for w in people if key(w) in checked], key=lambda w: last_seen.get(key(w), ''))
    rnd.shuffle(fresh)
    chosen, regs = [], []
    for pool in (fresh, old):                 # different regions first, then fill up
        for w in pool:
            r = v[v.who == w]['reg'].iloc[0]
            if len(chosen) < PER_DAY and w not in chosen and r not in regs:
                chosen.append(w); regs.append(r)
    for pool in (fresh, old):
        for w in pool:
            if len(chosen) < PER_DAY and w not in chosen:
                chosen.append(w)
    rows = []
    for w in sorted(chosen, key=lambda x: (v[v.who == x]['reg'].iloc[0], x)):
        vv = v[v.who == w]
        ids = rnd.sample(list(vv['#'].astype(int)), PER_TP)
        for i in sorted(ids):
            r = vv[vv['#'].astype(int) == i].iloc[0]
            rows.append({'who': w, 'reg': r['reg'], 'id': i, 'src': int(r['src']) if 'src' in r and pd.notna(r['src']) else (1 if grp == 'tp' else 4),
                         'obj': re.sub(r'\s*\([^()]*\)\s*$', '', str(r['Контр-агент/Врач'])).strip()})
    return rows


def listen(s, rows):
    from sales import switch_project
    cur = None
    for r in rows:
        r['dur'], r['comment'] = None, ''
        try:
            first = r.get('src') or cur or 1
            url = None
            for p in [first] + [x for x in (1, 4) if x != first]:     # the visit page needs the project it was entered in
                if p != cur:
                    switch_project(s, p); cur = p
                url = audio.audio_url(s, r['id'])
                if url:
                    break
            if not url:
                r['comment'] = 'Запись йўқ'; continue
            ext = url.split('?')[0].rsplit('.', 1)[-1].lower()
            data = s.get(url, timeout=120).content
            with tempfile.NamedTemporaryFile(suffix='.' + ext) as f:
                f.write(data); f.flush()
                m = audio.measure(f.name)
            r['dur'] = m['dur']
            if m['dur'] < 5 or m['silence_pct'] >= 97 or (m['mean_db'] is not None and m['mean_db'] < -55):
                r['comment'] = 'Маълумот йўқ (ёзувда овоз йўқ)'; continue
            r['comment'] = judge(audio.ai_two(data, audio.MIME.get(ext, 'audio/aac'), PROMPT))
        except Exception as e:
            print("::warning::az listen " + str(e)[:120])
            r['comment'] = r['comment'] or 'Текширилмади (ИИ лимити)'
    return rows


def refill(ws, proj=1) -> int:
    """Rows left as 'Текширилмади (ИИ лимити)' are listened to again."""
    from sales import login, switch_project
    todo = []
    for row in ws.iter_rows(min_row=1):
        g, h = row[6].value, row[7].value
        if isinstance(g, str) and g.startswith('Текширилмади') and isinstance(h, str):
            m = re.search(r'/visits/(\d+)/', h)
            if m:
                todo.append((row, {'id': int(m.group(1)), 'src': proj}))
    if not todo:
        return 0
    s = login(); switch_project(s, proj)
    listen(s, [r for _, r in todo])
    n = 0
    for row, r in todo:
        if r['comment'] and not r['comment'].startswith('Текширилмади'):
            row[6].value = r['comment']; n += 1
            if r.get('dur'):
                sec = int(round(r['dur'])); row[5].value = dt.time(min(sec // 60, 23), sec % 60)
    print(f"::notice::az refill {n}/{len(todo)}")
    return n


def write_block(ws, day: dt.date, rows):
    """Insert a day block at the top, copying the styles of the existing header/data rows."""
    hdr = [copy.copy(ws.cell(1, j)._style) for j in range(1, 9)]
    dat = [copy.copy(ws.cell(2, j)._style) for j in range(1, 9)]
    hh, dh = ws.row_dimensions[1].height, ws.row_dimensions[2].height
    n = len(rows) + 1
    ws.insert_rows(1, n)
    for j, v in enumerate([f"{day:%d.%m}", 'Менеджер', 'Регион', 'Дата', 'Аптека', 'Длительность записи', 'Комментария', 'Ссылка'], 1):
        c = ws.cell(1, j, v); c._style = copy.copy(hdr[j - 1])
    ws.row_dimensions[1].height = hh
    for i, r in enumerate(rows, 2):
        dur = None
        if r['dur']:
            sec = int(round(r['dur']))
            dur = dt.time(min(sec // 60, 23), sec % 60)        # his file keeps m:ss in an h:mm cell
        link = f"{BASE}/lists/visits/{r['id']}/result"
        vals = [None, r['who'], r['reg'], f"{day:%d.%m}", f'"{r["obj"]}"', dur, r['comment'], link]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v); c._style = copy.copy(dat[j - 1])
        ws.row_dimensions[i].height = dh
    # openpyxl does not move hyperlinks on insert_rows: rebuild them from the link texts
    ws._hyperlinks = []
    for row in ws.iter_rows(min_col=8, max_col=8):
        c = row[0]
        if isinstance(c.value, str) and c.value.startswith('http'):
            c.hyperlink = c.value


def run(days, send=True, grp='tp'):
    """Add blocks for the given days (oldest first, so the newest ends on top) and send the file. grp: 'tp' or 'mp'."""
    import vcache, roster as R
    from sales import login, switch_project
    wb = load_file(grp)
    if wb is None:
        print(f"::warning::az {grp}: base file not uploaded yet"); return
    ws = wb.active
    import os as _o
    if _o.environ.get('AZ_REDO'):
        print(f"::notice::az redo: removed old blocks {[f'{d:%d.%m}' for d in days if drop_day(ws, f'{d:%d.%m}')]}")
    refilled = refill(ws, 1 if grp == 'tp' else 4)
    have = {b[0] for b in blocks(ws)} if not getattr(wb, '_az_tmpl', 0) else set()
    days = [d for d in sorted(days) if f"{d:%d.%m}" not in have]
    if not days and not refilled:
        print(f"::notice::az {grp}: nothing new"); return
    regions = {}
    if days:
        d1_ = min(days).replace(day=1)
        try:
            parts = R.load(); regions = dict(zip(parts['mp']['key'], parts['mp']['region']))
            raw_tp, raw_mp = R.regroup(vcache.get('tp', d1_, max(days)), vcache.get('mp', d1_, max(days)), parts['tp'], parts['mp'])
        except Exception as e:
            print(f"::warning::az roster not available ({str(e)[:80]}) - plain projects")
            raw_tp, raw_mp = vcache.get('tp', d1_, max(days)), vcache.get('mp', d1_, max(days))
        v = raw_tp if grp == 'tp' else raw_mp
        v = v[v['Тип визита'].fillna('').str.contains('аптек|контрагент', case=False)]
        v = v.assign(day=pd.to_datetime(v['Дата'], format='%d.%m.%Y'))
        s = login()
    added = []
    for d in days:
        checked, last_seen = set(), {}
        for b in blocks(ws):
            try:
                bd = dt.date(d.year, int(b[0][3:5]), int(b[0][:2]))
            except Exception:
                continue
            for m in b[1]:
                last_seen[key(m)] = max(last_seen.get(key(m), ''), bd.isoformat())
                if bd.month == d.month and bd.year == d.year:
                    checked.add(key(m))
        rows = pick(d, v, checked, last_seen, seed=d.toordinal(), grp=grp, regions=regions)
        if not rows:
            print(f"::notice::az {grp} {d}: no {LABEL[grp]} visits"); continue
        listen(s, rows)
        tmpl = getattr(wb, '_az_tmpl', 0)
        write_block(ws, d, rows)
        if tmpl:                                       # new МП file: drop the copied style-template block (it is now the last one)
            ws.delete_rows(ws.max_row - tmpl + 1, tmpl); wb._az_tmpl = 0; _relink(ws)
        added.append((d, rows))
        print(f"::notice::az {grp} {d}: {len(rows) // PER_TP} {LABEL[grp]}, {len(rows)} rows")
    if added and grp == 'tp':
        target = max(d for d, _ in added).month
        if any(int(b[0][3:5]) != target for b in blocks(ws) if b[0][3:5].isdigit()):
            old = io.BytesIO(); wb.save(old)            # previous month's file is kept separately
            prev = [b[0] for b in blocks(ws) if b[0][3:5].isdigit() and int(b[0][3:5]) != target]
            store.save_bytes(f"az_file_m{prev[0][3:5]}", old.getvalue())
            print(f"::notice::az: month {target} starts a new file, removed {prune(ws, target)} old blocks")
    save_file(wb, grp)
    if send and (added or refilled):
        from telegram import send_text, send_file
        last = max([d for d, _ in added] or [dt.datetime.now(TZ).date()])
        tag = '' if grp == 'tp' else ' МП'
        path = f"/tmp/Аудиозаписи{tag} ({MON[last.month]}-{last:%y}).xlsx"
        wb.save(path)
        lines = [f"🎧 <b>Аудиозаписи{tag}</b>" + (" — қўшилди: " + ", ".join(f"{d:%d.%m}" for d, _ in added) if added else "")]
        if refilled:
            lines.append(f"• олдин ИИ лимити туфайли текширилмай қолган {refilled} та ёзув тингланди")
        for d, rows in added:
            bad = sum(1 for r in rows if r['comment'].startswith(('Маълумот йўқ', 'Запись йўқ')))
            lines.append(f"• {d:%d.%m}: {len(rows) // PER_TP} {LABEL[grp]}, {len(rows)} ёзув, «Маълумот йўқ / ёзув йўқ»: {bad}")
        send_text("\n".join(lines))
        send_file(path, f"Аудиозаписи{tag} — янги кунлар тепада")


if __name__ == "__main__":
    import os, sys
    mode = os.environ.get("AZ_MODE", "")
    today = dt.datetime.now(TZ).date()
    if mode == "split":                      # keep only the current month in the file and send it
        wb = load_file(); ws = wb.active
        b = io.BytesIO(); wb.save(b); store.save_bytes('az_file_m10', b.getvalue())
        n = prune(ws, today.month); save_file(wb)
        path = f"/tmp/Аудиозаписи ({MON[today.month]}-{today:%y}).xlsx"; wb.save(path)
        from telegram import send_file
        send_file(path, f"Аудиозаписи — фақат {MON[today.month].lower()} (олдинги ой алоҳида сақланди)")
        print(f"::notice::az split: removed {n} blocks, kept {[x[0] for x in blocks(ws)]}")
    elif mode == "review":                   # transcripts of this month's rows for a manual check (encrypted for Claude)
        import json, roster as R
        from sales import login, switch_project
        wb = load_file(); ws = wb.active
        TP = ("Listen to this whole pharmacy visit recording (Uzbek or Russian speech; there may be street/shop noise). "
              "First write a faithful transcript with speaker turns R: (sales rep) and P: (pharmacist/other); mark unclear parts [...]; "
              "write [no speech] only if nobody talks at all. Then, ONLY from that transcript, write the manager comment:\n" + PROMPT.split("Write the manager's check comment in Uzbek Cyrillic, in exactly this style:")[1].split("Return ONLY JSON")[0] +
              'Return ONLY JSON {"transcript": "...", "comment": "...", "speech_seconds": number}')
        s_ = login(); switch_project(s_, 1)
        out = []
        for row in ws.iter_rows(min_row=1):
            h = row[7].value
            if not (isinstance(h, str) and '/visits/' in h) or row[1].value == 'Менеджер':
                continue
            vid = int(re.search(r'/visits/(\d+)/', h).group(1))
            rec = {'id': vid, 'who': row[1].value, 'date': row[3].value, 'comment': row[6].value}
            try:
                url = audio.audio_url(s_, vid)
                if url:
                    ext = url.split('?')[0].rsplit('.', 1)[-1].lower()
                    data = s_.get(url, timeout=120).content
                    with tempfile.NamedTemporaryFile(suffix='.' + ext) as f:
                        f.write(data); f.flush(); rec['m'] = audio.measure(f.name)
                    a = audio.ai(data, audio.MIME.get(ext, 'audio/aac'), TP)
                    rec['t'] = a.get('transcript', ''); rec['c2'] = a.get('comment', ''); rec['sp'] = a.get('speech_seconds')
            except Exception as e:
                rec['err'] = str(e)[:150]
            out.append(rec)
        os.makedirs('drop', exist_ok=True)
        open('drop/az_review.fer', 'wb').write(R._fernet().encrypt(json.dumps(out, ensure_ascii=False).encode()))
        print(f"::notice::az review: {len(out)} rows")
    elif mode == "relisten":                 # listen again to every row of the current file with the stronger models
        from sales import login, switch_project
        wb = load_file(); ws = wb.active
        todo = []
        for row in ws.iter_rows(min_row=1):
            h = row[7].value
            if isinstance(h, str) and '/visits/' in h and row[1].value != 'Менеджер':
                todo.append((row, {'id': int(re.search(r'/visits/(\d+)/', h).group(1))}))
        s_ = login(); switch_project(s_, 1)
        listen(s_, [r for _, r in todo])
        ch = 0
        for row, r in todo:
            if r['comment'] and not r['comment'].startswith('Текширилмади'):
                if row[6].value != r['comment']:
                    ch += 1
                row[6].value = r['comment']
            else:
                row[6].value = 'Текширилмади (ИИ лимити)'
        save_file(wb)
        path = f"/tmp/Аудиозаписи ({MON[today.month]}-{today:%y}).xlsx"; wb.save(path)
        from telegram import send_file
        send_file(path, "Аудиозаписи — изоҳлар кучлироқ ИИ билан қайта ёзилди")
        print(f"::notice::az relisten: {len(todo)} rows, changed {ch}, left {sum(1 for _, r in todo if not r['comment'] or r['comment'].startswith('Текширилмади'))}")
    elif mode == "claude_audit":              # read-only check of one day's rows for Claude (encrypted to drop_pub.pem)
        import json, vcache, roster as R
        from sales import login, switch_project
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        day = dt.date.fromisoformat(os.environ["AZ_FROM"]) if os.environ.get("AZ_FROM") else today - dt.timedelta(days=1)
        dd = f"{day:%d.%m}"
        parts = R.load(); regions = dict(zip(parts['mp']['key'], parts['mp']['region']))
        d1m = day.replace(day=1)
        raw_tp, raw_mp = R.regroup(vcache.get('tp', d1m, day), vcache.get('mp', d1m, day), parts['tp'], parts['mp'])
        Q = ("Listen to this whole pharmacy visit recording (Uzbek/Russian speech, maybe noise). First a faithful transcript with speaker turns "
             "R: (sales rep) and P: (pharmacist/other), [...] for unclear parts, [no speech] only if nobody talks. Then ONLY from the transcript: "
             "topic in Russian (1 sentence), which of our products (Риномакс, Форсил, Риноксил, Мирамистин, Эрегра, Тивомакс, Триомакс, Альцетро, Авирол) "
             "were named, whether остатка/stock was asked, whether it is a work conversation, speech_seconds. "
             'Return ONLY JSON {"transcript": "...", "topic": "...", "products": [], "stock_asked": true/false, "work_talk": true/false, "speech_seconds": number}')
        s_ = login(); out = []; cur = None
        for grp, raw in (('tp', raw_tp), ('mp', raw_mp)):
            wb = load_file(grp)
            if wb is None:
                continue
            ws = wb.active
            heads = [r for r in range(1, ws.max_row + 1) if ws.cell(r, 2).value == 'Менеджер']
            allb = [(str(ws.cell(h, 1).value).strip(), h) for h in heads]
            seen_prev = {}
            for i, h in enumerate(heads):
                end = (heads[i + 1] - 1) if i + 1 < len(heads) else ws.max_row
                bday = str(ws.cell(h, 1).value).strip()
                for r in range(h + 1, end + 1):
                    if bday != dd:
                        who = ws.cell(r, 2).value
                        if who:
                            seen_prev.setdefault(key(who), []).append(bday)
            for i, h in enumerate(heads):
                if str(ws.cell(h, 1).value).strip() != dd:
                    continue
                end = (heads[i + 1] - 1) if i + 1 < len(heads) else ws.max_row
                for r in range(h + 1, end + 1):
                    row = [ws.cell(r, j).value for j in range(1, 9)]
                    if not (isinstance(row[7], str) and '/visits/' in row[7]):
                        continue
                    vid = int(re.search(r'/visits/(\d+)/', row[7]).group(1))
                    rec = {'grp': grp, 'xl_row': r, 'who': row[1], 'reg': row[2], 'date': str(row[3]), 'obj': row[4],
                           'dur_xl': str(row[5]), 'comment': row[6], 'link': row[7], 'id': vid, 'prev_days_checked': seen_prev.get(key(row[1]), [])}
                    m = raw[raw['#'].astype(int) == vid]
                    if len(m):
                        x = m.iloc[0]
                        rec['sales'] = {'who': x['Фарм. пред'], 'date': x['Дата'], 'type': x['Тип визита'], 'obj': x['Контр-агент/Врач'],
                                        'end': x.get('Время завершения визита'), 'src': int(x['src'])}
                        v_day = raw[(raw['Дата'] == x['Дата']) & (raw['Фарм. пред'] == x['Фарм. пред']) & raw['Тип визита'].fillna('').str.contains('аптек|контрагент', case=False)]
                        rec['mgr_visits_that_day'] = int(len(v_day))
                    else:
                        rec['sales'] = None
                    rec['exp_reg'] = short_region(row[1] or '') if grp == 'tp' else FULL2SHORT.get(regions.get(key(row[1] or '')))
                    out.append(rec)
        out.sort(key=lambda z: (z['sales'] or {}).get('src', 1))
        for rec in out:
            try:
                src = (rec['sales'] or {}).get('src') or (1 if rec['grp'] == 'tp' else 4)
                if src != cur:
                    switch_project(s_, src); cur = src
                url = audio.audio_url(s_, rec['id'])
                rec['has_audio'] = bool(url)
                if url:
                    ext = url.split('?')[0].rsplit('.', 1)[-1].lower()
                    data = s_.get(url, timeout=120).content
                    with tempfile.NamedTemporaryFile(suffix='.' + ext) as f:
                        f.write(data); f.flush(); rec['m'] = audio.measure(f.name)
                    if rec['m']['dur'] >= 5 and rec['m']['silence_pct'] < 97:
                        rec['ai'] = audio.ai(data, audio.MIME.get(ext, 'audio/aac'), Q)
            except Exception as e:
                rec['err'] = str(e)[:150]
        try:
            switch_project(s_, 1)
        except Exception:
            pass
        k_ = Fernet.generate_key()
        pub = serialization.load_pem_public_key(open('drop_pub.pem', 'rb').read())
        ek = pub.encrypt(k_, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        os.makedirs('drop', exist_ok=True)
        open('drop/claude_audit.key', 'wb').write(ek)
        open('drop/claude_audit.fer', 'wb').write(Fernet(k_).encrypt(json.dumps(out, ensure_ascii=False, default=str).encode()))
        print(f"::notice::az claude_audit {dd}: {len(out)} rows")
    elif mode == "recheck":                  # re-listen to the SAME rows of given days with the two-model rule, in place
        from sales import login
        d1 = dt.date.fromisoformat(os.environ["AZ_FROM"]); d2 = dt.date.fromisoformat(os.environ.get("AZ_TO") or os.environ["AZ_FROM"])
        want = {f"{d1 + dt.timedelta(days=i):%d.%m}" for i in range((d2 - d1).days + 1)}
        s_ = login()
        for g in ((os.environ.get('AZ_GROUP') or 'tp,mp').split(',')):
            g = g.strip(); wb = load_file(g)
            if wb is None:
                continue
            ws = wb.active; todo = []; day = None
            for row in ws.iter_rows(min_row=1):
                if row[1].value == 'Менеджер':
                    day = str(row[0].value).strip(); continue
                h = row[7].value
                if day in want and isinstance(h, str) and '/visits/' in h:
                    todo.append((row, {'id': int(re.search(r'/visits/(\d+)/', h).group(1)), 'src': 1 if g == 'tp' else 4}))
            listen(s_, [r for _, r in todo])
            ch = 0
            for row, r in todo:
                if r['comment'] == 'Текширилмади (ИИ лимити)':       # free limit ended: keep what the file had, never wipe it
                    continue
                if row[6].value != r['comment']:
                    ch += 1
                row[6].value = r['comment']
                if r.get('dur'):
                    sec = int(round(r['dur'])); row[5].value = dt.time(min(sec // 60, 23), sec % 60)
            save_file(wb, g)
            left = sum(1 for _, r in todo if r['comment'].startswith('Текширилмади'))
            print(f"::notice::az recheck {g} {sorted(want)}: {len(todo)} rows, changed {ch}, unsure {left}")
            if os.environ.get("AZ_SEND", "1") == "1" and todo and ch:
                from telegram import send_text, send_file
                tag = '' if g == 'tp' else ' МП'
                path = f"/tmp/Аудиозаписи{tag} ({MON[today.month]}-{today:%y}).xlsx"; wb.save(path)
                send_text(f"🎧 <b>Аудиозаписи{tag}</b> — {', '.join(sorted(want))} изоҳлари қайта текширилди (2 та ИИ келишуви): {len(todo)} ёзув, ўзгарди {ch}, ҳал бўлмади {left}")
                send_file(path, f"Аудиозаписи{tag} — қайта текширилган")
    elif mode == "keycheck":                 # which Gemini keys work (status codes only, never the key)
        import requests, merch
        print(f"::notice::keys configured: {len(merch.KEYS)}")
        for ki, k in enumerate(merch.KEYS):
            for m in ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"):
                try:
                    x = requests.post(f"{merch.API}/models/{m}:generateContent", headers={"x-goog-api-key": k}, timeout=20,
                                      json={"contents": [{"parts": [{"text": "OK"}]}], "generationConfig": {"maxOutputTokens": 2}})
                    why = ""
                    if x.status_code != 200:
                        e = x.json().get("error", {}); why = (e.get("status") or "") + " " + str(e.get("message", ""))[:110]
                    print(f"::notice::key{ki + 1} {m}: {x.status_code} {why}")
                except Exception as ex:
                    print(f"::notice::key{ki + 1} {m}: err {str(ex)[:60]}")
    elif mode == "upload":                     # Bobur's own file -> becomes the base
        src = sys.argv[1]
        store.save_bytes('az_file', open(src, 'rb').read())
        print("::notice::az base saved")
    else:
        d1 = dt.date.fromisoformat(os.environ["AZ_FROM"]) if os.environ.get("AZ_FROM") else today - dt.timedelta(days=1)
        d2 = dt.date.fromisoformat(os.environ["AZ_TO"]) if os.environ.get("AZ_TO") else today - dt.timedelta(days=1)
        _days = [d1 + dt.timedelta(days=i) for i in range((d2 - d1).days + 1)]
        for _g in ((os.environ.get('AZ_GROUP') or 'tp,mp').split(',')):
            try:
                run(_days, grp=_g.strip())
            except Exception as e:
                print(f"::error::az {_g}: {str(e)[:200]}")
