"""Run Gemini on the 30 verified visits and report agreement to Telegram.
Logs are public (public repo) - only aggregate numbers are printed."""
import csv, json, os, time
from openpyxl import Workbook
from merch import check_visit, pick_model, STATS
from telegram import send_text, send_file

HERE = os.path.dirname(os.path.abspath(__file__))
rows = list(csv.DictReader(open(os.path.join(HERE, "data", "test_sample.csv"), encoding="utf-8")))
model = pick_model()
print("model:", model, "visits:", len(rows))
print(f"::notice::model={model}")

NAMES = {"merch": "Мерч бор", "none": "—", "suspicious": "Шубҳали", "no_photo": "Фото йўқ", "error": "Хато"}
wb = Workbook(); ws = wb.active
ws.append(["#", "Кутилган", "Gemini", "Витрина (кут.)", "Витрина (Gemini)", "Касса (кут.)", "Касса (Gemini)", "Мос", "Фото 1", "Фото 2", "raw"])
ok = 0
T0 = time.time()
misses = []
for i, r in enumerate(rows, 1):
    try:
        res = check_visit(model, r["photo1"], r["photo2"])
    except Exception as e:  # keep going, count as error
        res = {"category": "error", "vitrina": 0, "kassa": 0, "raw": str(e)[:200]}
    match = res["category"] == r["expected"]
    if match and r["expected"] == "merch":
        match = str(res["vitrina"]) == r["vitrina"] and str(res["kassa"]) == r["kassa"]
    ok += match
    if not match:
        misses.append(f"{r['id']} exp={r['expected']}/v{r['vitrina']}/k{r['kassa']} got={res['category']}/v{res['vitrina']}/k{res['kassa']}"); print(f"MISS {r['id']} exp={r['expected']}/v{r['vitrina']}/k{r['kassa']} got={res['category']}/v{res['vitrina']}/k{res['kassa']} raw=" + json.dumps(res.get('raw'))[:400])
    ws.append([r["id"], NAMES[r["expected"]], NAMES[res["category"]], r["vitrina"], res["vitrina"],
               r["kassa"], res["kassa"], "✅" if match else "❌", r["photo1"], r["photo2"],
               json.dumps(res.get("raw"), ensure_ascii=False)[:500]])
    print(f"{i}/{len(rows)}")
    time.sleep(2)

path = "/tmp/gemini_test.xlsx"
wb.save(path)
errs = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r[2] == "Хато")
print("::notice::MISSES " + " | ".join(misses))
print(f"::notice::elapsed={int(time.time()-T0)}s stats={STATS}")
print(f"::notice::agreement={ok}/{len(rows)} errors={errs}")
for r in ws.iter_rows(min_row=2, values_only=True):
    if r[2] == "Хато":
        print("::warning::" + str(r[10])[:180].replace(chr(10), " "))
        break
try:
    send_text(f"🧪 <b>Gemini синов</b>\nМодель: {model}\nМослик: <b>{ok}/{len(rows)}</b> визит")
    send_file(path, "Ҳар бир визит бўйича солиштирув")
    print("::notice::telegram=sent")
except BaseException as e:
    print("::error::telegram failed: " + str(e)[:200].replace(chr(10), " "))
    raise
