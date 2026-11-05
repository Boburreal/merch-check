"""Baza bot: managers in the "Sales ASKLEPIY" group ask to add pharmacy branches (name + INN + Filial N).
The bot finds the main pharmacy by INN in Sales, checks who holds it, asks the requester when a working
manager holds it, then adds the branches as INN-1, INN-2 ... attached to the requester.

BAZA_LIVE != "1"  -> test mode: nothing is saved in Sales and nothing is written in the group;
                     Bobur gets a private report of what would have been done.
Runs on GitHub Actions (baza.yml), started by the Cloudflare Worker for each relevant group message."""
import html as H
import json, os, re, sys, time, traceback
import pandas as pd
import requests

import store
from sales import login, BASE

TOKEN = os.environ.get("BAZA_BOT_TOKEN", "")
LIVE = os.environ.get("BAZA_LIVE") == "1"
PROJ = {"ТП": 1, "МП": 4}
PNAME = {1: "Торговые представители", 4: "Аптечные сети"}
INN_RE = re.compile(r"(?<!\d)(\d{9})(?!\d)")
YES_NO = re.compile(r"\b(йўқ|йук|йок|yo'?q|yoq|нет|net|ishlamayman|ишламайман|керак эмас|kerak emas)\b", re.I)


# ------------------------------------------------------------------ telegram
def tg(method, **data):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=data, timeout=60).json()
        if not r.get("ok"):
            print(f"::warning::tg {method}: {str(r)[:200]}")
        return r
    except Exception as e:
        print(f"::warning::tg {method} failed: {e}")
        return {}


def bobur():
    d = store.load("chat")
    return int(d["chat_id"].iloc[0]) if len(d) else None


def to_bobur(text):
    print("::notice::" + re.sub(r"<[^>]+>", "", text).replace("\n", "%0A")[:3000])
    c = bobur()
    if c:
        tg("sendMessage", chat_id=c, text=text, parse_mode="HTML", disable_web_page_preview=True)


def esc(s):
    return H.escape(str(s or ""), quote=False)


# ------------------------------------------------------------------ parsing the request
def parse(text: str):
    """[{'name', 'inn', 'n'}]: n = how many branches are asked for that INN (lines 'Filial 1', 'Filial 2' ...)."""
    lines = [l.strip() for l in (text or "").splitlines()]
    out = []
    for i, l in enumerate(lines):
        m = INN_RE.search(l)
        if not m:
            continue
        name = re.sub(r"(?i)\b(inn|инн|stir|стир)\b[:\s]*", "", l).replace(m.group(1), "").strip(" :-–—,.")
        if not name:
            for j in range(i - 1, max(-1, i - 3), -1):
                if lines[j] and not INN_RE.search(lines[j]) and not re.match(r"(?i)^(assalom|ассалом|salom|салом)", lines[j]):
                    name = lines[j]; break
        n, nums = 0, []
        k0 = re.search(r"(?i)(\d{1,2})\s*(ta|та)?\s*(filial|филиал)", l.replace(m.group(1), ""))
        if k0:
            n += int(k0.group(1))
            name = re.sub(r"(?i)\d{1,2}\s*(ta|та)?\s*(filial|филиал)\w*", "", name).strip(" :-–—,.")
        for l2 in lines[i + 1:]:
            if INN_RE.search(l2):
                break
            f = re.match(r"(?i)^\s*(filial|филиал|fil|фил)\w*\s*[№#-]?\s*(\d+)?", l2)
            if f:
                n += 1
                if f.group(2):
                    nums.append(int(f.group(2)))
            else:
                k = re.search(r"(?i)(\d+)\s*(ta|та)?\s*(filial|филиал)", l2)
                if k:
                    n += int(k.group(1))
        out.append({"name": name, "inn": m.group(1), "n": max(n, len(nums), 1)})
    return out


# ------------------------------------------------------------------ people
LAT = [("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("o'", "ў"), ("g'", "ғ"), ("ts", "ц"), ("kh", "х"),
       ("a", "а"), ("b", "б"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "х"), ("i", "и"), ("j", "ж"),
       ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("q", "қ"), ("r", "р"), ("s", "с"),
       ("t", "т"), ("u", "у"), ("v", "в"), ("x", "х"), ("y", "й"), ("z", "з")]
FOLD = str.maketrans({"ў": "у", "қ": "к", "ғ": "г", "ҳ": "х", "ё": "е", "й": "и", "ы": "и", "э": "е", "ъ": "", "ь": ""})


def cyr(s: str) -> str:
    s = str(s).lower().replace("`", "'").replace("’", "'").replace("ʻ", "'")
    out, i = "", 0
    while i < len(s):
        for a, b in LAT:
            if s.startswith(a, i):
                out += b; i += len(a); break
        else:
            out += s[i]; i += 1
    return out.translate(FOLD)


def _txt(v):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(v or ""))).strip()


