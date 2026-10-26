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
    return {k: pd.read_csv(io.StringIO(v)) for k, v in raw.items()}


def save(parts: dict):
    raw = {k: v.to_csv(index=False) for k, v in parts.items()}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    open(PATH, "wb").write(_fernet().encrypt(json.dumps(raw, ensure_ascii=False).encode()))
