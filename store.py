"""Encrypted result store inside the public repo. Key is derived from repo secrets, so only the workflow can read it."""
import base64, hashlib, io, os
import pandas as pd
from cryptography.fernet import Fernet

DIR = "drop/store"


def _f():
    seed = (os.environ["GEMINI_API_KEY"] + "|" + os.environ["SALES_PASSWORD"] + "|merch-store-v1").encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed).digest()))


def save(name: str, df: pd.DataFrame):
    os.makedirs(DIR, exist_ok=True)
    open(f"{DIR}/{name}.fer", "wb").write(_f().encrypt(df.to_csv(index=False).encode()))


def load(name: str) -> pd.DataFrame:
    p = f"{DIR}/{name}.fer"
    if not os.path.exists(p):
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(_f().decrypt(open(p, "rb").read())), dtype=str)


def load_many(prefix: str) -> pd.DataFrame:
    if not os.path.isdir(DIR):
        return pd.DataFrame()
    parts = [load(f[:-4]) for f in sorted(os.listdir(DIR)) if f.startswith(prefix) and f.endswith(".fer")]
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def save_bytes(name: str, data: bytes):
    os.makedirs(DIR, exist_ok=True)
    open(f"{DIR}/{name}.fer", "wb").write(_f().encrypt(data))


def load_bytes(name: str):
    p = f"{DIR}/{name}.fer"
    return _f().decrypt(open(p, "rb").read()) if os.path.exists(p) else None
