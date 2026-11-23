"""Bir martalik: Sales'dagi «Результаты тестов» sahifasi tuzilishini aniqlash.
Repo public — logga hech qanday shaxsiy ma'lumot (ism, natija) chiqarilmaydi, faqat havolalar/formalar tuzilishi va sonlar."""
import re, sales
s = sales.login()
url = f"{sales.BASE}/tests/results?f[date_from]=2026-10-01&f[date_to]=2026-11-23"
r = s.get(url, timeout=120)
t = r.text
print("status", r.status_code, "len", len(t), "final", r.url.split('?')[0])
print("rows <tr>:", t.count("<tr"))
for h in sorted(set(re.findall(r'href="([^"]*)"', t))):
    if any(k in h.lower() for k in ("export", "excel", "download", "page=", "tests")):
        print("href", re.sub(r'\d{3,}', 'N', h)[:160])
for f in re.findall(r'<form[^>]*>', t):
    print("form", re.sub(r'value="[^"]*"', 'value=…', f)[:200])
for m in re.findall(r'(wire:click[^>]{0,80}|onclick="[^"]{0,80}|data-[a-z-]*url[^>]{0,80})', t):
    if any(k in m.lower() for k in ("excel", "export", "download")):
        print("act", m[:160])
th = re.findall(r'<th[^>]*>(.*?)</th>', t, re.S)
print("th", [re.sub(r'<[^>]+>|\s+', ' ', x).strip() for x in th][:12])
print("livewire" if "wire:snapshot" in t else "no-livewire")
for sn in re.findall(r'wire:snapshot="([^"]{0,200})', t)[:5]:
    import html; print("snap", re.sub(r'"[^"]{20,}"', '"…"', html.unescape(sn))[:160])
