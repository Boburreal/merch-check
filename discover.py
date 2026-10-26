"""Find data endpoints of /lists/companies (table) and /map (tracking). Prints code snippets only."""
import re
from sales import login, switch_project, BASE

s = login()
switch_project(s, 1)
r = s.get(BASE + "/lists/companies", timeout=60)
snips = [r.text[max(0, m.start() - 120): m.start() + 220].replace("\n", " ") for m in re.finditer(r'ajax|DataTable\(|serverSide|fetch\(|axios', r.text)][:4]
print(f"::notice::companies snippets={snips}"[:3800])
pag = re.findall(r'href="([^"]*page=\d+[^"]*)"', r.text)[:3]
rows = len(re.findall(r'<tr', r.text))
print(f"::notice::companies rows_in_html={rows} pag={pag}")
r = s.get(BASE + "/map", timeout=60)
snips = [r.text[max(0, m.start() - 150): m.start() + 250].replace("\n", " ") for m in re.finditer(r'tracking|polyline|L\.marker|ymaps|lat', r.text)][:5]
print(f"::notice::map snippets={snips}"[:3800])
