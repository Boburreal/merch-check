import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
r = s.get(BASE + "/visits/reports", timeout=60)
t = r.text
links = sorted(set(re.findall(r'href="(https://sales\.asklepiygroup\.uz/[^"]*visit[^"]*)"', t)))[:15]
print("::notice::visit links " + " | ".join(links)[:1500])
for kw in ['audio', 'mp3', 'record', 'Запись', 'запис', 'm4a', 'ogg', 'webm', 'wav']:
    ms = [t[max(0, m.start()-120):m.start()+150] for m in re.finditer(kw, t)][:2]
    if ms:
        print(f"::notice::{kw}: " + re.sub(r'\s+', ' ', ' ### '.join(ms))[:700])
