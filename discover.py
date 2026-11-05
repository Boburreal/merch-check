"""Read-only probe 4: naming of existing branch cards (INN with -N) and the users list of both projects."""
import re, json, os, base64, hashlib
from cryptography.fernet import Fernet
from sales import login, switch_project, restore, BASE
from companies import fetch_companies

out = {}
for p in (1, 4):
    c = fetch_companies(p)
    c = c.iloc[:, :9]
    c.columns = ['_sel', 'ID', 'Название', 'Инн', 'Регион', 'Район', 'Локация', 'Фарм. пред', 'Сеть']
    b = c[c['Инн'].astype(str).str.contains(r'\d-\d|\(|[A-Za-zА-Яа-я]', regex=True)]
    out[f"p{p}_branches"] = b.drop(columns=['_sel', 'Локация']).astype(str).to_dict('records')
    out[f"p{p}_names_tp_mp"] = c[c['Название'].astype(str).str.contains(r'\((?:ТП|МП|TP|MP)\)', regex=True)].drop(columns=['_sel', 'Локация']).astype(str).to_dict('records')
s = login()
for p in (1, 4):
    switch_project(s, p)
    u = s.get(BASE + "/lists/users", timeout=60)
    tok = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", u.text).group(1)
    data = {"draw": 1, "start": 0, "length": 3000, "search[value]": "", "search[regex]": "false"}
    for i in range(17):
        data[f"columns[{i}][data]"] = i
    out[f"p{p}_users"] = s.post(BASE + "/lists/users", data=data, timeout=300, headers={"X-CSRF-TOKEN": tok,
                                "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json().get("data", [])
restore(s)
k = os.environ["ROSTER_KEY"].encode()
open("drop/baza_probe4.fer", "wb").write(Fernet(base64.urlsafe_b64encode(hashlib.sha256(k).digest())).encrypt(json.dumps(out, ensure_ascii=False).encode()))
print("::notice::probe4 " + " ".join(f"{k}={len(v)}" for k, v in out.items()))
