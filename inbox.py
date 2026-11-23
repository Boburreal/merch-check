"""Ботнинг Excel файлини «Asklepiy Визитлар» саҳифаси учун Cloudflare D1 (vizit-inbox) га юклайди.

telegram.send_file() ҳар бир файлни юборгандан кейин push_file(path) ни чақиради.
Файл номи бўйича тури: «Факт визит и мерч…» = tp, «МП визит…» = mp,
«Аудиозаписи МП…» = au_mp, «Аудиозаписи…» = au (саҳифа ТП/МП ни ўзи аниқлайди). Бошқа файллар юборилмайди.
Secrets:  CF_ACCOUNT_ID, CF_D1_TOKEN (D1 Edit ҳуқуқли API token)
Хато бўлса ҳам бот ишини тўхтатмайди (exit 0) — фақат лог ёзади.
"""
import base64, datetime, json, os, sys, urllib.request, uuid

DB = "5ceb1306-b25c-4012-8a00-a4962f4ebd41"
CHUNK = 60000
KEEP_DAYS = 30


def q(sql, params):
    acc, tok = os.environ["CF_ACCOUNT_ID"], os.environ["CF_D1_TOKEN"]
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{acc}/d1/database/{DB}/query",
        data=json.dumps({"sql": sql, "params": params}).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if not out.get("success"):
        raise RuntimeError(out.get("errors"))
    return out


def push(kind, path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5)  # Тошкент
    sent = now.strftime("%Y-%m-%dT%H:%M:%S")
    fid = f"{kind}-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)] or [""]
    for i, p in enumerate(parts):
        q("INSERT INTO files (fid, kind, name, sent_at, part, nparts, b64) VALUES (?, ?, ?, ?, ?, ?, ?)",
          [fid, kind, os.path.basename(path), sent, i, len(parts), p])
    print(f"inbox: {kind} {os.path.basename(path)} -> {len(parts)} parts")


def kind_of(path):
    n = os.path.basename(path)
    if n.startswith("Факт визит и мерч"):
        return "tp"
    if n.startswith("МП визит"):
        return "mp"
    if n.startswith("Аудиозаписи МП"):
        return "au_mp"
    if n.startswith("Аудиозаписи"):
        return "au"
    return None


def push_file(path):
    """Хато бўлса ҳам ҳеч қачон exception чиқармайди — бот иши бузилмайди."""
    try:
        kind = kind_of(path)
        if not kind:
            return
        if not os.environ.get("CF_D1_TOKEN") or not os.environ.get("CF_ACCOUNT_ID"):
            print("inbox: CF_D1_TOKEN/CF_ACCOUNT_ID йўқ — ўтказиб юборилди")
            return
        push(kind, path)
        old = (datetime.datetime.utcnow() + datetime.timedelta(hours=5, days=-KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
        q("DELETE FROM files WHERE sent_at < ?", [old])
    except Exception as e:
        print(f"inbox: хато {os.path.basename(path)}: {e}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        push_file(p)
