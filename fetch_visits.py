"""Download 'Общий отчёт' (visits with photo links) month by month via the Livewire export."""
import base64, html, json, os, re, sys, datetime as dt
from sales import login, switch_project, BASE

FROM = os.environ.get("FROM", "2026-01-01")
TO = os.environ.get("TO", dt.date.today().isoformat())
OUT = os.environ.get("OUT", "/tmp/visits")
os.makedirs(OUT, exist_ok=True)

s = login()
PROJECT = int(os.environ.get("PROJECT", "1"))
if PROJECT != 1:
    switch_project(s, PROJECT)


def component():
    r = s.get(BASE + "/visits/reports", timeout=120)
    csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
    upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
    for sn in re.findall(r'wire:snapshot="([^"]+)"', r.text):
        raw = html.unescape(sn)
        if json.loads(raw).get("memo", {}).get("name") == "visits.reports.all":
            return csrf, upd, raw
    raise SystemExit("visits.reports.all component not found")


def export(d1, d2):
    csrf, upd, snap = component()
    body = {"_token": csrf, "components": [{
        "snapshot": snap,
        "updates": {"filter.from": d1, "filter.to": d2},
        "calls": [{"path": "", "method": "excel", "params": ["csv"]}]}]}
    r = s.post(upd, json=body, timeout=600, headers={
        "X-Livewire": "true", "Content-Type": "application/json", "Accept": "application/json",
        "Referer": BASE + "/visits/reports", "X-CSRF-TOKEN": csrf})
    if not r.ok:
        raise RuntimeError(f"{d1}: HTTP {r.status_code} {r.text[:200]}")
    eff = r.json()["components"][0].get("effects", {})
    if "download" in eff:
        return base64.b64decode(eff["download"]["content"])
    if "redirect" in eff:
        f = s.get(eff["redirect"], timeout=600)
        return f.content
    raise RuntimeError(f"{d1}: no download, effects keys={list(eff.keys())}")


start = dt.date.fromisoformat(FROM); end = dt.date.fromisoformat(TO)
cur = start
total = 0
while cur <= end:
    nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    d2 = min(nxt - dt.timedelta(days=1), end)
    data = export(cur.isoformat(), d2.isoformat())
    lines = data.count(b"\n")
    total += lines
    open(f"{OUT}/visits_{cur:%Y-%m}.csv", "wb").write(data)
    head = data[:400].decode("utf-8", "ignore").splitlines()
    if head: print(f"::notice::header={head[0][:300]}")
    print(f"::notice::{cur:%Y-%m}: {lines} rows, {len(data)//1024} KB")
    cur = nxt
print(f"::notice::TOTAL rows {total}")