def sales_users(s, fresh=False):
    """All users of both projects (cached for 12 h: reading them switches the Sales project)."""
    c = store.load("baza_users")
    if len(c) and not fresh and time.time() - float(c["_t"].iloc[0]) < 12 * 3600:
        c["active"] = c["active"] == "True"
        return c.drop(columns="_t")
    df = _sales_users(s)
    store.save("baza_users", df.assign(_t=str(time.time())))
    return df


def _sales_users(s):
    """All users of both projects: id, name, active, category, group (ТП/МП), telegram id."""
    import sales
    rows = []
    for p in (1, 4):
        sales.switch_project(s, p)
        u = s.get(BASE + "/lists/users", timeout=60)
        tok = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", u.text).group(1)
        data = {"draw": 1, "start": 0, "length": 3000, "search[value]": "", "search[regex]": "false"}
        for i in range(17):
            data[f"columns[{i}][data]"] = i
        j = s.post(BASE + "/lists/users", data=data, timeout=300, headers={
            "X-CSRF-TOKEN": tok, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json()
        for r in j.get("data", []):
            rows.append({"id": str(r["id"]), "name": _txt(r.get("name")), "active": _txt(r.get("active")) == "Да",
                         "category": _txt(r.get("category_id")), "role": _txt(r.get("roles")),
                         "tg": _txt(r.get("telegram_user_id")), "project": p})
    sales.restore(s)
    df = pd.DataFrame(rows)
    # one row per person; МП if the person is in the Аптечные сети project
    df = df.sort_values("project", ascending=False).drop_duplicates("id")
    return df


CAT_ID = {"Торг Пред": 559, "Рег.Роп": 565, "Медицинский представитель": 566, "Региональный менеджер": 567,
          "Торг Пред Рус": 568, "Рег.Роп РУС": 572, "Фармацевтический представитель узб.": 575}


def who(users: pd.DataFrame, frm: dict):
    """Sales user of the Telegram sender: saved link, Telegram id in Sales, or a unique name match."""
    links = store.load("baza_links")
    if len(links):
        hit = links[links["tg"] == str(frm["id"])]
        if len(hit):
            u = users[users["id"] == hit["user"].iloc[-1]]
            if len(u):
                return u.iloc[0], "saved"
    u = users[users["tg"] == str(frm["id"])]
    if len(u):
        return u.iloc[0], "sales"
    toks = [cyr(t) for t in re.split(r"[\s.]+", f"{frm.get('first', '')} {frm.get('last', '')}") if len(t) >= 2]
    act = users[users["active"]]
    words = act["name"].map(lambda n: [w for w in cyr(re.sub(r"\([^)]*\)", " ", n)).split() if len(w) >= 2])
    if toks:
        full = act[words.map(lambda ws: all(any(w.startswith(t) for w in ws) for t in toks))]
        if len(full) == 1:
            return full.iloc[0], "name"
        first = act[words.map(lambda ws: any(w == toks[0] or (len(toks[0]) >= 4 and w.startswith(toks[0])) for w in ws))]
        if len(first) == 1:
            return first.iloc[0], "name"
        if len(first) > 1 and len(toks) > 1:     # "Muslima M" -> surname starting with M among the Muslimas
            ini = first[words[first.index].map(lambda ws: any(w.startswith(toks[1][:1]) for w in ws if w != toks[0]))]
            if len(ini) == 1:
                return ini.iloc[0], "name"
    return None, "unknown"


def group_of(u) -> str:
    return "МП" if int(u["project"]) == 4 else "ТП"


# ------------------------------------------------------------------ Sales "add company" wizard (Livewire)
class Wizard:
    def __init__(self, s):
        self.s = s
        r = s.get(BASE + "/lists/companies/add_company", timeout=60)
        self.csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
        self.upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
        self.snap = next(H.unescape(x) for x in re.findall(r'wire:snapshot="([^"]+)"', r.text)
                         if '"step":"inn"' in H.unescape(x))
        self.effects = {}

    def call(self, updates=None, method=None, params=None):
        body = {"_token": self.csrf, "components": [{"snapshot": self.snap, "updates": updates or {},
                                                      "calls": [{"path": "", "method": method, "params": params or []}] if method else []}]}
        x = self.s.post(self.upd, json=body, timeout=120, headers={
            "X-Livewire": "true", "Content-Type": "application/json", "X-CSRF-TOKEN": self.csrf,
            "Referer": BASE + "/lists/companies/add_company"})
        x.raise_for_status()
        c = x.json()["components"][0]
        self.snap, self.effects = c["snapshot"], c.get("effects", {})
        return json.loads(self.snap)

    @property
    def data(self):
        return json.loads(self.snap)["data"]

    def errors(self):
        return json.loads(self.snap)["memo"].get("errors") or {}


def unarr(v):
    """Livewire keeps arrays as [value, {"s": "arr"}]."""
    if isinstance(v, list) and len(v) == 2 and isinstance(v[1], dict) and v[1].get("s") == "arr":
        return [unarr(x) for x in v[0]] if isinstance(v[0], list) else unarr(v[0])
    if isinstance(v, dict):
        return {k: unarr(x) for k, x in v.items()}
    if isinstance(v, list):
        return [unarr(x) for x in v]
    return v


def lookup(s, inn: str):
    """('found', fields) | ('create', None) | (step, None)."""
    w = Wizard(s)
    d = w.call({"inn": inn}, "next")["data"]
    f = unarr(d.get("fields"))
    f = f[0] if isinstance(f, list) and f and isinstance(f[0], dict) else f
    return d.get("step"), (f if d.get("step") == "found" else None), d


def add(s, inn, name, region_id, project, user_id, category_id):
    w = Wizard(s)
    d = w.call({"inn": inn}, "next")["data"]
    if d.get("step") != "create":
        return False, f"INN {inn} бўш эмас ({d.get('step')})"
    w.call({}, "addPharmUser")
    upd = {"fields.is_active": True, "fields.name": name, "fields.projects": [str(project)],
           "fields.users.0.user_id": str(user_id)}
    if region_id:
        upd["fields.region_id"] = str(region_id)
    if category_id:
        upd["fields.users.0.category_id"] = str(category_id)
    w.call(upd, "save")
    err = w.errors()
    if err:
        return False, "; ".join(f"{k}: {' '.join(v) if isinstance(v, list) else v}" for k, v in err.items())
    # verify
    st, f, _ = lookup(s, inn)
    return (st == "found"), ("" if st == "found" else f"сақлангандан кейин топилмади ({st})")


# ------------------------------------------------------------------ the decision
def plan(s, users, req, item):
    """Everything the bot would do for one pharmacy of a request."""
    inn, n = item["inn"], item["n"]
    st, main, raw = lookup(s, inn)
    p = {"inn": inn, "asked_name": item["name"], "n": n}
    if st == "network":
        p["status"] = "network"
        p["dist"] = raw.get("distributerName")
        p["network"] = [{"id": c.get("id"), "name": c.get("name"), "in_project": c.get("in_project")}
                        for c in (unarr(raw.get("networkCompanies")) or []) if isinstance(c, dict)]
        return p
    if st != "found":
        p["status"], p["step"] = "no_main", st
        print(f"::warning::INN {inn}: step={st} data={json.dumps({k: v for k, v in raw.items() if k != 'fields'}, ensure_ascii=False)[:800]}")
        return p
    p["main_name"] = main.get("name") or item["name"]
    p["region_id"] = main.get("region_id")
    p["main_projects"] = [int(x) for x in (main.get("projects") or [])]
    holders = []
    for h in main.get("users") or []:
        uid = str(h.get("user_id")) if isinstance(h, dict) else ""
        u = users[users["id"] == uid]
        holders.append({"id": uid, "name": u["name"].iloc[0] if len(u) else f"#{uid}",
                        "active": bool(u["active"].iloc[0]) if len(u) else False,
                        "group": group_of(u.iloc[0]) if len(u) else ""})
    p["holders"] = holders
    # ТП and МП may work the same pharmacy: ask only when a working manager of the SAME group holds it
    others = [h for h in holders if h["active"] and h["id"] != str(req["id"]) and h["group"] == group_of(req)]
    p["ask"] = [h["name"] for h in others]
    # free INN suffixes
    free, k, existing = [], 1, []
    while len(free) < n and k < 30:
        st2, f2, _ = lookup(s, f"{inn}-{k}")
        if st2 == "create":
            free.append(k)
        elif st2 == "found":
            existing.append({"inn": f"{inn}-{k}", "name": f2.get("name"),
                             "users": [users[users["id"] == str(h.get("user_id"))]["name"].iloc[0]
                                       if len(users[users["id"] == str(h.get("user_id"))]) else str(h.get("user_id"))
                                       for h in (f2.get("users") or []) if isinstance(h, dict)]})
        k += 1
    p["existing"] = existing
    grp = group_of(req)
    proj = PROJ[grp]
    suffix = ""
    if p["main_projects"] and proj not in p["main_projects"]:
        suffix = f" ({grp})"                 # main pharmacy lives only in the other category
    base = (item["name"] or p["main_name"]).strip()
    p["new"] = [{"inn": f"{inn}-{k}", "name": f"{base} filial {k}{suffix}"} for k in free]
    p["project"], p["group"] = proj, grp
    p["category_id"] = CAT_ID.get(req["category"])
    p["status"] = "ask" if others else "add"
    return p


def describe(p):
    if p["status"] == "network":
        lst = "; ".join(f"{esc(c['name'])} (ID {c['id']})" for c in p["network"][:8])
        return (f"🔗 ИНН <code>{p['inn']}</code> ({esc(p['asked_name'])}) — Sales бу ИННни «{esc(p['dist'])}» тармоғи деб кўрсатяпти, "
                f"филиаллари бир ИНН билан бошқа лойиҳаларда бор: {lst}. Автомат қўшмадим — қўлда кўриб чиқинг.")
    if p["status"] == "no_main":
        return f"❗️ ИНН <code>{p['inn']}</code> ({esc(p['asked_name'])}) — базада бош аптека топилмади, қўшилмади."
    h = ", ".join(f"{esc(x['name'])} ({x.get('group') or '?'}{'' if x['active'] else ', ишдан кетган'})" for x in p["holders"]) or "ҳеч ким"
    t = [f"🏥 <b>{esc(p['main_name'])}</b> — ИНН <code>{p['inn']}</code>",
         f"   Бош аптека: {PNAME.get(p['main_projects'][0], '') if len(p['main_projects']) == 1 else 'иккала база'}; бириктирилган: {h}"]
    if p["existing"]:
        t.append("   Олдин қўшилган филиаллар: " + "; ".join(f"{e['inn']} ({esc(', '.join(e['users']) or '—')})" for e in p["existing"]))
    if p["status"] == "ask":
        t.append(f"   ❓ Аввал сўралади: «{esc(', '.join(p['ask']))} базасида турибди»")
    for nb in p["new"]:
        t.append(f"   ➕ {nb['inn']} — «{esc(nb['name'])}», {PNAME[p['project']]}")
    return "\n".join(t)


# ------------------------------------------------------------------ handlers
def pending_load():
    return store.load("baza_pending")


def pending_save(df):
    store.save("baza_pending", df)


def execute(s, users, req, plans, chat, reply_to):
    done, bad = [], []
    for p in plans:
        if p["status"] in ("no_main", "network"):
            continue
        for nb in p["new"]:
            ok, why = add(s, nb["inn"], nb["name"], p["region_id"], p["project"], req["id"], p["category_id"])
            (done if ok else bad).append(f"{nb['inn']} {nb['name']}" + ("" if ok else f" — {why}"))
            print(f"action=add {nb['inn']} ok={ok} {why}")
    if done:
        tg("sendMessage", chat_id=chat, text="+", reply_to_message_id=reply_to)
    to_bobur(f"✅ <b>{esc(req['name'])}</b> заявкаси бажарилди:\n" + "\n".join("➕ " + esc(x) for x in done)
             + ("\n\n❗️ Қўшилмади:\n" + "\n".join(esc(x) for x in bad) if bad else ""))


def on_request(u):
    items = parse(u.get("text", ""))
    if not items:
        return
    s = login()
    users = sales_users(s)
    frm = {"id": u.get("from_id"), "first": u.get("first", ""), "last": u.get("last", "")}
    req, how = who(users, frm)
    if req is None:
        to_bobur(f"❓ Заявка ёзган одамни Sales'дан топа олмадим: <b>{esc(frm['first'])} {esc(frm['last'])}</b> "
                 f"(tg {frm['id']}).\n\n{esc(u.get('text', ''))[:800]}\n\nКимлигини ёзиб юборинг: <code>/link {frm['id']} Фамилия Исм</code>")
        return
    plans = [plan(s, users, req, it) for it in items]
    mode = "🧪 СИНОВ (Sales'га ёзилмади)" if not LIVE else "📥 Заявка"
    head = (f"{mode}: <b>{esc(req['name'])}</b> "
            f"({group_of(req)}, {esc(req['category'])}){'' if how != 'name' else ' — исми бўйича топилди'}")
    body = "\n\n".join(describe(p) for p in plans)
    ask = [p for p in plans if p["status"] == "ask"]
    if not LIVE:
        to_bobur(head + "\n\n" + body)
        return
    if ask:
        names = sorted({n for p in ask for n in p["ask"]})
        q = ("Ассалому алайкум! " + "; ".join(f"{p['main_name']} ({p['inn']})" for p in ask) +
             f" — {', '.join(names)} базасида турибди. Сиз шу аптекада ишлайсизми? Жавобни шу хабарга reply қилиб ёзинг.")
        r = tg("sendMessage", chat_id=u["chat"], text=q, reply_to_message_id=u["mid"])
        mid = (r.get("result") or {}).get("message_id")
        pend = pending_load()
        row = pd.DataFrame([{"bot_mid": str(mid), "chat": str(u["chat"]), "req_mid": str(u["mid"]), "from_id": str(frm["id"]),
                             "user": str(req["id"]), "plans": json.dumps(plans, ensure_ascii=False), "when": time.strftime("%Y-%m-%d %H:%M")}])
        pending_save(pd.concat([pend, row], ignore_index=True) if len(pend) else row)
        to_bobur(head + "\n\n" + body + "\n\n⏳ Менежердан жавоб кутилмоқда.")
        ready = [p for p in plans if p["status"] == "add"]
        if ready:
            execute(s, users, req, ready, u["chat"], u["mid"])
        return
    to_bobur(head + "\n\n" + body)
    execute(s, users, req, plans, u["chat"], u["mid"])


def on_reply(u):
    pend = pending_load()
    if not len(pend):
        return
    hit = pend[(pend["bot_mid"] == str(u.get("reply_mid"))) & (pend["from_id"] == str(u.get("from_id")))]
    if not len(hit):
        return
    row = hit.iloc[-1]
    pending_save(pend[pend["bot_mid"] != row["bot_mid"]])
    plans = [p for p in json.loads(row["plans"]) if p["status"] == "ask"]
    s = login()
    users = sales_users(s)
    req = users[users["id"] == row["user"]].iloc[0]
    if YES_NO.search(u.get("text", "")):
        to_bobur(f"❌ <b>{esc(req['name'])}</b> «{esc(u.get('text', ''))[:200]}» деб жавоб берди — филиаллар қўшилмади.")
        return
    to_bobur(f"💬 <b>{esc(req['name'])}</b> жавоби: «{esc(u.get('text', ''))[:300]}»")
    # INN suffixes may have been taken meanwhile - re-plan
    plans = [plan(s, users, req, {"inn": p["inn"], "name": p["asked_name"], "n": p["n"]}) for p in plans]
    for p in plans:
        if p["status"] == "ask":
            p["status"] = "add"
    execute(s, users, req, plans, int(row["chat"]), int(row["req_mid"]))


def on_private(u):
    t = (u.get("text") or "").strip()
    me = bobur()
    if me and str(u.get("chat")) != str(me):
        tg("sendMessage", chat_id=u["chat"], text="Бу бот «Sales ASKLEPIY» гуруҳидаги заявкалар учун.")
        return
    m = re.match(r"^/link\s+(\d+)\s+(.+)$", t)
    if m:
        s = login()
        users = sales_users(s)
        toks = [cyr(x) for x in m.group(2).split()]
        hit = users[users["name"].map(lambda n: all(any(w.startswith(x) for w in cyr(n).split()) for x in toks))]
        if len(hit) != 1:
            tg("sendMessage", chat_id=u["chat"], text=f"Топилди: {len(hit)} та. Фамилия ва исмни аниқроқ ёзинг.")
            return
        links = store.load("baza_links")
        row = pd.DataFrame([{"tg": m.group(1), "user": hit["id"].iloc[0]}])
        store.save("baza_links", pd.concat([links, row], ignore_index=True) if len(links) else row)
        tg("sendMessage", chat_id=u["chat"], text=f"✅ tg {m.group(1)} = {hit['name'].iloc[0]}")
        return
    tg("sendMessage", chat_id=u["chat"], parse_mode="HTML",
       text="Бот ишлаяпти. " + ("<b>Ишчи режим</b>: заявкалар Sales'га қўшилади." if LIVE else
                                "<b>Синов режими</b>: Sales'га ҳеч нарса ёзилмайди, натижани сизга юбораман."))


def main():
    u = json.loads(os.environ["UPDATE"])
    print(f"::notice::kind={u.get('kind')} live={LIVE}")
    if u.get("kind") == "private":
        on_private(u)
    elif u.get("kind") == "reply":
        on_reply(u)
    elif u.get("kind") == "request":
        on_request(u)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        print("::error::" + tb.replace("\n", "%0A")[-3000:])
        to_bobur("⚠️ Baza bot хатоси:\n<code>" + esc(tb[-1500:]) + "</code>")
        sys.exit(1)
