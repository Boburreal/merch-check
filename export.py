"""Download the 'Общий отчёт' visits export for a project and date range (month by month)."""
import base64, datetime as dt, html, io, json, re
import pandas as pd
from sales import login, switch_project, BASE


def _component(s):
    r = s.get(BASE + "/visits/reports", timeout=120)
    csrf = re.search(r'data-csrf="([^"]+)"', r.text).group(1)
    upd = re.search(r'data-update-uri="([^"]+)"', r.text).group(1)
    for sn in re.findall(r'wire:snapshot="([^"]+)"', r.text):
        raw = html.unescape(sn)
        if json.loads(raw).get("memo", {}).get("name") == "visits.reports.all":
            return csrf, upd, raw
    raise SystemExit("visits.reports.all component not found")


def _export(s, d1: str, d2: str) -> bytes:
    csrf, upd, snap = _component(s)
    body = {"_token": csrf, "components": [{
        "snapshot": snap, "updates": {"filter.from": d1, "filter.to": d2},
        "calls": [{"path": "", "method": "excel", "params": ["csv"]}]}]}
    r = s.post(upd, json=body, timeout=600, headers={
        "X-Livewire": "true", "Content-Type": "application/json", "Accept": "application/json",
        "Referer": BASE + "/visits/reports", "X-CSRF-TOKEN": csrf})
    r.raise_for_status()
    eff = r.json()["components"][0].get("effects", {})
    if "download" in eff:
        return base64.b64decode(eff["download"]["content"])
    if "redirect" in eff:
        return s.get(eff["redirect"], timeout=600).content
    raise RuntimeError(f"{d1}: no download, effects={list(eff)}")


def fetch(project: int, d1: dt.date, d2: dt.date) -> pd.DataFrame:
    s = login()
    switch_project(s, project)          # project choice is stored on the account - always set it explicitly
    try:
        return _fetch(s, d1, d2)
    finally:
        if project != 1:
            switch_project(s, 1)        # leave the account on "Торговые представители" as the user had it


def _fetch(s, d1, d2):
    parts, cur = [], d1
    while cur <= d2:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        end = min(nxt - dt.timedelta(days=1), d2)
        data = _export(s, cur.isoformat(), end.isoformat())
        if data.strip():
            parts.append(pd.read_csv(io.BytesIO(data), dtype=str))
        cur = nxt
    if not parts:
        return pd.DataFrame(columns=["#", "Дата", "Тип визита", "Фарм. пред", "Контр-агент/Врач", "Адрес",
                                     "Время завершения визита", "Фото 1", "Фото 2"])
    return pd.concat(parts, ignore_index=True).drop_duplicates("#")
