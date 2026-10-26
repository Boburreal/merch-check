"""Download the pharmacy (контрагент) list with coordinates from /lists/companies (DataTables server-side)."""
import re
import pandas as pd
from sales import login, switch_project, BASE

COLS = ['_sel', 'ID', 'Название', 'Инн', 'Регион', 'Район', 'Локация', 'Фарм. пред', 'Сеть']


def _clean(v):
    if v is None:
        return ''
    v = re.sub(r'<[^>]+>', ' ', str(v))
    return re.sub(r'\s+', ' ', v).strip()


def fetch_companies(project: int = 1) -> pd.DataFrame:
    s = login()
    switch_project(s, project)
    try:
        r = s.get(BASE + "/lists/companies", timeout=120)
        csrf = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", r.text) or re.search(r'data-csrf="([^"]+)"', r.text)
        csrf = csrf.group(1)
        rows, start, step, total = [], 0, 2000, None
        while total is None or start < total:
            data = {"draw": 1, "start": start, "length": step, "search[value]": "", "search[regex]": "false",
                    "order[0][column]": 3, "order[0][dir]": "asc"}
            for i in range(len(COLS)):
                data[f"columns[{i}][data]"] = i
                data[f"columns[{i}][searchable]"] = "true"
                data[f"columns[{i}][orderable]"] = "true"
            x = s.post(BASE + "/lists/companies", data=data, timeout=300,
                       headers={"X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
            x.raise_for_status()
            j = x.json()
            total = int(j.get("recordsFiltered", j.get("recordsTotal", 0)))
            batch = j.get("data", [])
            if not batch:
                break
            rows += batch
            start += len(batch)
        if rows and isinstance(rows[0], dict):
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame([[_clean(v) for v in r] for r in rows])
        return df
    finally:
        if project != 1:
            switch_project(s, 1)


if __name__ == "__main__":
    df = fetch_companies(1)
    print(f"::notice::rows={len(df)} cols={len(df.columns)} colnames={list(df.columns)[:15]}")
    # shape only: which columns look like coordinates / ids (no values printed)
    for c in df.columns:
        v = df[c].astype(str)
        print(f"::notice::col {c}: coords={v.str.match(r'^-?\d+\.\d+\s*,\s*-?\d+\.\d+').mean():.2f} digits={v.str.fullmatch(r'\d+').mean():.2f} empty={(v.str.strip()=='').mean():.2f} maxlen={v.str.len().max()}")
    df.to_csv("/tmp/companies.csv", index=False)
