"""Visit audio recordings (Запись): every ТП/МП visit records the conversation in the pharmacy.
Free check (ffmpeg, no AI limit): is there a recording, how long, how much of it is silence / how loud.
AI check (Gemini, uses the free daily limit): is it a real conversation with a pharmacist, about our products."""
import json, os, re, subprocess, tempfile, time
import requests

from sales import BASE
import merch

PROMPT = """This is an audio recording made by a pharmaceutical sales representative during a visit to a pharmacy in Uzbekistan
(speech is usually Uzbek or Russian). The rep must talk with the pharmacist: introduce the company, ask about sales,
present products (Риномакс / Rinomaks, Форсил / Forsil, Риноксил, Мирамистин, Эрегра, Тивомакс, Триомакс, Альцетро, Авирол),
ask to place merchandising (boxes on the shelf and near the cash desk).
Listen and return ONLY JSON:
{"speech": true/false (any human speech at all),
 "speakers": number of different voices talking (0,1,2,3+),
 "dialog": true/false (the rep and another person actually talk with each other),
 "pharmacy_talk": true/false (the conversation is a work conversation in a pharmacy: medicines, sales, prices, orders),
 "products": [our product names actually mentioned],
 "merch_talk": true/false (asking to place / check boxes on shelf or cash desk),
 "talk_seconds": estimated seconds of speech,
 "summary": one short sentence in Russian about what happened in the recording}"""


def audio_url(s, vid: int):
    r = s.get(f"{BASE}/lists/visits/{vid}/result", timeout=60)
    m = re.search(r'<source[^>]+src="([^"]+)"', r.text) or re.search(r'<audio[^>]+src="([^"]+)"', r.text)
    return m.group(1) if m else None


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def measure(path: str) -> dict:
    """Duration, silence share and loudness with ffmpeg (free)."""
    dur = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout.strip()
    dur = float(dur) if dur and dur != "N/A" else 0.0
    out = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                "silencedetect=noise=-38dB:d=1.5,volumedetect", "-f", "null", "-"]).stderr
    sil = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", out))
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", out)
    return {"dur": round(dur, 1), "silence_pct": round(sil / dur * 100) if dur else 100,
            "mean_db": float(mean.group(1)) if mean else None, "max_db": float(peak.group(1)) if peak else None}


def ask_ai(model: str, data: bytes, mime: str) -> dict:
    import base64
    body = {"contents": [{"parts": [{"text": PROMPT}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    wait = 20
    for attempt in range(5):
        r = requests.post(f"{merch.API}/models/{model}:generateContent", headers={"x-goog-api-key": merch.GEMINI_KEY},
                          json=body, timeout=240)
        if r.status_code in (403, 404) or (r.status_code == 429 and ("PerDay" in r.text or "per day" in r.text.lower())):
            raise merch.DailyQuotaExceeded(f"{model}: {r.status_code}")
        if r.status_code in (429, 500, 503):
            time.sleep(wait); wait = min(wait * 2, 120); continue
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().removeprefix("```json").removesuffix("```")
        d = json.loads(txt)
        return d[0] if isinstance(d, list) else d
    raise RuntimeError("Gemini audio: too many retries")


def ai(data: bytes, mime: str) -> dict:
    """Same model rotation as the merch check (next free model when one's daily limit ends)."""
    model = merch.pick_model()
    while True:
        try:
            return ask_ai(model, data, mime)
        except merch.DailyQuotaExceeded:
            merch._DEAD.add(model)
            model = merch.pick_model()


MIME = {"aac": "audio/aac", "m4a": "audio/mp4", "mp3": "audio/mp3", "ogg": "audio/ogg", "wav": "audio/wav", "webm": "audio/webm",
        "3gp": "audio/3gpp", "amr": "audio/amr", "flac": "audio/flac"}


def verdict(m: dict, a: dict | None) -> tuple[str, str]:
    """(status, reason) in Russian for the Excel file. 'Подозрительная' means 'listen to it', not 'fraud'."""
    if m is None:
        return "Нет записи", "У визита нет аудиозаписи"
    notes = []
    if m["dur"] < 30:
        notes.append(f"очень короткая ({m['dur']:.0f} сек)")
    if m["silence_pct"] >= 85:
        notes.append(f"{m['silence_pct']}% записи — тишина")
    if m["max_db"] is not None and m["max_db"] < -30:
        notes.append("звука почти нет (очень тихо)")
    if a:
        if not a.get("speech"):
            notes.append("ИИ: речи не слышно")
        elif not a.get("dialog"):
            notes.append("ИИ: разговора нет, говорит один человек" if a.get("speakers", 0) == 1 else "ИИ: диалог не распознан")
        elif not a.get("pharmacy_talk"):
            notes.append("ИИ: разговор не об аптеке/лекарствах")
    if notes:
        return "Подозрительная", "; ".join(notes)
    return "Норма", ""


def check(s, vid: int, use_ai: bool = False) -> dict:
    url = audio_url(s, vid)
    if not url:
        st, com = verdict(None, None)
        return {"id": vid, "url": "", "dur": 0, "silence_pct": None, "status": st, "comment": com, "ai": ""}
    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
    with tempfile.NamedTemporaryFile(suffix="." + ext) as f:
        data = s.get(url, timeout=120).content
        f.write(data); f.flush()
        m = measure(f.name)
        a = None
        if use_ai and m["dur"] >= 5 and m["silence_pct"] < 97:
            try:
                a = ai(data, MIME.get(ext, "audio/aac"))
            except merch.DailyQuotaExceeded:
                a = None
    st, com = verdict(m, a)
    ai_txt = ""
    if a:
        ai_txt = (f"{a.get('summary', '')} (голосов: {a.get('speakers')}, речь ~{a.get('talk_seconds')} сек"
                  + (f", препараты: {', '.join(a.get('products') or [])}" if a.get('products') else "")
                  + (", говорили о мерче" if a.get('merch_talk') else "") + ")")
    return {"id": vid, "url": url, "dur": m["dur"], "silence_pct": m["silence_pct"], "status": st, "comment": com, "ai": ai_txt,
            "products": ", ".join(a.get("products") or []) if a else ""}
