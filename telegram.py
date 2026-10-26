import os
import requests

TOKEN = os.environ["TG_BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"


def chat_id() -> int:
    if os.environ.get("TG_CHAT_ID"):
        return int(os.environ["TG_CHAT_ID"])
    r = requests.get(f"{API}/getUpdates", timeout=30).json()
    ids = [u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u]
    if not ids:
        raise SystemExit("Botga /start yuboring (chat_id topilmadi)")
    return ids[-1]


def send_text(text: str):
    for i in range(0, len(text), 4000):
        requests.post(f"{API}/sendMessage", timeout=30,
                      data={"chat_id": chat_id(), "text": text[i:i + 4000], "parse_mode": "HTML"})


def send_file(path: str, caption: str = ""):
    with open(path, "rb") as f:
        requests.post(f"{API}/sendDocument", timeout=120,
                      data={"chat_id": chat_id(), "caption": caption}, files={"document": f})
