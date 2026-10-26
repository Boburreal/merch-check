"""Print small inline scripts (page logic, not vendor libs) of /lists/companies and /map."""
import re
from sales import login, switch_project, BASE

s = login()
switch_project(s, 1)
for path in ["/lists/companies", "/map"]:
    r = s.get(BASE + path, timeout=60)
    scripts = re.findall(r'<script(?![^>]*src)[^>]*>(.*?)</script>', r.text, re.S)
    small = [re.sub(r'\s+', ' ', x)[:700] for x in scripts if 30 < len(x) < 20000 and 'livewire' not in x[:200].lower()]
    srcs = re.findall(r'<script[^>]*src="([^"]+)"', r.text)
    print(f"::notice::{path} n_inline={len(scripts)} srcs={srcs[-6:]}")
    for i, x in enumerate(small[:4]):
        print(f"::notice::{path} S{i}: {x}")
