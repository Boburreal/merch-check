import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
t = s.get(BASE + "/lists/companies/10/edit", timeout=60).text
out = []
for k in ['edit_form', '.submit(', 'submit', 'FormData', '_method', 'location']:
    for m in re.finditer(re.escape(k), t):
        seg = t[max(0, m.start()-150): m.start()+250]
        if 'function Pe(' in seg or len(out) > 14: continue
        out.append(k + ' >> ' + re.sub(r'\s+', ' ', seg))
for o in out[:14]:
    print("::notice::" + o[:600])
print("::notice::SRC " + str(re.findall(r'<script[^>]*src="([^"]+)"', t))[:800])
