"""Staff rosters (ТП with daily plan, МП) - stored encrypted (ROSTER_KEY secret), never in plain text in the public repo."""
import base64, hashlib, io, json, os, re
import pandas as pd
from cryptography.fernet import Fernet

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "roster.enc")
DEFAULT_PLAN = 15
CODE = {'сыр': 'Сырдарьинская', 'т.обл': 'Ташкентская', 'таш': 'г.Ташкент', 'нук': 'Р.Каракалпакстан',
        'бух': 'Бухарская', 'ург': 'Хорезмская', 'фер': 'Ферганская', 'кок': 'Коканд', 'нам': 'Наманганская',
        'кар': 'Кашкадарьинская', 'нав': 'Навоийская', 'тер.в': 'Сурхандарьинская', 'тер.з': 'Сурхандарьинская',
        'сам': 'Самаркандская', 'дж': 'Джизакская', 'джиз': 'Джизакская', 'анд': 'Андижанская'}
LAT2CYR = str.maketrans({'o': 'о', 'a': 'а', 'e': 'е', 'c': 'с', 'p': 'р', 'x': 'х', 'k': 'к', 'm': 'м', 't': 'т', 'h': 'н', 'b': 'в'})


def key(name: str) -> str:
    """Surname + first name, prefix '(reg)' and role removed, latin look-alikes -> cyrillic."""
    n = re.sub(r'^\([^)]*\)\s*', '', str(name)).lower().translate(LAT2CYR)
    n = n.replace('ё', 'е').replace('қ', 'к').replace('ғ', 'г').replace('ҳ', 'х').replace('ў', 'у')
    n = re.sub(r'\([^)]*\)', '', n)
    return ' '.join(n.split()[:2])


def region_from_prefix(name: str):
    m = re.match(r'^\(([^)]*)\)', str(name))
    return CODE.get(m.group(1).strip().lower()) if m else None


def _fernet():
    k = os.environ["ROSTER_KEY"].encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(k).digest()))


def load() -> dict:
    """{'tp': DataFrame(name, region, plan, key), 'mp': DataFrame(name, region, key), 'seed_merch': DataFrame}"""
    raw = json.loads(_fernet().decrypt(open(PATH, "rb").read()))
    parts = {k: pd.read_csv(io.StringIO(v)) for k, v in raw.items()}
    for k in ('tp', 'mp'):                         # keys are recomputed so spelling rules (ё/е, қ/к ...) stay consistent
        if k in parts and 'name' in parts[k]:
            parts[k]['key'] = parts[k]['name'].map(key)
    return parts


def regroup(raw_tp: pd.DataFrame, raw_mp: pd.DataFrame, tp_people: pd.DataFrame, mp_people: pd.DataFrame):
    """Visits are sorted by the roster, not by the Sales project they were entered in: people listed as МП go to the МП
    report, people listed as ТП to the ТП report (a ТП who became МП may still enter visits in the ТП project)."""
    raw_tp, raw_mp = raw_tp.assign(src=1), raw_mp.assign(src=4)     # project the visit was entered in (audio pages need it)
    mk, tk = set(mp_people['key']), set(tp_people['key'])
    kt = raw_tp['Фарм. пред'].map(key) if len(raw_tp) else pd.Series([], dtype=str)
    km = raw_mp['Фарм. пред'].map(key) if len(raw_mp) else pd.Series([], dtype=str)
    to_mp = kt.isin(mk) & ~kt.isin(tk)
    to_tp = km.isin(tk) & ~km.isin(mk)
    new_tp = pd.concat([raw_tp[~to_mp], raw_mp[to_tp]], ignore_index=True)
    new_mp = pd.concat([raw_mp[~to_tp], raw_tp[to_mp]], ignore_index=True)
    print(f"::notice::regroup: {int(to_mp.sum())} visits ТП->МП, {int(to_tp.sum())} visits МП->ТП")
    return new_tp, new_mp


def save(parts: dict):
    raw = {k: v.to_csv(index=False) for k, v in parts.items()}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    open(PATH, "wb").write(_fernet().encrypt(json.dumps(raw, ensure_ascii=False).encode()))
