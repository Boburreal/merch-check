import re
from sales import login, switch_project, BASE
s = login(); switch_project(s, 1)
for path in ["/lists/companies/10", "/lists/companies/10/edit"]:
    r = s.get(BASE + path, timeout=60)
    t = re.sub(r'<script.*?</script>', ' ', r.text, flags=re.S)
    heads = re.findall(r'<(?:h\d|th|label|button|a)[^>]*>\s*([^<]{3,50})<', t)
    kw = [m.group(0) for m in re.finditer(r'(?i)(истори|history|audit|лог|изменен|updated_at|created_at|location_history)[^<]{0,60}', t)][:10]
    names = sorted(set(re.findall(r'name="([^"]+)"', t)))[:30]
    print(f"::notice::{path} status={r.status_code} heads={heads[:40]} kw={kw} inputs={names}"[:3800])
