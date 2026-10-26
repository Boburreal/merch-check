"""Merch photo checker: Gemini (free tier) decides Витрина / Касса / Шубҳали per visit."""
import base64, io, json, os, time
import requests
from PIL import Image

STATS = {"requests": 0, "r429": 0, "wait_s": 0.0}


def shrink(data: bytes, side: int = 1024) -> bytes:
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((side, side))
        b = io.BytesIO(); im.save(b, "JPEG", quality=85)
        return b.getvalue()
    except Exception:
        return data

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
API = "https://generativelanguage.googleapis.com/v1beta"
HERE = os.path.dirname(os.path.abspath(__file__))

PROMPT = """You check pharmacy merchandising photos for TWO products.
Product A "RinoMaks HOT extra": orange-yellow box, big blue arrow/shield logo, text "РиноМакс" or "RinoMaks",
"ХОТ экстра" or "XOT ekstra", Russian ("при гриппе и простуде") or Uzbek ("SHAMOLLASH VA GRIPPDAN") text, lemon and cup picture.
Product B "Forsil": purple box, text "ФОРСИЛ" or "FORSIL", Nika Pharm, round body/joint pictures.
Reference images of both boxes are attached first. Then come the visit photos (PHOTO 1, PHOTO 2).
Photos may be rotated 90 degrees, blurry, behind glass, or show the boxes small and far away - look carefully at the whole image.

For EACH visit photo answer:
- rinomaks: true if Product A is visible anywhere
- forsil: true if Product B is visible anywhere
- pharmacy_visible: true if around Product A and B you can see the pharmacy itself - shelves or cabinet with other medicines, the counter, the room.
    false if the boxes are photographed so close that they fill most of the frame and the background is only a wall, a single surface or blur (typical "closeup" shot)
- surface: what A and B physically stand on:
    "shelf"   = a shelf of a display cabinet / showcase / wall rack, usually with other medicine boxes beside, above or below them on shelves (also glass display window);
    "counter" = the flat top of the sales counter / cash desk where customers are served: wide flat surface in front, often a cash register, keyboard, card terminal, monitor, counter mat or calculator nearby;
    "unknown" = cannot tell (held in hand, against a wall, too close)
Think carefully about surface: products standing on a wide, flat, mostly empty counter top are "counter" even if shelves are visible in the background.
Return ONLY JSON: {"photos":[{"rinomaks":bool,"forsil":bool,"pharmacy_visible":bool,"surface":"..."},{...}]}"""


def _img_part(data: bytes):
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(data).decode()}}


_REF = None


def ref_parts():
    global _REF
    if _REF is None:
        _REF = []
        for name, label in [("rinomaks.jpg", "REFERENCE Product A"), ("forsil.jpg", "REFERENCE Product B")]:
            with open(os.path.join(HERE, "ref", name), "rb") as f:
                _REF += [{"text": label}, _img_part(f.read())]
    return _REF


def pick_model():
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": GEMINI_KEY}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and "image" not in n and "tts" not in n
             and "live" not in n and "audio" not in n]
    # prefer the newest flash-lite (largest free daily quota), then flash
    for pref in ("flash-lite", "flash"):
        c = sorted([n for n in flash if pref in n and "preview" not in n and "exp" not in n], reverse=True)
        if c:
            return c[0]
    return sorted(flash, reverse=True)[0]


def download(url: str) -> bytes | None:
    if not url or not url.startswith("http"):
        return None
    for _ in range(3):
        try:
            r = requests.get(url, timeout=60)
            if r.ok and r.content:
                return shrink(r.content)
        except requests.RequestException:
            pass
        time.sleep(3)
    return None


class DailyQuotaExceeded(Exception):
    pass


def ask_gemini(model: str, photos: list[bytes]) -> dict:
    parts = [{"text": PROMPT}] + ref_parts()
    for i, p in enumerate(photos, 1):
        parts += [{"text": f"PHOTO {i}"}, _img_part(p)]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    wait = 20
    for attempt in range(6):
        STATS["requests"] += 1
        r = requests.post(f"{API}/models/{model}:generateContent",
                          headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=180)
        if r.status_code == 429 and ("PerDay" in r.text or "per day" in r.text.lower()):
            raise DailyQuotaExceeded(r.text[:200])
        if r.status_code == 429:
            STATS["r429"] += 1
            if STATS["r429"] <= 2:
                print("::warning::429 " + r.text[:300].replace(chr(10), " "))
        if r.status_code in (429, 500, 503):
            STATS["wait_s"] += wait
            if attempt == 5:
                if r.status_code == 429:
                    raise DailyQuotaExceeded(r.text[:200])
                r.raise_for_status()
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(txt)
    raise RuntimeError("Gemini: too many retries")


def is_closeup(p: dict) -> bool:
    return not p.get("pharmacy_visible", True)


def decide(result: dict) -> dict:
    """Apply Bobur's rules: both products in ONE photo; closeups are 'suspicious'."""
    vit = kas = 0
    both_closeup = False
    for p in result.get("photos", []):
        if not (p.get("rinomaks") and p.get("forsil")):
            continue
        if is_closeup(p) or p.get("surface") == "unknown":
            both_closeup = True
            continue
        if p.get("surface") == "shelf":
            vit = 1
        elif p.get("surface") == "counter":
            kas = 1
    if vit or kas:
        cat = "merch"
    elif both_closeup:
        cat = "suspicious"
    else:
        cat = "none"
    return {"category": cat, "vitrina": vit, "kassa": kas}


def check_visit(model: str, url1: str, url2: str) -> dict:
    photos = [p for p in (download(url1), download(url2)) if p]
    if not photos:
        return {"category": "no_photo", "vitrina": 0, "kassa": 0, "raw": None}
    raw = ask_gemini(model, photos)
    out = decide(raw)
    out["raw"] = raw
    return out


SURF = {"shelf": "витринада/полкада", "counter": "касса олдида", "unknown": "жойи аниқ эмас"}


def comment(raw) -> str:
    """Human-readable, per-photo explanation of what the AI saw."""
    if not raw or not isinstance(raw, dict):
        return ""
    out = []
    for i, p in enumerate(raw.get("photos", []), 1):
        r = "✓" if p.get("rinomaks") else "✗"
        f = "✓" if p.get("forsil") else "✗"
        t = f"Фото {i}: Риномакс {r}, Форсил {f}"
        if p.get("rinomaks") and p.get("forsil"):
            t += ", " + SURF.get(p.get("surface"), "жойи аниқ эмас")
            if not p.get("pharmacy_visible", True):
                t += ", яқин план (аптека кўринмайди)"
        out.append(t)
    return ". ".join(out)
