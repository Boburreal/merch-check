"""Check merch on a stratified random sample: N visits per ТП per month.
Round-robin order (rank 1 of every rep-month first, then rank 2 ...), so a partial run is still balanced.
Progress = drop/done_ids.txt (visit IDs only). Results are written to /tmp/merch_out.csv and encrypted by the workflow."""
import csv, glob, json, os, random, time, sys
from merch import check_visit, pick_model, DailyQuotaExceeded

PER = int(os.environ.get("PER_REP_MONTH", "10"))
MAX_MIN = int(os.environ.get("MAX_MINUTES", "300"))
done_path = "drop/done_ids.txt"
done = set(open(done_path).read().split()) if os.path.exists(done_path) else set()

rows = []
for f in sorted(glob.glob("/tmp/visits/visits_*.csv")):
    rows += list(csv.DictReader(open(f, encoding="utf-8-sig")))
rows = [r for r in rows if "Торг Пред" in r["Фарм. пред"]]
groups = {}
for r in rows:
    d, m, y = r["Дата"].split(".")
    groups.setdefault((r["Фарм. пред"], f"{y}-{m}"), []).append(r)
order = []
for k in sorted(groups):
    g = groups[k][:]
    random.Random(f"{k[0]}|{k[1]}").shuffle(g)
    for rank, r in enumerate(g[:PER]):
        order.append((rank, k, r))
order.sort(key=lambda x: (x[0], x[1]))
todo = [(rank, r) for rank, k, r in order if r["#"] not in done]
print(f"::notice::sample={len(order)} done={len(done)} todo={len(todo)}")

model = pick_model()
t0 = time.time(); n = 0; stop = ""
with open("/tmp/merch_out.csv", "w", newline="", encoding="utf-8") as fo:
    w = csv.writer(fo)
    w.writerow(["id", "rank", "category", "vitrina", "kassa", "raw", "model"])
    for rank, r in todo:
        if time.time() - t0 > MAX_MIN * 60:
            stop = "time"; break
        try:
            res = check_visit(model, r["Фото 1"], r["Фото 2"])
        except DailyQuotaExceeded:
            stop = "daily quota"; break
        except Exception as e:
            res = {"category": "error", "vitrina": 0, "kassa": 0, "raw": str(e)[:200]}
        w.writerow([r["#"], rank + 1, res["category"], res["vitrina"], res["kassa"],
                    json.dumps(res.get("raw"), ensure_ascii=False), model])
        fo.flush()
        if res["category"] != "error":
            done.add(r["#"])
        n += 1
        time.sleep(4)
open(done_path, "w").write("\n".join(sorted(done)))
print(f"::notice::checked now={n} total done={len(done)}/{len(order)} stop={stop or 'finished'} model={model}")
