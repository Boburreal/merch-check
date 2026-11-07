"""Sales base audit (read only): data-quality problems of pharmacies and users -> encrypted Excel drop for Claude."""
import base64, datetime as dt, hashlib, io, json, os, re
import pandas as pd
from cryptography.fernet import Fernet
from companies import fetch_companies
from sales import login, switch_project, restore, BASE
import vcache

T = lambda v: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(v or ''))).strip()
def names(v):
    parts = re.split(r'<br\s*/?>|</(?:li|div|span|p)>|,|;|\n', str(v or ''))
    return [x for x in (T(p) for p in parts) if x]
norm = lambda s: re.sub(r'\s+', ' ', re.sub(r'\([^()]*\)\s*$', '', str(s))).strip().lower()

comp = []
for p in (1, 4):
    c = fetch_companies(p)
    print(f"::notice::dates sample") if False else print(f"::notice::companies p{p}: rows={len(c)} cols={list(c.columns)}")
    c['project'] = 'ТП' if p == 1 else 'МП'
    comp.append(c)
c = pd.concat(comp, ignore_index=True)
ll = c['location'].fillna('').astype(str).str.extract(r'll=(-?[\d.]+)%2C(-?[\d.]+)')
C = pd.DataFrame({'ID': c['id'].astype(int), 'База': c['project'], 'Аптека': c['name'].map(T),
                  'ИНН': c['inn'].map(T) if 'inn' in c else '', 'Регион': c['region_id'].map(T),
                  'Туман': c['district_id'].map(T), 'lat': pd.to_numeric(ll[1], errors='coerce'),
                  'reps': c['users'].map(names)})

