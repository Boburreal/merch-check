"""Telegram bot actions. One run per incoming update (Cloudflare Worker -> bot.yml -> this file).
Screenshot / text with a pharmacy  -> find it in the base, show 3-month visit history, ask "delete location?"
Button "Ўчир"                      -> empty the pharmacy's location in Sales (all other fields kept), verify.
Only Bobur's chat (stored encrypted) is served; nothing is deleted without his button press."""
import datetime as dt, json, os, re
from zoneinfo import ZoneInfo
import pandas as pd
import requests

import store
from telegram import API, chat_id

TZ = ZoneInfo("Asia/Tashkent")
DAYS = 92
LAT = str.maketrans({'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'k': 'к', 'm': 'м', 't': 'т',
                     'h': 'н', 'b': 'в', 'y': 'у'})


def tg(method, **data):
    for k, v in list(data.items()):
        if isinstance(v, (dict, list)):
            data[k] = json.dumps(v, ensure_ascii=False)
    r = requests.post(f"{API}/{method}", data=data, timeout=60)
    if not r.ok:
        print(f"::warning::{method} {r.status_code} {r.text[:150]}")
    return r.json() if r.ok else {}


def say(text, kb=None):
    for i in range(0, len(text), 4000):
        last = i + 4000 >= len(text)
        tg("sendMessage", chat_id=OWNER, text=text[i:i + 4000], parse_mode="HTML",
           disable_web_page_preview="true", **({"reply_markup": {"inline_keyboard": kb}} if kb and last else {}))


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def norm(s):
    s = str(s).lower().replace('ё', 'е').replace('ў', 'у').replace('қ', 'к').replace('ғ', 'г').replace('ҳ', 'х')
    s = re.sub(r'["«»\'`’ʻ.,()]', ' ', s.translate(LAT))
    s = re.sub(r'\b(аптека|апт|dorixona|дорихона|xk|хк|ооо|мчж|mchj|хусусий|xususiy|korxonasi|корхонаси)\b', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# ---------------------------------------------------------------- reading the screenshot
def read_screenshot(file_id) -> dict:
    from merch import API as GAPI, GEMINI_KEY, pick_model, _img_part, shrink
    path = tg("getFile", file_id=file_id)["result"]["file_path"]
    img = requests.get(f"{API.replace('/bot', '/file/bot')}/{path}", timeout=60).content
    prompt = ("This is a screenshot from a Telegram work group of a pharma company in Uzbekistan. A sales rep asks to "
              "delete (or change) the GPS location of a pharmacy in the CRM. Extract, keeping the original spelling: "
              'Return ONLY JSON {"pharmacy": name of the pharmacy, "address": address or district if written, '
              '"region": region/city if written, "inn": INN if written, "sender": name of the person who wrote, '
              '"date": message date if visible, "request": short summary of what is asked}. Use "" when absent.')
    body = {"contents": [{"parts": [{"text": prompt}, _img_part(shrink(img, 1600))]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    r = requests.post(f"{GAPI}/models/{pick_model()}:generateContent", headers={"x-goog-api-key": GEMINI_KEY},
                      json=body, timeout=120)
    r.raise_for_status()
    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().removeprefix("```json").removesuffix("```")
    d = json.loads(txt)
    return d[0] if isinstance(d, list) else d


# ---------------------------------------------------------------- finding the pharmacy
def companies():
    c = store.load('companies_last')
    for k in ('name', 'region', 'district', 'reps'):
        c[k] = c[k].fillna('').astype(str)
    c['id'] = c['id'].astype(int)
    c['n'] = c['name'].map(norm)
    return c


def exact(c, name):
    """Only pharmacies whose name is exactly the one written (case, quotes, spaces and the word «аптека» ignored)."""
    q = norm(name)
    return c[c['n'] == q] if q else c[:0]


def pick_kb(rows):
    return [[{"text": f"{r['name'][:30]} · {r.region[:12]} {r.district[:12]} · ID {r.id}", "callback_data": f"pick:{r.id}"}]
            for _, r in rows.head(8).iterrows()]


# ---------------------------------------------------------------- history
def visits_for(row):
    import vcache
    d2 = dt.datetime.now(TZ).date()
    d1 = d2 - dt.timedelta(days=DAYS)
    out = []
    for grp, who in (('tp', 'ТП'), ('mp', 'МП')):
        v = vcache.get(grp, d1, d2)
        if not len(v):
            continue
        obj = v['Контр-агент/Врач'].fillna('')
        v = v.assign(obj=obj.str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip(),
                     reg=obj.str.extract(r'\(([^()]*)\)\s*$')[0].fillna(''))
        m = v[v['obj'].map(norm) == row.n]
        if row.region and len(m):
            same = m[m['reg'].map(norm).str[:5] == norm(row.region)[:5]]
            m = same if len(same) else m
        m = m.assign(grp=who, emp=m['Фарм. пред'].str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip())
        out.append(m[['emp', 'grp', 'Время завершения визита']])
    v = pd.concat(out) if out else pd.DataFrame(columns=['emp', 'grp', 'Время завершения визита'])
    v['t'] = pd.to_datetime(v['Время завершения визита'], format='%d.%m.%Y %H:%M', errors='coerce')
    return v.sort_values('t', ascending=False), d1, d2


def header(row):
    lat, lon = pd.to_numeric(row.lat, errors='coerce'), pd.to_numeric(row.lon, errors='coerce')
    L = [f"🏥 <b>{esc(row['name'])}</b>  (ID {row.id})",
         f"📍 {esc(row.region)}{', ' + esc(row.district) if row.district else ''}"]
    if row.reps:
        L.append(f"📌 Базада бириктирилган: {esc(row.reps)}")
    L.append(f"🗺 Локация: <a href=\"https://yandex.uz/maps/?pt={lon},{lat}&z=18&l=map\">{lat:.6f}, {lon:.6f}</a>"
             if pd.notna(lat) else "🗺 Локация: <b>йўқ</b> (базада ҳозир бўш)")
    return L, pd.notna(lat)


def ask_people(row, shot=None):
    """Step 1: list everyone who visited (3 months) + people attached in the base; Bobur ticks the attached ones."""
    v, d1, d2 = visits_for(row)
    g = (v.groupby(['emp', 'grp']).size().reset_index(name='n').sort_values('n', ascending=False)
         if len(v) else pd.DataFrame(columns=['emp', 'grp', 'n']))
    people = [(r.emp, r.grp, int(r.n)) for r in g.itertuples()]
    known = {norm(p[0]) for p in people}
    for rep in re.split(r'[,;\n]', row.reps or ''):
        rep = re.sub(r'\s*\([^()]*\)\s*$', '', rep).strip()
        if rep and norm(rep) not in known:
            people.append((rep, '—', 0)); known.add(norm(rep))
    people = people[:24]
    store.save(f'ctx_{row.id}', pd.DataFrame(people, columns=['emp', 'grp', 'n']))
    store.save(f'ctxv_{row.id}', v[['emp', 'grp', 'Время завершения визита']])
    L, _ = header(row)
    if shot:
        L.append(f"📩 Скриншотда: {esc(shot.get('sender') or '—')}: «{esc(shot.get('request') or '')}»")
    L.append(f"\n📊 {d1:%d.%m}–{d2:%d.%m.%Y}: <b>{len(v)}</b> та визит, {len(g)} ходим.")
    if not people:
        L.append("Бу аптекага 3 ойда ҳеч ким бормаган ва базада ҳеч ким бириктирилмаган.")
    L.append("\n👇 <b>Бу аптекага қайси ходимлар бириктирилган?</b> Белгиланг ва «Тайёр» ни босинг.")
    kb = [[{"text": f"☐ {p[0][:28]} · {p[1]} · {p[2]}", "callback_data": f"t:{i}"}] for i, p in enumerate(people)]
    kb.append([{"text": "✅ Тайёр", "callback_data": f"go:{row.id}"}, {"text": "❌ Бекор", "callback_data": f"no:{row.id}"}])
    say("\n".join(L), kb)


def analytics(row, sel):
    """Step 2: analysis against the people Bobur marked as attached, then ask to delete."""
    people = store.load(f'ctx_{row.id}')
    v = store.load(f'ctxv_{row.id}')
    if not len(people) and not len(v):
        vv, _, _ = visits_for(row)
        v = vv[['emp', 'grp', 'Время завершения визита']]
    v = v.copy()
    v['t'] = pd.to_datetime(v['Время завершения визита'], format='%d.%m.%Y %H:%M', errors='coerce')
    v = v.sort_values('t', ascending=False)
    chosen = {norm(people.iloc[i]['emp']) for i in sel if i < len(people)}
    L, has_loc = header(row)
    d2 = dt.datetime.now(TZ).date(); d1 = d2 - dt.timedelta(days=DAYS)
    L.append(f"\n📊 <b>Охирги 3 ой ({d1:%d.%m}–{d2:%d.%m.%Y}): {len(v)} та визит</b>")
    L.append("\n✅ <b>Бириктирилган ходимлар (сиз белгилаган):</b>")
    if not chosen:
        L.append(" — ҳеч ким белгиланмади")
    for i in sel:
        if i >= len(people):
            continue
        p = people.iloc[i]
        m = v[v['emp'].map(norm) == norm(p['emp'])]
        if len(m):
            L.append(f" • {esc(p['emp'])} ({m.grp.iloc[0]}) — <b>{len(m)}</b> марта, "
                     f"{m.t.min():%d.%m}…{m.t.max():%d.%m.%Y}, охиргиси {(pd.Timestamp(d2) - m.t.max().normalize()).days} кун олдин")
        else:
            L.append(f" • {esc(p['emp'])} — ⚠️ 3 ойда <b>бирор марта ҳам бормаган</b>")
    other = v[~v['emp'].map(norm).isin(chosen)]
    if len(other):
        L.append("\n❗️ <b>Бириктирилмаган, лекин визит қилган:</b>")
        for (e, g), m in other.groupby(['emp', 'grp']):
            L.append(f" • {esc(e)} ({g}) — <b>{len(m)}</b> марта, {m.t.min():%d.%m}…{m.t.max():%d.%m.%Y}")
    if len(v):
        L.append("\n🕒 Охирги визитлар:")
        L += [f" {r.t:%d.%m %H:%M} — {esc(r.emp)} ({r.grp})" for r in v.head(8).itertuples()]
        months = v['t'].dt.strftime('%m.%Y').value_counts().sort_index()
        L.append("📅 Ойлар бўйича: " + ", ".join(f"{k}: {n}" for k, n in months.items()))
    lg = store.load('loc_log')
    if len(lg):
        lg = lg[lg['ID'].astype(str) == str(row.id)]
        if len(lg):
            L.append("\n🔁 <b>Локация ўзгаришлари:</b>")
            L += [f" • {r[1]} — {r[7]}" for r in lg.tail(6).itertuples(index=False)]
    offs = []
    for grp in ('tp', 'mp'):
        o = store.load(f'offenses_{grp}')
        if len(o):
            o = o[o['obj'].map(norm) == row.n]
            offs += [f"{r.date[8:10]}.{r.date[5:7]} {esc(r.who)}: {TYPES.get(r.type, r.type)}" for r in o.itertuples()]
    if offs:
        L.append("\n⚠️ <b>Шу аптекадаги шубҳали визитлар:</b>")
        L += [" • " + x for x in offs[-6:]]
    kb = None
    if has_loc:
        L.append("\n<b>Локацияни ўчирайми?</b>")
        kb = [[{"text": "🗑 Ҳа, ўчир", "callback_data": f"del:{row.id}"},
               {"text": "❌ Йўқ", "callback_data": f"no:{row.id}"}]]
    say("\n".join(L), kb)


# ---------------------------------------------------------------- deleting the location
def serialize(html):
    """Serialize the edit form exactly like a browser would submit it."""
    from bs4 import BeautifulSoup
    form = BeautifulSoup(html, 'lxml').find('form', class_='edit_form')
    out = []
    for el in form.find_all(['input', 'select', 'textarea']):
        n = el.get('name')
        if not n or el.has_attr('disabled'):
            continue
        if el.name == 'input':
            t = (el.get('type') or 'text').lower()
            if t in ('submit', 'button', 'image', 'reset', 'file'):
                continue
            if t in ('checkbox', 'radio'):
                if el.has_attr('checked'):
                    out.append((n, el.get('value', 'on')))
                continue
            out.append((n, el.get('value', '')))
        elif el.name == 'textarea':
            out.append((n, el.text))
        else:
            opts = el.find_all('option')
            sel = [o for o in opts if o.has_attr('selected')]
            if el.has_attr('multiple'):
                out += [(n, o.get('value', o.text.strip())) for o in sel]
            elif sel or opts:
                o = sel[-1] if sel else opts[0]
                out.append((n, o.get('value', o.text.strip())))
    return out


def delete_location(cid: int):
    """The edit page opens only under the project the pharmacy belongs to (ТП=1 or МП=4)."""
    from sales import login, switch_project
    s = login()
    try:
        for proj in (1, 4):
            switch_project(s, proj)
            res = _delete_in(s, cid)
            if res is not None:
                return res
        return '', '', "failed (аптеканинг таҳрирлаш саҳифаси очилмади — ТП ва МП лойиҳаларида ҳам)"
    finally:
        switch_project(s, 1)


def _delete_in(s, cid: int):
    from sales import BASE
    url = f"{BASE}/lists/companies/{cid}/edit"
    page = s.get(url, timeout=60)
    if 'class="edit_form"' not in page.text:
        print(f"::notice::edit page status={page.status_code} url_end={page.url[-30:]}")
        return None
    before = serialize(page.text)
    loc = dict(before).get('location', '')
    name = dict(before).get('name', '')
    if not loc.strip():
        return name, loc, "already"
    data = [(k, '' if k == 'location' else v) for k, v in before]
    r = s.post(url, files=[(k, (None, v)) for k, v in data], timeout=60, headers={"Referer": url})
    after = serialize(s.get(url, timeout=60).text)
    keep = lambda f: [(k, v) for k, v in f if k not in ('_token', 'location')]
    if dict(after).get('location', '').strip():
        return name, loc, f"failed (HTTP {r.status_code}, локация сақланиб қолди)"
    if keep(after) != keep(before):
        changed = sorted({k for k, v in set(keep(before)) ^ set(keep(after))})
        return name, loc, "changed:" + ", ".join(changed)
    log = store.load('loc_deleted')
    row = pd.DataFrame([{'id': cid, 'name': name, 'old': loc, 'when': dt.datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}])
    store.save('loc_deleted', pd.concat([log, row]) if len(log) else row)
    return name, loc, "ok"


# ---------------------------------------------------------------- dispatch
def main():
    u = json.loads(os.environ["UPDATE"])
    if u.get("chat") == "owner":          # manual test run by a repo maintainer
        u["chat"] = OWNER
    if int(u.get("chat", 0)) != OWNER:
        print("::notice::ignored foreign chat")
        return
    if u.get("cb"):
        act, _, rest = u["cb"].partition(":")
        cid, _, sel = rest.partition(":")
        cid = int(cid)
        print(f"::notice::action={act} id={cid}")
        c = companies()
        row = c[c.id == cid]
        if act == "no":
            say("❌ Бекор қилинди, локацияга тегилмади.")
        elif act == "pick":
            ask_people(row.iloc[0])
        elif act == "go":
            analytics(row.iloc[0], [int(x) for x in sel.split(",") if x.isdigit()])
        elif act == "del":
            name, old, st = delete_location(cid)
            if st == "ok":
                say(f"✅ <b>{esc(name)}</b> (ID {cid}) — локация ўчирилди.\nЭски координата: <code>{esc(old)}</code>\n"
                    "Бошқа маълумотлари ўзгармади (текширилди). Кимдир янги локация қўйса, хабар бераман.")
            elif st == "already":
                say(f"ℹ️ <b>{esc(name)}</b> (ID {cid}) — локацияси аллақачон бўш экан.")
            elif st.startswith("changed:"):
                say(f"⚠️ <b>{esc(name)}</b> (ID {cid}) — локация ўчди, лекин бошқа майдонлар ҳам ўзгарган кўринди: "
                    f"{esc(st[8:])}. Sales'да шу аптекани текшириб кўринг.")
            else:
                say(f"❗️ <b>{esc(name)}</b> (ID {cid}) — ўчмади: {esc(st)}. Қўлда текшириб кўринг.")
        return
    text = (u.get("text") or "").strip()
    if text.startswith("/start") or text.lower() in ("/help", "ёрдам", "yordam"):
        # the bot menu is for visit analytics only (removes commands another program left on this bot)
        tg("setMyCommands", commands=[{"command": "start", "description": "Ёрдам"}])
        say("📊 <b>Визит аналитикаси боти</b>\n\n"
            "<b>Ўзи юборади:</b>\n"
            "• ҳар куни 17:30 — ТП «Факт визит и мерч» ва МП визит файллари (ой бошидан)\n"
            "• ҳар куни 08:30 — кечаги кун кечиккан визитлар билан янгиланган\n"
            "• якшанба 23:00 — ҳафталик тўлиқ таҳлил\n"
            "• ойнинг 1-санаси 09:00 — ойлик таҳлил (шубҳали ҳолати бор ходимлар)\n"
            "• аптека локацияси ўзгарса ёки ўчирилган локация қайта қўйилса — хабар\n\n"
            "<b>Аптека локациясини ўчириш:</b> гуруҳдаги хабар скриншотини ташланг (ёки аптека номи / ID). "
            "3 ойлик визитлар тарихини кўрсатаман, фақат сиз «Ҳа, ўчир» тугмасини боссангиз ўчираман.")
        return
    shot = None
    c = companies()
    if u.get("photo"):
        shot = read_screenshot(u["photo"])
        q = shot.get("pharmacy", "")
        if not q:
            say("Скриншотдан аптека номини топа олмадим. Номини ёки ID сини ёзинг.")
            return
    elif text.isdigit() and int(text) in set(c.id):
        ask_people(c[c.id == int(text)].iloc[0])
        return
    elif text:
        q = text
    else:
        return
    hit = exact(c, q)
    src = f"🔎 Скриншотдаги ном: <b>{esc(q)}</b>\n" if shot else ""
    if not len(hit):
        say(src + "Базада айнан шу номли аптека йўқ. Номини Sales'дагидек ёзинг ёки ID сини юборинг.")
    elif len(hit) == 1:
        ask_people(hit.iloc[0], shot)
    else:
        say(src + f"Базада айнан шу номли {len(hit)} та аптека бор. Қайси бири?", pick_kb(hit))


if __name__ == "__main__":
    from checks import TYPES
    OWNER = chat_id()
    try:
        main()
    except Exception as e:
        import traceback
        print("::error::" + traceback.format_exc()[-900:].replace(chr(10), " | "))
        say(f"❗️ Хатолик: {esc(str(e)[:300])}")
        raise
