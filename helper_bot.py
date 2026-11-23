import os
import json
import time
import urllib.parse
import requests
import yt_dlp
from google import genai

BOT_TOKEN = os.environ["HELPER_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

HISTORY_FILE = "helper_history.json"

# ಹಂತ 1: ಮೊದಲು ಸಂಪೂರ್ಣವಾಗಿ ಕನ್ನಡ ಸಿನಿಮಾ (ಟ್ರೈಲರ್, OTT, ಬಾಕ್ಸ್ ಆಫೀಸ್) ಮಾತ್ರ ಹುಡುಕುತ್ತದೆ
# ಹಂತ 2: ಕನ್ನಡದಲ್ಲಿ ಕಳೆದ 24 ಗಂಟೆಗಳಲ್ಲಿ ಏನೂ ಸಿಗದಿದ್ದರೆ ಮಾತ್ರ ಕೊನೆಯ 3 ಬೇರೆ ಭಾಷೆ/Pan-India ಕಡೆ ಹೋಗುತ್ತದೆ
SEARCH_QUERIES = [
    # --- ಕನ್ನಡಕ್ಕೆ ಮೊದಲ ಆದ್ಯತೆ (Kannada Priority) ---
    "New Kannada Movie Official Trailer 2026",
    "ಕನ್ನಡ ಹೊಸ ಸಿನಿಮಾ ಟ್ರೈಲರ್ 2026",
    "Kannada New OTT Releases This Week 2026",
    "ಕನ್ನಡ ಹೊಸ OTT ಸಿನಿಮಾಗಳು 2026",
    "Kannada Movies Releasing This Week 2026",
    "Kannada Movie Official Teaser 2026",
    "Kannada Movie Box Office Collection 2026",

    # --- ಕನ್ನಡ ಸಿಗದಿದ್ದರೆ ಮಾತ್ರ ಬೇರೆ ಭಾಷೆ / Pan-India ---
    "Pan India Movie Official Trailer 2026",
    "New OTT Releases Today Kannada Telugu Tamil 2026",
    "Indian Movie Box Office Collection Today 2026"
]

# ಬೇರೆಯವರ ರಿವ್ಯೂ, ಫೇಕ್ ಟ್ರೈಲರ್ ಅಥವಾ ಅನಗತ್ಯ ವಿಡಿಯೋಗಳನ್ನು ತಡೆಯಲು:
IGNORE_WORDS = [
    "review", "explained", "ending", "concept", "fan made", "fan-made",
    "spoof", "reaction", "full movie", "roast", "breakdown", "dubbed"
]

# ಟೈಟಲ್‌ನಲ್ಲಿ ಈ ಪದಗಳಲ್ಲಿ ಒಂದಾದರೂ ಇರಲೇಬೇಕು (ಕನ್ನಡ & ಇಂಗ್ಲಿಷ್ ಎರಡೂ ಸೇರಿಸಲಾಗಿದೆ):
REQUIRED_WORDS = [
    "official trailer", "official teaser", "releasing this week",
    "ott release", "ott releases", "box office", "new trailer",
    "ಟ್ರೈಲರ್", "ಟೀಸರ್", "ಬಾಕ್ಸ್ ಆಫೀಸ್", "ರಿಲೀಸ್"
]

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("videos", [])
            return data
    return []

def save_history(videos):
    with open(HISTORY_FILE, "w") as f:
        json.dump(videos[-100:], f, indent=2)

def search_latest_video(history_list):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": 10
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for query in SEARCH_QUERIES:
            encoded_q = urllib.parse.quote(query)
            # sp=EgIIAg%253D%253D -> ಕಳೆದ 24 ಗಂಟೆಗಳ (Today) ಫಿಲ್ಟರ್
            search_url = f"https://www.youtube.com/results?search_query={encoded_q}&sp=EgIIAg%253D%253D"
            try:
                info = ydl.extract_info(search_url, download=False)
            except Exception as e:
                print(f"ಸರ್ಚ್ ಎರರ್: {e}")
                continue

            for entry in info.get("entries", []):
                vid_id = entry.get("id")
                title = entry.get("title") or ""
                title_lower = title.lower()
                duration = entry.get("duration") or 0
                view_count = entry.get("view_count") or 0
                
                if not vid_id or vid_id in history_list:
                    continue
                
                # 1 ನಿಮಿಷದಿಂದ 6 ನಿಮಿಷದ ಒಳಗಿನ ವಿಡಿಯೋ
                if not (60 <= duration <= 360):
                    continue

                if any(bad in title_lower for bad in IGNORE_WORDS):
                    continue

                if not any(req in title_lower for req in REQUIRED_WORDS):
                    continue

                # ಕನ್ನಡ OTT / ವಾರದ ರಿಲೀಸ್ ವಿಡಿಯೋಗಳಿಗೆ ಕನಿಷ್ಠ 1,000 ವ್ಯೂಸ್, ಟ್ರೈಲರ್‌ಗಳಿಗೆ 8,000 ವ್ಯೂಸ್ ಚೆಕ್
                is_kannada_query = ("kannada" in query.lower() or "ಕನ್ನಡ" in query)
                if "ott" in title_lower or "week" in title_lower or "ರಿಲೀಸ್" in title_lower:
                    min_views = 1000 if is_kannada_query else 3000
                else:
                    min_views = 5000 if is_kannada_query else 15000

                if view_count > 0 and view_count < min_views:
                    continue

                return f"https://www.youtube.com/watch?v={vid_id}", vid_id, title
    return None, None, None

def generate_script(title, url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್. 
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ವಿಷಯವನ್ನು ಆಧರಿಸಿ (ಕನ್ನಡ ಸಿನಿಮಾದ ಟ್ರೈಲರ್, OTT ರಿಲೀಸ್ ಅಪ್‌ಡೇಟ್, ಬಾಕ್ಸ್ ಆಫೀಸ್ ಕಲೆಕ್ಷನ್ ಅಥವಾ Pan-India ಸಿನಿಮಾ ಅಪ್‌ಡೇಟ್), ನಮ್ಮ ಕನ್ನಡ ಪ್ರೇಕ್ಷಕರಿಗೆ ಸರಿಹೊಂದುವಂತೆ 3 ರಿಂದ 4 ನಿಮಿಷ ಓದುವಷ್ಟು (ಸುಮಾರು 450 ರಿಂದ 550 ಪದಗಳ) ಆಕರ್ಷಕ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಮುಖ್ಯ ನಿಯಮಗಳು:
1. ಸ್ಕ್ರಿಪ್ಟ್ ನೇರವಾಗಿ Intro ದಿಂದ ಶುರುವಾಗಲಿ (ಯಾವುದೇ ಪೀಠಿಕೆ ಅಥವಾ 'ಇಲ್ಲಿದೆ ಸ್ಕ್ರಿಪ್ಟ್' ಎಂಬ ಸಾಲುಗಳು ಬೇಡ).
2. OTT ರಿಲೀಸ್ ಅಪ್‌ಡೇಟ್ ಆಗಿದ್ದರೆ ಯಾವ ಸಿನಿಮಾ ಯಾವ OTT ಪ್ಲಾಟ್‌ಫಾರ್ಮ್‌ನಲ್ಲಿ (Prime Video, Netflix, Zee5, JioHotstar, Sun NXT) ಬರುತ್ತಿದೆ ಎಂಬುದನ್ನು ಸ್ಪಷ್ಟವಾಗಿ ವಿವರಿಸು. ಬಾಕ್ಸ್ ಆಫೀಸ್ ಕಲೆಕ್ಷನ್ ಆಗಿದ್ದರೆ ಗಳಿಕೆಯ ಅಂಕಿಅಂಶಗಳನ್ನು ರೋಚಕವಾಗಿ ಹೇಳು.
3. Google AI Studio Voice (Algenib) ಓದಲು ಸುಲಭವಾಗುವಂತೆ ಕನ್ನಡ ಪದಗಳನ್ನು ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಮತ್ತು ಇಂಗ್ಲಿಷ್ ಪದಗಳನ್ನು (ಉದಾಹರಣೆಗೆ: Trailer, Teaser, OTT, Prime Video, Netflix, Zee5, JioHotstar, Box office, BGM, Action, Review, Subscribe, Collection) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ.
4. ಯಾವುದೇ ಸ್ಟಾರ್ ಚಿಹ್ನೆಗಳು (* ಅಥವಾ #) ಅಥವಾ ಎಮೋಜಿಗಳನ್ನು ಸ್ಕ್ರಿಪ್ಟ್ ಒಳಗೆ ಬಳಸಬೇಡ, ಏಕೆಂದರೆ ಇದನ್ನು ನೇರವಾಗಿ AI Studio ಗೆ ಕಾಪಿ-ಪೇಸ್ಟ್ ಮಾಡಲಾಗುತ್ತದೆ.
5. ಅಂಕಿಅಂಶಗಳನ್ನು (Numbers) ಸ್ಪಷ್ಟವಾಗಿ ಓದುವಂತೆ ಬರೆ.
6. ಕೊನೆಯಲ್ಲಿ 'MK CINEVIEW ಕನ್ನಡ' ಚಾನೆಲ್‌ಗೆ Subscribe ಮಾಡಲು ಕೇಳುವ Call to Action ಇರಲಿ.
"""
    available_models = []
    for m in client.models.list():
        name = m.name.replace("models/", "")
        if "gemini" in name and ("flash" in name or "pro" in name) and "tts" not in name and "image" not in name:
            available_models.append(name)

    for model_name in available_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            print(f"ಯಶಸ್ವಿಯಾಗಿ ಬಳಸಿದ ಮಾಡೆಲ್: {model_name}")
            return response.text
        except Exception:
            continue
    raise RuntimeError("ಯಾವುದೇ Gemini ಮಾಡೆಲ್ ಲಭ್ಯವಾಗಲಿಲ್ಲ.")

def main():
    history = load_history()
    url, vid_id, search_title = search_latest_video(history)
    
    if not url:
        print("ಕಳೆದ 24 ಗಂಟೆಗಳಲ್ಲಿ ಯಾವುದೇ ಹೊಸ ಟ್ರೈಲರ್, OTT ಅಥವಾ ಬಾಕ್ಸ್ ಆಫೀಸ್ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.")
        return

    print(f"ಹೊಸ ವಿಡಿಯೋ ಸಿಕ್ಕಿದೆ: {url}")
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    caption = f"🎬 <b>{search_title}</b>\n\n🔗 <b>YouTube Link:</b> {url}"
    thumb_url = f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg"
    
    res = requests.post(
        f"{base_url}/sendPhoto",
        data={"chat_id": CHAT_ID, "photo": thumb_url, "caption": caption, "parse_mode": "HTML"}
    )
    if not res.ok:
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"}
        )

    time.sleep(2)
    script_text = generate_script(search_title, url)
    
    header = "📝 <b>3-4 ನಿಮಿಷದ AI ಸ್ಕ್ರಿಪ್ಟ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

    history.append(vid_id)
    save_history(history)
    print("ಯಶಸ್ವಿಯಾಗಿ ಹೊಸ ವಿಡಿಯೋ ಲಿಂಕ್ ಮತ್ತು ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸಲಾಗಿದೆ!")

if __name__ == "__main__":
    main()
