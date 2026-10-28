import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
for path in ["/lists/visits", "/lists/visits/213625", "/lists/visits/213625/edit", "/visits/213625", "/visits/reports/done-visits"]:
    r = s.get(BASE + path, timeout=90)
    t = r.text
    hits = []
    for kw in ['<audio', '.mp3', '.m4a', '.ogg', '.wav', '.webm', '.aac', '.3gp', 'audio', 'record', 'Запис', 'запис']:
        for m in list(re.finditer(re.escape(kw), t))[:2]:
            hits.append(kw + ': ' + re.sub(r'\s+', ' ', t[max(0, m.start()-100):m.start()+160]))
    ths = re.findall(r'<th[^>]*>\s*([^<]{2,40})<', t)[:30]
    print(f"::notice::{path} status={r.status_code} final={r.url[-40:]} th={ths}"[:900])
    print("::notice::" + path + " HITS " + " ### ".join(hits)[:2500])
