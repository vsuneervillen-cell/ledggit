"""ledggit news fetcher. Free, standard library only.
Reads public news RSS + the weekly economic calendar, optionally asks a free
Gemini key to summarise, and writes news.json for the app."""
import json, os, time, datetime as dt, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (ledggit news bot)"}
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")  # change if Google renames it
KEY = os.environ.get("GEMINI_API_KEY", "")
CAL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"  # check its terms before going public

INSTR = {
 "gold": {"short": "Gold", "name": "XAUUSD", "q": "gold price XAUUSD", "ccy": ["USD"]},
 "eur": {"short": "EUR/USD", "name": "EURUSD", "q": "EURUSD euro dollar", "ccy": ["USD", "EUR"]},
 "gbp": {"short": "GBP/USD", "name": "GBPUSD", "q": "GBPUSD pound sterling", "ccy": ["USD", "GBP"]},
 "jpy": {"short": "USD/JPY", "name": "USDJPY", "q": "USDJPY yen dollar", "ccy": ["USD", "JPY"]},
 "oil": {"short": "Oil", "name": "USOIL", "q": "crude oil prices Brent WTI", "ccy": ["USD"]},
 "nifty": {"short": "Nifty", "name": "NIFTY", "q": "Nifty 50 Sensex market", "ccy": ["INR"]},
}

def get(url, data=None, headers=None):
    try:
        req = urllib.request.Request(url, data=data, headers=headers or UA)
        return urllib.request.urlopen(req, timeout=25).read()
    except Exception as e:
        print("fetch failed:", url[:70], e)
        return None

def headlines(q):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:2d") + "&hl=en-US&gl=US&ceid=US:en"
    raw = get(url)
    out = []
    if raw:
        try:
            for it in ET.fromstring(raw).iter("item"):
                src = it.find("source")
                out.append({"t": (it.findtext("title") or "").strip(),
                            "src": (src.text if src is not None else "News"),
                            "link": (it.findtext("link") or "")})
                if len(out) >= 8: break
        except Exception as e:
            print("rss parse failed", e)
    return out

def calendar():
    raw = get(CAL)
    try: return json.loads(raw) if raw else []
    except Exception: return []

def events_for(cal, ccy):
    res = []
    for e in cal:
        if e.get("country") in ccy and e.get("impact") in ("High", "Medium"):
            res.append(f'{str(e.get("date",""))[:16].replace("T"," ")} {e.get("country")} {e.get("title")} ({e.get("impact")}; forecast {e.get("forecast") or "n/a"}, previous {e.get("previous") or "n/a"})')
    return res[:8]

def srcs(heads):
    seen, out = set(), []
    for h in heads:
        if h["src"] not in seen and h["link"]:
            seen.add(h["src"]); out.append([h["src"], h["link"]])
    return out[:4]

def ask_ai(info, heads, events):
    if not KEY or not heads: return None
    prompt = f"""You brief retail traders in plain, friendly English. Instrument: {info['name']}.
Use ONLY the headlines and calendar events below. Do not invent prices or numbers. This is education, not advice.
Headlines: {json.dumps([h['t'] for h in heads])}
Calendar (high/medium impact this week): {json.dumps(events)}
Reply with JSON only, in this shape:
{{"head":"one short headline","plain":"2 simple sentences on what is happening and why it matters for {info['name']}","bias":number from -1 (bearish) to 1 (bullish),"tag":"2-3 word label such as Leaning cautious","pts":[["emoji","short title","one sentence"],["emoji","short title","one sentence"],["emoji","short title","one sentence"]],"watch":"the next key event to watch","plan":"one sentence on how to approach the day"}}"""
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    for _ in range(2):
        raw = get(url, body, {"Content-Type": "application/json"})
        try:
            r = json.loads(json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"])
            if all(k in r for k in ("head", "plain", "bias", "tag", "pts", "watch", "plan")) and len(r["pts"]) >= 1:
                r["bias"] = max(-1, min(1, float(r["bias"])))
                r["pts"] = [p[:3] for p in r["pts"][:3]]
                return r
        except Exception as e:
            print("ai parse failed", e)
        time.sleep(8)
    return None

def fallback(heads, events):
    return {"head": heads[0]["t"] if heads else "No fresh headlines",
            "plain": "AI summaries are switched off, so these are the latest headlines from trusted outlets. Read them with care.",
            "bias": 0, "tag": "Headlines only",
            "pts": [["\U0001F4F0", h["src"], h["t"]] for h in heads[:3]],
            "watch": events[0] if events else "Check the economic calendar for today.",
            "plan": "Keep size small until you have formed your own view."}

def main():
    cal = calendar()
    items = {}
    for k, info in INSTR.items():
        heads = headlines(info["q"])
        if not heads: continue
        ev = events_for(cal, info["ccy"])
        card = ask_ai(info, heads, ev) or fallback(heads, ev)
        card.update({"short": info["short"], "name": info["name"], "src": srcs(heads)})
        items[k] = card
        time.sleep(6)  # stay under free-tier rate limits
    if not items:
        print("Nothing fetched; keeping the old news.json"); return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y %H:%M UTC")
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump({"updated": stamp, "items": items}, f, ensure_ascii=False, indent=1)
    print("Wrote news.json with", len(items), "instruments")

main()