s = login()
U = []
for p in (1, 4):
    switch_project(s, p)
    u = s.get(BASE + "/lists/users", timeout=60)
    tok = re.search(r"'X-CSRF-TOKEN':\s*'([^']+)'", u.text).group(1)
    data = {"draw": 1, "start": 0, "length": 3000, "search[value]": "", "search[regex]": "false"}
    for i in range(17):
        data[f"columns[{i}][data]"] = i
    for r in s.post(BASE + "/lists/users", data=data, timeout=300, headers={"X-CSRF-TOKEN": tok,
                    "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json().get("data", []):
        U.append({'id': r['id'], 'Ходим': T(r.get('name')), 'Фаол': T(r.get('active')) == 'Да', 'Категория': T(r.get('category_id')),
                  'Роль': T(r.get('roles')), 'Telegram': T(r.get('telegram_user_id')), 'База': 'ТП' if p == 1 else 'МП'})
restore(s)
U = pd.DataFrame(U).drop_duplicates(['id', 'База'])
active = dict(zip(U['Ходим'].str.lower(), U['Фаол']))
known = set(U['Ходим'].str.lower())

today = dt.date.today()
v = []
for grp in ('tp', 'mp'):
    x = vcache.get(grp, dt.date(today.year, today.month - 1 if today.month > 1 else 12, 1) if today.month > 1 else dt.date(today.year - 1, 12, 1), today)
    x['grp'] = 'ТП' if grp == 'tp' else 'МП'
    v.append(x)
V = pd.concat(v, ignore_index=True)
print(f"::notice::visits={len(V)} date sample={V['Дата'].astype(str).head(3).tolist()} rep sample={V['Фарм. пред'].astype(str).head(2).tolist()}")
V = V[V['Тип визита'].fillna('').str.contains('аптек', case=False)]
V['obj'] = V['Контр-агент/Врач'].map(norm)   # visit name = '<pharmacy> (<region>)'
V['rep'] = V['Фарм. пред'].astype(str).str.replace(r'\s*\([^()]*\)\s*$', '', regex=True).str.strip()
vis = V.groupby('obj').size()
C['obj'] = C['Аптека'].map(lambda s: re.sub(r'\s+', ' ', str(s)).strip().lower())
C['Визит (2 ой)'] = C['obj'].map(vis).fillna(0).astype(int)
C['Ходимлар'] = C['reps'].map(lambda r: ', '.join(r))
rep_clean = lambda n: re.sub(r'\s*\([^()]*\)\s*$', '', n).strip().lower()
C['Ишдан кетганлар'] = C['reps'].map(lambda r: ', '.join(n for n in r if active.get(rep_clean(n)) is False))
C['Ишлаётганлар сони'] = C['reps'].map(lambda r: sum(1 for n in r if active.get(rep_clean(n)) is True))

out = {}
uniq = C.drop_duplicates('ID')
out['1 Локациясиз аптекалар'] = C[C['lat'].isna()].sort_values('Визит (2 ой)', ascending=False)
out['2 Ходим бириктирилмаган'] = C[C['reps'].map(len) == 0].sort_values('Визит (2 ой)', ascending=False)
out['3 Ишдан кетган ходимда'] = C[(C['Ишдан кетганлар'] != '') & (C['Ишлаётганлар сони'] == 0)].sort_values('Визит (2 ой)', ascending=False)
inn = uniq['ИНН'].str.replace(r'\s', '', regex=True)
base_inn = inn.str.extract(r'^(\d{9})')[0]
out['4 ИНН хато ёки бўш'] = uniq[~inn.str.fullmatch(r'\d{9}(-\d+)?')]
dup = uniq[inn.str.fullmatch(r'\d{9}') & inn.duplicated(keep=False)]
out['5 Бир ИНН бир неча карточкада'] = dup.assign(_i=inn).sort_values('_i').drop(columns='_i')
nm = uniq.assign(_k=uniq['obj'] + '|' + uniq['Регион'])
out['6 Номи ва вилояти бир хил (дубль)'] = nm[nm['_k'].duplicated(keep=False)].sort_values('_k').drop(columns='_k')
out['7 Регион ёки туман бўш'] = uniq[(uniq['Регион'] == '') | (uniq['Туман'] == '')]
out['8 2 ойда визит йўқ'] = C[C['Визит (2 ой)'] == 0]
inv = V[~V['obj'].isin(set(C['obj']))].groupby(['grp', 'Контр-агент/Врач']).agg(Визит=('obj', 'size'), Ходимлар=('rep', lambda s: ', '.join(sorted(set(s))))).reset_index()
out['9 Визит бор, базада номи йўқ'] = inv.sort_values('Визит', ascending=False)
held = C.explode('reps').dropna(subset=['reps'])
held['k'] = held['reps'].map(rep_clean)
cnt = held.groupby('k').size()
U['Бириктирилган аптека'] = U['Ходим'].str.lower().map(cnt).fillna(0).astype(int)
U['Шу ой визит'] = U['Ходим'].str.lower().map(V[pd.to_datetime(V['Дата'], dayfirst=True, errors='coerce').dt.month == today.month].assign(k=lambda d: d['rep'].str.lower()).groupby('k').size()).fillna(0).astype(int)
out['10 Ишдан кетган, аптека ушлаб турибди'] = U[(~U['Фаол']) & (U['Бириктирилган аптека'] > 0)].sort_values('Бириктирилган аптека', ascending=False)
out['11 Фаол, бу ой визит йўқ'] = U[U['Фаол'] & (U['Шу ой визит'] == 0) & U['Категория'].str.contains('Пред|представ', case=False)]
out['12 Ходимлар'] = U

summ = [{'Текширув': k, 'Сони': len(d)} for k, d in out.items()]
summ = [{'Текширув': 'Жами аптека карточкалари (ТП+МП, ID бўйича)', 'Сони': uniq['ID'].nunique()},
        {'Текширув': 'Жами ходимлар', 'Сони': len(U)}] + summ
print("::notice::" + " | ".join(f"{x['Текширув']}={x['Сони']}" for x in summ))
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine='openpyxl') as w:
    pd.DataFrame(summ).to_excel(w, sheet_name='Хулоса', index=False)
    for k, d in out.items():
        d.drop(columns=[x for x in ('reps', 'obj', 'lat') if x in d], errors='ignore').to_excel(w, sheet_name=k[:31], index=False)
print("::notice::" + " | ".join(f"{x['Текширув']}={x['Сони']}" for x in summ))
key = os.environ["ROSTER_KEY"].encode()
os.makedirs("drop", exist_ok=True)
open("drop/audit.fer", "wb").write(Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest())).encrypt(buf.getvalue()))
