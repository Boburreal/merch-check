"""Telegram bot actions. One run per incoming update (Cloudflare Worker -> bot.yml -> this file).
Screenshot / text with a pharmacy  -> find it in the base, show 3-month visit history, ask "delete location?"
Button "Ўчир"                      -> empty the pharmacy's location in Sales (all other fields kept), verify.
Only Bobur's chat (stored encrypted) is served; nothing is deleted without his button press."""
import base64, datetime as dt, difflib, json, os, re
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


def search(c, name, region='', inn=''):
    if inn and 'inn' in c:
        hit = c[c['inn'].astype(str) == str(inn)]
        if len(hit):
            return [(1.0, r) for _, r in hit.iterrows()]
    q = norm(name)
    if not q:
        return []
    rg = norm(region)
    sc = []
    for _, r in c.iterrows():
        s = difflib.SequenceMatcher(None, q, r.n).ratio()
        if q in r.n or (r.n and r.n in q):
            s = max(s, 0.85)
        if rg and rg[:5] in norm(r.region + ' ' + r.district):
            s += 0.05
        sc.append((s, r))
    sc.sort(key=lambda x: -x[0])
    return sc[:6]


# ---------------------------------------------------------------- history
def visits_for(row):
    from export import fetch
    d2 = dt.datetime.now(TZ).date()
    d1 = d2 - dt.timedelta(days=DAYS)
    out = []
    for proj, who in ((1, 'ТП'), (4, 'МП')):
        v = fetch(proj, d1, d2)
        if not len(v):
            continue
        obj = v['Контр-агент/Врач'].fillna('')
        v['obj'] = obj.str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip()
        v['reg'] = obj.str.extract(r'\(([^()]*)\)\s*$')[0].fillna('')
        m = v[v['obj'].map(norm) == row.n]
        if row.region and len(m):
            same = m[m['reg'].map(norm).str[:5] == norm(row.region)[:5]]
            m = same if len(same) else m
        m = m.assign(grp=who, emp=m['Фарм. пред'].str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip())
        out.append(m)
    v = pd.concat(out) if out else pd.DataFrame()
    if len(v):
        v['t'] = pd.to_datetime(v['Время завершения визита'], format='%d.%m.%Y %H:%M', errors='coerce')
        v = v.sort_values('t', ascending=False)
    return v, d1, d2


