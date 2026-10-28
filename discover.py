import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
r = s.get(BASE + "/lists/visits/213625", timeout=90)
t = re.sub(r'<script.*?</script>', ' ', r.text, flags=re.S)
t = re.sub(r'<style.*?</style>', ' ', t, flags=re.S)
i = t.find('page-wrapper') if 'page-wrapper' in t else 0
body = t[i:]
txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' | ', body))
txt = re.sub(r'(\| )+', '| ', txt)
print("::notice::TEXT " + txt[:3000])
srcs = sorted(set(re.findall(r'(?:src|href|data-src|data-url)="([^"]+)"', body)))
srcs = [x for x in srcs if 'storage' in x or 'upload' in x or 'audio' in x.lower() or 'record' in x.lower()]
print("::notice::MEDIA " + " | ".join(x.split('/')[-2] + '/' + x.split('.')[-1] for x in srcs)[:1500])
print("::notice::TAGS " + str(sorted(set(re.findall(r'<(audio|video|source|iframe|canvas)\b', body)))))
