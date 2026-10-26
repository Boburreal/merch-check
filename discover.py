import re
from sales import login, switch_project, BASE

s = login()
switch_project(s, 1)
r = s.get(BASE + "/lists/companies", timeout=60)
for m in re.finditer(r'#datatable|ajax\s*:|serverSide|"url"|url\s*:', r.text):
    print("::notice::C " + re.sub(r'\s+', ' ', r.text[max(0, m.start() - 80): m.start() + 400])[:600])
r = s.get(BASE + "/map", timeout=60)
for m in re.finditer(r'Livewire\.on|\$wire|dispatch|wire:ignore|myMap|Placemark|Polyline', r.text):
    print("::notice::M " + re.sub(r'\s+', ' ', r.text[max(0, m.start() - 80): m.start() + 400])[:600])
