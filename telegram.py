import os
import requests

TOKEN = os.environ["TG_BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"


_CACHE = None


def _saved():
    try:
        import store
        d = store.load("chat")
        return int(d["chat_id"].iloc[0]) if len(d) else None
    except Exception:
        return None


def _save(cid: int):
    try:
        import store, pandas as pd
        store.save("chat", pd.DataFrame({"chat_id": [cid]}))
    except Exception:
        pass


def chat_id() -> int:
    """Telegram keeps /start messages only 24h, so the chat id is stored (encrypted) after the first success."""
    global _CACHE
    if _CACHE:
        return _CACHE
    if os.environ.get("TG_CHAT_ID"):
        _CACHE = int(os.environ["TG_CHAT_ID"]); return _CACHE
    r = requests.get(f"{API}/getUpdates", timeout=30).json()
    if not r.get("ok"):
        raise RuntimeError(f"getUpdates: {r}"[:200])
    ids = [u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u]
    if ids:
        _CACHE = ids[-1]
        if _saved() != _CACHE:
            _save(_CACHE)
        return _CACHE
    _CACHE = _saved()
    if not _CACHE:
        raise SystemExit("Botga /start yuboring (chat_id topilmadi)")
    return _CACHE


def send_text(text: str):
    for i in range(0, len(text), 4000):
        r = requests.post(f"{API}/sendMessage", timeout=30,
                          data={"chat_id": chat_id(), "text": text[i:i + 4000], "parse_mode": "HTML"})
        if not r.ok:
            raise RuntimeError(f"sendMessage {r.status_code}: {r.text[:150]}")


def send_file(path: str, caption: str = ""):
    with open(path, "rb") as f:
        r = requests.post(f"{API}/sendDocument", timeout=120,
                          data={"chat_id": chat_id(), "caption": caption[:1000]}, files={"document": f})
    if not r.ok:
        raise RuntimeError(f"sendDocument {r.status_code}: {r.text[:150]}")
