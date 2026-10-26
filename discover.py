"""Grep the site's own JS files for data URLs used by the companies table and the tracking map."""
import re
from sales import login, switch_project, BASE

s = login()
switch_project(s, 1)
for path in ["/lists/companies", "/map"]:
    r = s.get(BASE + path, timeout=60)
    srcs = [x for x in re.findall(r'<script[^>]*src="([^"]+)"', r.text) if 'cdn' not in x and 'yandex' not in x and 'jquery' not in x.lower()]
    print(f"::notice::{path} own_js={srcs}"[:1500])
    for src in srcs:
        u = src if src.startswith('http') else BASE + src
        js = s.get(u, timeout=60).text
        hits = sorted(set(re.findall(r'''(?:url\s*:\s*|ajax\s*:\s*|get\(|post\(|fetch\()\s*[`'"]([^`'"]{3,120})''', js)))
        if hits:
            print(f"::notice::{src[:60]} -> {hits[:15]}"[:1500])
    # data attributes on the table
    attrs = re.findall(r'<table[^>]*>', r.text)
    print(f"::notice::{path} tables={attrs[:3]}"[:1500])
