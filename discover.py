import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
t = s.get(BASE + "/lists/visits/213625", timeout=90).text
p = t.find('Результаты визита')
a = t.rfind('<a', 0, p)
print("::notice::TAB " + re.sub(r'\s+', ' ', t[a:p])[:500])
href = re.search(r'href="([^"]+)"', t[a:p])
if href:
    u = href.group(1)
    r = s.get(u if u.startswith('http') else BASE + u, timeout=90)
    b = r.text
    b2 = re.sub(r'<script.*?</script>', ' ', b, flags=re.S)
    i = b2.find('Результаты визита')
    txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', b2[i:]))
    txt = re.sub(r'(\| )+', '| ', txt)
    print(f"::notice::RES status={r.status_code} url_end={r.url[-50:]} TEXT " + txt[:2500])
    med = re.findall(r'(?:src|href)="([^"]*(?:storage|upload)[^"]*)"', b2)
    print("::notice::MEDIA " + " | ".join(m.split('?')[0].split('/')[-3] + '/' + m.split('?')[0].split('.')[-1] for m in med)[:1200])
    print("::notice::TAGS " + str(sorted(set(re.findall(r'<(audio|video|source)\b', b2)))))
