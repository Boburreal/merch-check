import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
r = s.get(BASE + "/lists/companies/10/edit", timeout=60)
t = r.text
i = t.find('class="edit_form"'); f = t[i:t.find('</form>', i)]
fl = []
for m in re.finditer(r'<(input|select|textarea)([^>]*)>', f):
    a = m.group(2)
    nm = re.search(r'name="([^"]+)"', a); ty = re.search(r'type="([^"]+)"', a); v = re.search(r'value="([^"]*)"', a)
    fl.append(f"{m.group(1)}:{nm and nm.group(1)}:{ty and ty.group(1)}:{'v' if v and v.group(1) else '-'}")
print("::notice::FIELDS " + " | ".join(fl))
js = [x for x in re.findall(r'<script[^>]*>(.*?)</script>', t, flags=re.S) if 'edit_form' in x or 'location' in x.lower()]
print("::notice::JS " + re.sub(r'\s+', ' ', " ### ".join(js))[:3500])
print("::notice::BTN " + str(re.findall(r'<button[^>]*>[^<]{0,40}', f))[:1500])
