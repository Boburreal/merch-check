"""Sales «Тесты → Результаты» дан Excel'ни олиб, «Asklepiy — Продажа ва Визитлар» саҳифаси учун
Cloudflare D1 (vizit-inbox) га ташлайди. Ойнинг 1-санасидан олдинги ой 1-санасигача (2 ой) олинади —
саҳифа шу даврдаги ойларни тўлиқ алмаштиради.
Repo public: логга исм ва натижалар чиқарилмайди, фақат сонлар."""
import base64, datetime as dt, html, io, json, os, re
from sales import login, BASE

TZ = dt.timezone(dt.timedelta(hours=5))


def _component(s, url):
    r = s.get(url, timeout=120)
    csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
    upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
    for sn in re.findall(r'wire:snapshot="([^"]+)"', r.text):
        raw = html.unescape(sn)
        if "date_from" in json.dumps(json.loads(raw).get("data", {})):
            return csrf, upd, raw
    raise SystemExit("tests results component not found")


def export(d1: str, d2: str) -> bytes:
    s = login()
    url = f"{BASE}/tests/results?f[date_from]={d1}&f[date_to]={d2}"
    csrf, upd, snap = _component(s, url)
    body = {"_token": csrf, "components": [{"snapshot": snap,
            "updates": {"filter.date_from": d1, "filter.date_to": d2},
            "calls": [{"path": "", "method": "export", "params": []}]}]}
    r = s.post(upd, json=body, timeout=600, headers={
        "X-Livewire": "true", "Content-Type": "application/json", "Accept": "application/json",
        "Referer": url, "X-CSRF-TOKEN": csrf})
    r.raise_for_status()
    eff = r.json()["components"][0].get("effects", {})
    if "download" in eff:
        return base64.b64decode(eff["download"]["content"])
    if "redirect" in eff:
        return s.get(eff["redirect"], timeout=600).content
    raise RuntimeError(f"no download, effects={list(eff)}")


def main():
    today = dt.datetime.now(TZ).date()
    d1 = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    data = export(d1.isoformat(), today.isoformat())
    path = f"/tmp/Тест результаты {d1:%Y-%m-%d}_{today:%Y-%m-%d}.xlsx"
    with open(path, "wb") as f:
        f.write(data)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        n = sum(max(ws.max_row - 1, 0) for ws in wb.worksheets)
        print(f"tests: {len(data)} bytes, ~{n} rows, sheets={len(wb.worksheets)}")
    except Exception as e:
        print(f"tests: {len(data)} bytes (not xlsx? {e})")
    from inbox import push_file
    push_file(path, kind="test")


if __name__ == "__main__":
    main()
