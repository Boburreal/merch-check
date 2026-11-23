"""Telegram bot actions. One run per incoming update (Cloudflare Worker -> bot.yml -> this file).
Only Bobur's chat (stored encrypted) is served. Commands: /start (help), /tekshir (staff/region check).
Pharmacy location deletion was removed on 09.11.2026 (Bobur's request)."""
import json, os, re
import requests

from telegram import API, chat_id

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


def gh_dispatch(wf, inputs):
    """Trigger another workflow in this same repo via the job's own GITHUB_TOKEN (no extra secret needed)."""
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        return False, "GITHUB_TOKEN йўқ (bot.yml'да permissions/actions: write қўшилганми?)"
    r = requests.post(f"https://api.github.com/repos/Boburreal/merch-check/actions/workflows/{wf}/dispatches",
                      headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
                      json={"ref": "main", "inputs": inputs}, timeout=30)
    return r.status_code == 204, f"{r.status_code} {r.text[:150]}"


def arxiv(text):
    """/arxiv 10.2026 (yoki 2026-10) — o'sha oyning yakuniy ТП/МП визит va Аудиозаписи файлларини qayta yuboradi."""
    import calendar
    m = re.search(r'(\d{1,2})[.\-/](\d{4})\b', text) or re.search(r'(\d{4})-(\d{1,2})\b', text)
    if not m:
        say("Қайси ойни қайта чиқарай? Масалан: <code>/arxiv 10.2026</code> (Октябрь 2026)")
        return
    mm, yyyy = (int(m.group(1)), int(m.group(2))) if len(m.group(2)) == 4 else (int(m.group(2)), int(m.group(1)))
    if not (1 <= mm <= 12):
        say("Ой рақами 1-12 оралиғида бўлиши керак, масалан: <code>/arxiv 10.2026</code>")
        return
    # "update" rejimi (bir kun oldinga TODAY bilan) — oyning oxirgi kuni uchun ertasi kuni (08:30dagiga o'xshab)
    # kech kiritilgan vizitlar bilan to'liq yangilangan holatni beradi, оddiy "daily" kabi soat-кесик эмас
    nxt_y, nxt_m = (yyyy, mm + 1) if mm < 12 else (yyyy + 1, 1)
    say(f"⏳ {mm:02d}.{yyyy} ойи учун ТП/МП визит (кеч киритилган визитлар билан янгиланган) ва Аудиозаписи файллари "
        f"қайта тайёрланяпти — бир неча дақиқа кетиши мумкин, тайёр бўлгач ўзим юбораман.")
    ok1, msg1 = gh_dispatch("report.yml", {
        "mode": "update", "today": f"{nxt_y}-{nxt_m:02d}-01",
        "no_regroup": "1" if (yyyy, mm) < (2026, 11) else ""})
    ok2, msg2 = gh_dispatch("az.yml", {"mode": "resend_month", "month": f"{mm:02d}", "year": str(yyyy)})
    if not (ok1 and ok2):
        say(f"❗️ Ишга туширишда хатолик: {esc(msg1 if not ok1 else msg2)}")


def ask_period(tg_):
    import check
    t = (tg_[0], int(tg_[1:]))
    kb = [[{"text": nm, "callback_data": f"ck:{k}:{tg_}"} for k, nm in list(check.PERIODS.items())[:2]],
          [{"text": nm, "callback_data": f"ck:{k}:{tg_}"} for k, nm in list(check.PERIODS.items())[2:]]]
    say(f"{esc(check.label(t))}\nҚайси давр бўйича текширамиз?", kb)


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
        if act in ("ck", "cks"):             # manager check: ck:<period>:<r|p><i>  /  cks:<r|p><i> (choose period)
            import check
            if act == "cks":
                return ask_period(rest)
            code, _, tg_ = rest.partition(":")
            t = (tg_[0], int(tg_[1:]))
            say(f"⏳ {esc(check.label(t))} — {check.PERIODS[code].lower()} текширилмоқда. "
                "Мерч фотолари ИИ да текширилгани учун 2–20 дақиқа кетиши мумкин, файл тайёр бўлса ўзим юбораман.")
            return check.run(t, code)
        return
    text = (u.get("text") or "").strip()
    if text.startswith("/start") or text.lower() in ("/help", "ёрдам", "yordam"):
        # the bot menu is for visit analytics only (removes commands another program left on this bot)
        tg("setMyCommands", commands=[{"command": "start", "description": "Ёрдам"},
                                      {"command": "tekshir", "description": "Ходим ёки ҳудуд жамоасини текшириш"},
                                      {"command": "arxiv", "description": "Ўтган ойнинг якуний файлларини қайта юбориш"}])
        say("📊 <b>Визит аналитикаси боти</b>\n\n"
            "<b>Ўзи юборади:</b>\n"
            "• ҳар куни ~17:45 — ТП «Факт визит и мерч», МП визит файллари (ой бошидан) ва «Аудиозаписи» файли\n"
            "• ҳар куни ~09:00 — кечаги кун тўлиқ янгиланган (кечиккан визитлар, мерч, аудио изоҳлари)\n"
            "• якшанба 23:00 — ҳафталик тўлиқ таҳлил (ТП ва МП)\n"
            "• ойнинг 1-санаси 09:00 — ойлик таҳлил\n"
            "Файлларда: шубҳали визитлар, мерч (Витрина/Касса), «ТП × аптека», «Аптека × ТП», «Бир нуқтада 7+ аптека».\n\n"
            "<b>Ходим / жамоани текшириш:</b> <code>/tekshir Фамилия</code> ёки <code>/tekshir Вилоят</code> — "
            "давр (ҳафта/ой) танлайсиз, шубҳали визитлар, мерч ва аптека қамрови бўйича файл келади.\n\n"
            "<b>Ўтган ойнинг якуний файлларини қайта олиш:</b> <code>/arxiv 10.2026</code> — ўша ойнинг ТП «Факт визит и мерч», "
            "МП визит ва Аудиозаписи (ТП+МП) файлларини қайта юборади.")
        return
    low = text.lower()
    if low.startswith(("/arxiv", "/архив", "arxiv", "архив")):
        return arxiv(text)
    if low.startswith(("/tekshir", "/текшир", "tekshir", "текшир")):
        import check
        q = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        if not q:
            say("Кимни текширамиз? Ходим фамилиясини ёки ҳудудни ёзинг, масалан:\n"
                "<code>/tekshir Азимов</code> — битта ходим\n<code>/tekshir Самарканд</code> — ҳудуд жамоаси (ТП+МП)")
            return
        ts = check.resolve(q)
        if not ts:
            say(f"«{esc(q)}» бўйича ходим ҳам, ҳудуд ҳам топилмади. Фамилияни ёки вилоят номини ёзинг.")
        elif len(ts) == 1:
            ask_period(f"{ts[0][0]}{ts[0][1]}")
        else:
            say("Қайси бири?", [[{"text": check.label(t)[:60], "callback_data": f"cks:{t[0]}{t[1]}"}] for t in ts[:10]])
        return
    say("Бот фақат ҳисобот юборади, <code>/tekshir Фамилия</code> ва <code>/arxiv ОЙ.ЙИЛ</code> буйруқларини тушунади. Ёрдам: /start")


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
