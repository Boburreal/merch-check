import re, html
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
r = s.get(BASE + "/lists/visits/213625", timeout=90)
t = r.text
for kw in ['Результаты визита', 'upload', 'wire:snapshot', 'tab-pane', 'x-data']:
    ms = [m.start() for m in re.finditer(re.escape(kw), t)][:4]
    print(f"::notice::{kw} count={len(re.findall(re.escape(kw), t))}")
    for p in ms[:3]:
        seg = re.sub(r'\s+', ' ', t[max(0, p-200):p+400])
        seg = re.sub(r'_token[^,]{0,80}', '_token=*', seg)
        print("::notice::  " + seg[:600])
names = [json_name for json_name in re.findall(r'&quot;name&quot;:&quot;([^&]+)&quot;', t)]
print("::notice::components " + str(sorted(set(names)))[:500])
