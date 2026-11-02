"""Merch check by Claude (when the free Gemini quota is used up).
STEP=export DAY=YYYY-MM-DD : unchecked ТП visits of the day -> photos (2 per visit, side by side) -> encrypted drop for Claude
STEP=import DAY=YYYY-MM-DD : Claude's encrypted decisions -> merged into the normal merch store (m_<day>)
No personal data is printed."""
import datetime as dt, io, json, os, subprocess, tarfile
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from PIL import Image, ImageDraw
import store
from merch import download, decide, comment

STEP, DAY = os.environ["STEP"], dt.date.fromisoformat(os.environ["DAY"])
NAME = f"m_{DAY.isoformat()}"
OUT = f"drop/cm_{DAY:%Y%m%d}"


def composite(photos, n):
    ims = []
    for p in photos:
        try:
            im = Image.open(io.BytesIO(p)).convert("RGB"); im.thumbnail((720, 720)); ims.append(im)
        except Exception:
            pass
    if not ims:
        return None
    h = max(i.height for i in ims); w = sum(i.width for i in ims) + 10 * (len(ims) - 1)
    c = Image.new("RGB", (w, h + 28), "white"); x = 0
    for k, im in enumerate(ims, 1):
        c.paste(im, (x, 28)); ImageDraw.Draw(c).text((x + 4, 6), f"#{n}  PHOTO {k}", fill="red"); x += im.width + 10
    b = io.BytesIO(); c.save(b, "JPEG", quality=80); return b.getvalue()


if STEP == "export":
    from export import fetch
    from analysis import prepare
    tp = prepare(fetch(1, DAY, DAY), 'ТП', store.load('loc_log'))
    tp = tp[tp.day.dt.date == DAY]
    old = store.load(NAME)
    done = set(old.loc[old['category'] != 'error', 'id'].astype(int)) if len(old) else set()
    todo = tp[~tp.id.isin(done) & tp['Лавозим'].str.contains('Торг')].reset_index(drop=True)
    os.makedirs("/tmp/cm", exist_ok=True)

    def one(arg):
        n, r = arg
        ph = [p for p in (download(r['Фото 1']), download(r['Фото 2'])) if p]
        img = composite(ph, n) if ph else None
        if img:
            open(f"/tmp/cm/{n:04d}.jpg", "wb").write(img)
        return n, int(r['id']), len(ph)
    with ThreadPoolExecutor(12) as ex:
        idx = pd.DataFrame(list(ex.map(one, todo.iterrows())), columns=['n', 'id', 'photos'])
    idx.to_csv("/tmp/cm/index.csv", index=False)
    with tarfile.open("/tmp/cm.tgz", "w:gz") as t:
        t.add("/tmp/cm", arcname="cm")
    key = os.urandom(32); open("/tmp/k.bin", "wb").write(key.hex().encode())
    store.save_bytes(f"cmkey_{DAY:%Y%m%d}", key.hex().encode())          # import step decrypts Claude's answer with it
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", "/tmp/cm.tgz", "-out", OUT + ".enc",
                    "-pass", "file:/tmp/k.bin"], check=True)
    subprocess.run(["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", "drop_pub.pem", "-in", "/tmp/k.bin",
                    "-out", OUT + ".key"], check=True)
    os.remove("/tmp/k.bin")
    print(f"::notice::claude export {DAY}: tp_day={len(tp)} todo={len(todo)} no_photo={(idx.photos == 0).sum()}")

else:
    open("/tmp/k.bin", "wb").write(store.load_bytes(f"cmkey_{DAY:%Y%m%d}"))
    subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", OUT + "_res.enc", "-out", "/tmp/res.csv",
                    "-pass", "file:/tmp/k.bin"], check=True)
    os.remove("/tmp/k.bin")
    res = pd.read_csv("/tmp/res.csv", dtype=str)        # columns: id, raw (JSON in the Gemini format) or category=no_photo
    rows = []
    for r in res.itertuples(index=False):
        if r.raw == 'no_photo':
            rows.append({"id": int(r.id), "category": "no_photo", "vitrina": 0, "kassa": 0, "comment": "Фото йўқ", "raw": ""})
            continue
        raw = json.loads(r.raw); d = decide(raw)
        rows.append({"id": int(r.id), **d, "comment": "Claude: " + comment(raw), "raw": json.dumps(raw, ensure_ascii=False)})
    new = pd.DataFrame(rows)
    old = store.load(NAME)
    if len(old):
        old = old[~old['id'].astype(int).isin(set(new['id']))]
        new = pd.concat([old, new.astype(str)], ignore_index=True)
    store.save(NAME, new)
    for f in (OUT + ".enc", OUT + ".key", OUT + "_res.enc", f"drop/store/cmkey_{DAY:%Y%m%d}.fer"):
        if os.path.exists(f):
            os.remove(f)
    print(f"::notice::claude import {DAY}: added={len(rows)} cats={pd.DataFrame(rows)['category'].value_counts().to_dict()}")
