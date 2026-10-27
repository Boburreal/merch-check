import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
r = s.get(BASE + "/lists/companies/10/edit", timeout=60)
t = r.text
forms = re.findall(r'<form[^>]*>', t)
print(f"::notice::status={r.status_code} forms={forms}"[:3000])
for m in re.finditer(r'<(input|select|textarea)([^>]*)>', t):
    a = m.group(2)
    nm = re.search(r'name="([^"]+)"', a); ty = re.search(r'type="([^"]+)"', a); v = re.search(r'value="([^"]*)"', a)
    wm = re.findall(r'wire:model[^=]*="([^"]+)"', a)
    print(f"::notice::{m.group(1)} name={nm and nm.group(1)} type={ty and ty.group(1)} has_value={bool(v and v.group(1))} wire={wm}")
lw = [ (re.search(r'"name":"([^"]+)"', x) or [None,None])[1] for x in re.findall(r'wire:snapshot="([^"]+)"', t.replace('&quot;','"'))]
print(f"::notice::livewire={lw} buttons={re.findall(r'<button[^>]*>[^<]{0,40}', t)[:10]}"[:3000])
