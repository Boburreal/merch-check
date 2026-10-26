"""Merch photo checker: Gemini (free tier) decides Витрина / Касса / Шубҳали per visit."""
import base64, json, os, time
import requests

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
- place: "vitrina" if the products stand on a display shelf / showcase / glass cabinet among other medicines;
         "kassa" if the products stand on the counter / cash desk (near register, card terminal, keyboard, counter mat, sales window);
         "unknown" if you cannot tell
- closeup: true if the photo is taken so close that the pharmacy surroundings (shelves, counter, room) are NOT visible and the boxes fill the frame (e.g. held against a wall)
Return ONLY JSON: {"photos":[{"rinomaks":bool,"forsil":bool,"place":"...","closeup":bool},{...}]}"""


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
                return r.content
        except requests.RequestException:
            pass
        time.sleep(3)
    return None


def ask_gemini(model: str, photos: list[bytes]) -> dict:
    parts = [{"text": PROMPT}] + ref_parts()
    for i, p in enumerate(photos, 1):
        parts += [{"text": f"PHOTO {i}"}, _img_part(p)]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    wait = 20
    for attempt in range(6):
        r = requests.post(f"{API}/models/{model}:generateContent",
                          headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=180)
        if r.status_code in (429, 500, 503):
            if attempt == 5:
                r.raise_for_status()
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(txt)
    raise RuntimeError("Gemini: too many retries")


def decide(result: dict) -> dict:
    """Apply Bobur's rules: both products in ONE photo; closeups are 'suspicious'."""
    vit = kas = 0
    both_closeup = False
    for p in result.get("photos", []):
        if not (p.get("rinomaks") and p.get("forsil")):
            continue
        if p.get("closeup"):
            both_closeup = True
            continue
        if p.get("place") == "vitrina":
            vit = 1
        elif p.get("place") == "kassa":
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
