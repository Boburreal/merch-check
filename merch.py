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
# several free keys (different Google accounts) = several free daily limits; a model id may carry "@<key index>"
KEYS = [k for k in (os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_API_KEY_2", ""),
                    os.environ.get("GEMINI_API_KEY_3", "")) if k.strip()]


def split(model: str):
    """'gemini-x@1' -> ('gemini-x', second key)."""
    name, _, i = str(model).partition("@")
    return name, KEYS[int(i)] if i.isdigit() and int(i) < len(KEYS) else GEMINI_KEY
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
Think carefully about surface - decide by WHERE THE TWO BOXES THEMSELVES STAND, not by what is in the foreground:
- products standing on a wide, flat, mostly empty counter top in front of the customer are "counter" even if shelves are visible in the background;
- products standing on a shelf or rack BEHIND the counter (the pharmacist's side, among other medicine boxes on the same shelf) are "shelf",
  even when the counter, a calculator or a keyboard is in the foreground of the photo - the photo is often taken from the customer side, from a distance;
- several boxes of A and B stacked / lined up as a display (many facings, often behind glass) are "shelf" (a vitrina display), even when that display stands on the counter.
IMPORTANT - the counter is often made of GLASS or dark/glossy material, or has a transparent safety screen / curved glass guard standing on it:
- boxes standing on the flat top of the sales counter are "counter" EVEN IF the counter top is glass or dark, and EVEN IF a clear glass/plastic screen is next to them or in front;
- clear signs of the counter: laptop, monitor, keyboard, mouse, calculator, card terminal, receipt printer, barcode scanner, camera, desk mat, candy jar, notebook, scissors, plastic bags next to the boxes;
- "shelf" only when the boxes stand INSIDE a display cabinet / on a shelf among rows of other medicine boxes, or as a stacked display of many facings.
- Typical visit: one photo of the counter (kassa) and one photo of the display (vitrina) - judge each photo on its own.
The photo may be taken from far away: look for the small orange-yellow (A) and purple (B) boxes anywhere in the picture.
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


_CHAIN = []          # all usable free models, best first; a model whose daily quota is used up is skipped
_DEAD = set()
_SLOW = {}


def _models():
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": GEMINI_KEY}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "live", "audio", "exp", "preview", "thinking"))]
    lite = sorted([n for n in flash if "lite" in n], reverse=True)
    full = sorted([n for n in flash if "lite" not in n], reverse=True)
    # each model has its own free daily quota: flash-lite first (tested ~75%), then flash models.
    # Probe once: skip models that are overloaded (503) or retired right now, so no thread waits on them.
    combos = [(m, ki) for m in lite + full for ki in range(len(KEYS))]

    def probe(arg):
        m, ki = arg
        try:
            x = requests.post(f"{API}/models/{m}:generateContent", headers={"x-goog-api-key": KEYS[ki]}, timeout=10,
                              json={"contents": [{"parts": [{"text": "OK"}]}], "generationConfig": {"maxOutputTokens": 2}})
            return f"{m}@{ki}" if x.status_code == 200 else None
        except requests.RequestException:
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as ex:
        ok = [r for r in ex.map(probe, combos) if r]
    print(f"::notice::gemini models available ({len(ok)}/{len(combos)}): {ok}")
    return ok


def pick_model():
    global _CHAIN
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    if not _CHAIN:
        _CHAIN = _models()
    alive = [m for m in _CHAIN if m not in _DEAD]
    if not alive:
        raise DailyQuotaExceeded("all free Gemini models used up today")
    return alive[0]


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
    """Uses `model`; when its free daily quota is used up, continues with the next free model."""
    while True:
        if model in _DEAD and not os.environ.get("GEMINI_MODEL"):
            model = pick_model()
        try:
            return _ask(model, photos)
        except DailyQuotaExceeded:
            if os.environ.get("GEMINI_MODEL"):
                raise
            if model not in _DEAD:
                _DEAD.add(model)
                print(f"::warning::Gemini {model}: daily free quota used up - switching model")
            model = pick_model()          # raises DailyQuotaExceeded when nothing is left


def _ask(model: str, photos: list[bytes]) -> dict:
    parts = [{"text": PROMPT}] + ref_parts()
    for i, p in enumerate(photos, 1):
        parts += [{"text": f"PHOTO {i}"}, _img_part(p)]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    wait = 20
    for attempt in range(6):
        STATS["requests"] += 1
        _name, _key = split(model)
        r = requests.post(f"{API}/models/{_name}:generateContent",
                          headers={"x-goog-api-key": _key}, json=body, timeout=180)
        if r.status_code in (403, 404):        # model retired / not available for this key -> next model
            raise DailyQuotaExceeded(f"{model}: HTTP {r.status_code}")
        if r.status_code == 429 and ("PerDay" in r.text or "per day" in r.text.lower()):
            raise DailyQuotaExceeded(r.text[:200])
        if r.status_code == 429:
            STATS["r429"] += 1
            if STATS["r429"] <= 2:
                print("::warning::429 " + r.text[:300].replace(chr(10), " "))
        if r.status_code in (500, 503) and attempt >= 2:   # model overloaded for a while -> use another one
            _SLOW[model] = _SLOW.get(model, 0) + 1
            raise DailyQuotaExceeded(f"{model}: overloaded (HTTP {r.status_code})")
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
