import os, requests
T = os.environ["TG_BOT_TOKEN"].strip()
A = f"https://api.telegram.org/bot{T}"
me = requests.get(A + "/getMe", timeout=30).json()
wh = requests.get(A + "/getWebhookInfo", timeout=30).json()
up = requests.get(A + "/getUpdates", timeout=30).json()
print(f"::notice::getMe ok={me.get('ok')} username={me.get('result',{}).get('username')} desc={me.get('description','')}")
r = wh.get("result", {})
print(f"::notice::webhook url_set={bool(r.get('url'))} host={(r.get('url') or '').split('/')[2] if r.get('url') else ''} pending={r.get('pending_update_count')}")
print(f"::notice::updates ok={up.get('ok')} n={len(up.get('result',[]))} err={up.get('description','')}")
print(f"::notice::token_len={len(T)} raw_len={len(os.environ['TG_BOT_TOKEN'])}")
from telegram import send_text
send_text("✅ Салом, Бобур! Бот уланди.\nБундан кейин визит ва мерч ҳисоботлари шу ерга келади.")
print("::notice::sent=ok")