def report(row, shot=None):
    v, d1, d2 = visits_for(row)
    lat, lon = pd.to_numeric(row.lat, errors='coerce'), pd.to_numeric(row.lon, errors='coerce')
    L = [f"🏥 <b>{esc(row['name'])}</b>  (ID {row.id})",
         f"📍 {esc(row.region)}{', ' + esc(row.district) if row.district else ''}"]
    if row.reps:
        L.append(f"👤 Бириктирилган: {esc(row.reps)}")
    if pd.notna(lat):
        L.append(f"🗺 Локация: <a href=\"https://yandex.uz/maps/?pt={lon},{lat}&z=18&l=map\">{lat:.6f}, {lon:.6f}</a>")
    else:
        L.append("🗺 Локация: <b>йўқ</b> (базада ҳозир ўчирилган)")
    lg = store.load('loc_log')
    if len(lg):
        lg = lg[lg['ID'].astype(str) == str(row.id)]
        if len(lg):
            L.append("\n🔁 <b>Локация ўзгаришлари</b> (кузатув бошланганидан):")
            for r in lg.tail(8).itertuples(index=False):
                L.append(f" • {r[1]} — {r[7]}")
    same = (companies()['n'] == row.n).sum()
    if same > 1:
        L.append(f"\nℹ️ Базада шу номли {same} та аптека бор — визитлар ҳудуди бўйича ажратилди.")
    L.append(f"\n📊 <b>Охирги 3 ой ({d1:%d.%m}–{d2:%d.%m.%Y}): {len(v)} та визит</b>")
    if len(v):
        g = v.groupby(['grp', 'emp']).agg(n=('t', 'size'), last=('t', 'max'), first=('t', 'min')).reset_index()
        for r in g.sort_values('n', ascending=False).itertuples():
            L.append(f" • {esc(r.emp)} ({r.grp}) — <b>{r.n}</b> марта, {r.first:%d.%m}…{r.last:%d.%m.%Y}")
        L.append("\n🕒 Охирги визитлар:")
        for r in v.head(10).itertuples():
            L.append(f" {r.t:%d.%m %H:%M} — {esc(r.emp)} ({r.grp})")
        months = v['t'].dt.strftime('%m.%Y').value_counts().sort_index()
        L.append("📅 Ойлар бўйича: " + ", ".join(f"{k}: {n}" for k, n in months.items()))
    else:
        L.append(" Бу даврда ҳеч ким визит қилмаган.")
    offs = []
    for grp in ('tp', 'mp'):
        o = store.load(f'offenses_{grp}')
        if len(o):
            o = o[o['obj'].map(norm) == row.n]
            offs += [f"{r.date[8:10]}.{r.date[5:7]} {esc(r.who)}: {TYPES.get(r.type, r.type)}" for r in o.itertuples()]
    if offs:
        L.append("\n⚠️ <b>Шу аптекадаги шубҳали визитлар:</b>")
        L += [" • " + x for x in offs[-8:]]
    if shot:
        L.append(f"\n📩 Скриншотда: {esc(shot.get('sender') or '—')}: «{esc(shot.get('request') or '')}»")
        snd = norm(shot.get('sender', ''))
        if snd and len(v):
            hit = v[v['emp'].map(norm).str.contains(snd.split()[0], regex=False)] if snd.split() else v[:0]
            L.append(f"   Сўраган ходим бу аптекага 3 ойда {len(hit)} марта борган." if len(hit)
                     else "   Сўраган ходим бу аптекага 3 ойда борган эмас (ёки исми мос келмади).")
    kb = None
    if pd.notna(lat):
        L.append("\nЛокацияни ўчирайми?")
        kb = [[{"text": "🗑 Ҳа, локацияни ўчир", "callback_data": f"del:{row.id}"},
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
    from sales import login, BASE
    s = login()
    url = f"{BASE}/lists/companies/{cid}/edit"
    before = serialize(s.get(url, timeout=60).text)
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
        act, _, cid = u["cb"].partition(":")
        tg("editMessageReplyMarkup", chat_id=OWNER, message_id=u["mid"], reply_markup={"inline_keyboard": []})
        cid = int(cid)
        if act == "no":
            say("❌ Бекор қилинди, локацияга тегилмади.")
        elif act == "pick":
            c = companies()
            say("⏳ Охирги 3 ойлик визитлар йиғилмоқда (1–2 дақиқа)...")
            report(c[c.id == cid].iloc[0])
        elif act == "del":
            say("⏳ Локация ўчирилмоқда...")
            name, old, st = delete_location(cid)
            if st == "ok":
                say(f"✅ <b>{esc(name)}</b> (ID {cid}) — локация ўчирилди.\nЭски координата: <code>{esc(old)}</code>\n"
                    "Бошқа маълумотлари ўзгармади (текширилди). Кимдир янги локация қўйса, сизга хабар бераман.")
            elif st == "already":
                say(f"ℹ️ <b>{esc(name)}</b> (ID {cid}) — локацияси аллақачон бўш экан.")
            elif st.startswith("changed:"):
                say(f"⚠️ <b>{esc(name)}</b> (ID {cid}) — локация ўчди, лекин бошқа майдонлар ҳам ўзгарган кўринди: "
                    f"{esc(st[8:])}. Илтимос, Sales'да шу аптекани текшириб кўринг.")
            else:
                say(f"❗️ <b>{esc(name)}</b> (ID {cid}) — ўчмади: {esc(st)}. Қўлда текшириб кўринг.")
        return
    text = (u.get("text") or "").strip()
    if text.startswith("/start") or text.lower() in ("/help", "ёрдам", "yordam"):
        say("Салом! Аптека локациясини ўчириш учун гуруҳдаги хабар скриншотини ташланг "
            "(ёки аптека номини / ID рақамини ёзинг). Мен 3 ойлик визитлар тарихини кўрсатаман ва "
            "фақат сиз «Ҳа, ўчир» тугмасини боссангиз ўчираман.")
        return
    shot = None
    c = companies()
    if u.get("photo"):
        say("⏳ Скриншот ўқилмоқда...")
        shot = read_screenshot(u["photo"])
        q, reg, inn = shot.get("pharmacy", ""), shot.get("region", "") + " " + shot.get("address", ""), shot.get("inn", "")
        if not q and not inn:
            say("Скриншотдан аптека номини топа олмадим. Илтимос, номини ёки ID сини ёзинг.")
            return
    elif text.isdigit() and int(text) in set(c.id):
        say("⏳ Охирги 3 ойлик визитлар йиғилмоқда (1–2 дақиқа)...")
        report(c[c.id == int(text)].iloc[0])
        return
    elif text:
        q, reg, inn = (u.get("caption") or text), "", ""
    else:
        return
    found = search(c, q, reg, inn)
    head = f"🔎 Скриншотдан: <b>{esc(q)}</b> {esc(reg.strip())}\n" if shot else ""
    if not found or found[0][0] < 0.55:
        say(head + "Базадан мос аптека топилмади. Номини аниқроқ ёки ID сини ёзинг.")
        return
    best = found[0]
    if best[0] >= 0.9 and (len(found) == 1 or found[1][0] < best[0] - 0.08):
        say(head + "⏳ Аптека топилди, охирги 3 ойлик визитлар йиғилмоқда (1–2 дақиқа)...")
        report(best[1], shot)
        return
    kb = [[{"text": f"{r['name'][:38]} · {r.region[:12]} · ID {r.id}", "callback_data": f"pick:{r.id}"}]
          for s, r in found if s >= 0.5][:6]
    say(head + "Қайси аптека? Танланг:", kb)


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
