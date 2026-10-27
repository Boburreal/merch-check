"""Compare the Worker's edit-form serialization (JS, HTMLRewriter) with the Python one. Prints only match results."""
import hashlib, os, sys, requests
sys.path.insert(0, os.getcwd())
from sales import login, switch_project, BASE
from bot import serialize

cid = int(sys.argv[1])
k = hashlib.sha256(("hook|" + os.environ["TG_BOT_TOKEN"]).encode()).hexdigest()[:40]
w = requests.get(f"http://localhost:8787/selftest?id={cid}&k={k}", timeout=120)
print(f"::notice::worker status={w.status_code} body_start={w.text[:60]!r}" if not w.ok else "::notice::worker ok")
wj = w.json()
s = login()
py = None
try:
    for p in (1, 4):
        switch_project(s, p)
        page = s.get(f"{BASE}/lists/companies/{cid}/edit", timeout=60).text
        if 'class="edit_form"' in page:
            py = serialize(page); break
finally:
    switch_project(s, 1)
js = [tuple(x) for x in wj.get("fields", [])]
print(f"::notice::st={wj.get('st')} js_fields={len(js)} py_fields={len(py or [])} equal={js == py} has_loc={bool(wj.get('loc'))}")
if py and js != py:
    names = sorted({a[0] for a in set(js) ^ set(py)})
    print(f"::warning::differs in: {names}")
