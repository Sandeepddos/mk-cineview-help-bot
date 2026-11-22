import os
import json
import time
import urllib.parse
from datetime import datetime, timedelta
import requests
import yt_dlp
from google import genai

BOT_TOKEN = os.environ["HELPER_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

HISTORY_FILE = "helper_history.json"

SEARCH_QUERIES = [
    "New Kannada Movie Official Trailer 2026",
    "Kannada Movie Official Teaser 2026",
    "Kannada Movie Box Office Collection 2026",
    "Pan India Movie Official Trailer 2026",
    "New Telugu Movie Official Trailer 2026",
    "New Tamil Movie Official Trailer 2026",
    "New Hindi Movie Official Trailer 2026",
    "Indian Movie Box Office Collection Today 2026"
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

def is_recent_video(entry, ydl):
    up_date = entry.get("upload_date")
    if not up_date:
        try:
            full_info = ydl.extract_info(f"https://www.youtube.com/watch?v={entry['id']}", download=False)
            up_date = full_info.get("upload_date")
        except Exception:
            return False

    if not up_date:
        return False

    try:
        video_dt = datetime.strptime(up_date, "%Y%m%d")
        # ಭಾರತೀಯ ಕಾಲಮಾನ (IST = UTC + 5:30) ಪ್ರಕಾರ ಕಳೆದ 2 ದಿನಗಳ (ಇಂದು ಮತ್ತು ನಿನ್ನೆ) ವಿಡಿಯೋ ಮಾತ್ರ ತೆಗೆದುಕೊಳ್ಳುತ್ತದೆ
        ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        cutoff_dt = ist_now - timedelta(days=2)
        return video_dt.date() >= cutoff_dt.date()
    except Exception:
        return False

def search_latest_video(history_list):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": 6
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for query in SEARCH_QUERIES:
            encoded_q = urllib.parse.quote(query)
            # sp=EgIIAg%253D%253D -> YouTube ನ 'Last 24 hours (Today)' ಫಿಲ್ಟರ್
            search_url = f"https://www.youtube.com/results?search_query={encoded_q}&sp=EgIIAg%253D%253D"
            try:
                info = ydl.extract_info(search_url, download=False)
            except Exception as e:
                print(f"ಸರ್ಚ್ ಎರರ್: {e}")
                continue

            for entry in info.get("entries", []):
                vid_id = entry.get("id")
                duration = entry.get("duration") or 0
                if vid_id and vid_id not in history_list and 60 <= duration <= 480:
                    if is_recent_video(entry, ydl):
                        return f"https://www.youtube.com/watch?v={vid_id}", vid_id, entry.get("title", "New Video")
                    else:
                        print(f"ಹಳೆಯ ವಿಡಿಯೋ ಸ್ಕಿಪ್ ಮಾಡಲಾಗಿದೆ: {entry.get('title')}")
    return None, None, None

def generate_script(title, url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್. 
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ಮಾಹಿತಿಯನ್ನು ಆಧರಿಸಿ (ಅದು ಕನ್ನಡ, ತೆಲುಗು, ತಮಿಳು, ಹಿಂದಿ ಅಥವಾ ಯಾವುದೇ Pan-India ಸಿನಿಮಾವಾಗಿದ್ದರೂ ಸರಿ), ನಮ್ಮ ಕನ್ನಡ ಪ್ರೇಕ್ಷಕರಿಗೆ ಸರಿಹೊಂದುವಂತೆ 3 ರಿಂದ 4 ನಿಮಿಷ ಓದುವಷ್ಟು (ಸುಮಾರು 450 ರಿಂದ 550 ಪದಗಳ) ಆಕರ್ಷಕ ಕನ್ನಡ ರಿವ್ಯೂ/ಅನಾಲಿಸಿಸ್ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಮುಖ್ಯ ನಿಯಮಗಳು:
1. ಸ್ಕ್ರಿಪ್ಟ್ ನೇರವಾಗಿ Intro ದಿಂದ ಶುರುವಾಗಲಿ (ಯಾವುದೇ ಪೀಠಿಕೆ ಅಥವಾ 'ಇಲ್ಲಿದೆ ಸ್ಕ್ರಿಪ್ಟ್' ಎಂಬ ಸಾಲುಗಳು ಬೇಡ).
2. ಬೇರೆ ಭಾಷೆಯ ಸಿನಿಮಾವಾಗಿದ್ದರೆ, ಕರ್ನಾಟಕದ ಪ್ರೇಕ್ಷಕರಿಗೆ ಮತ್ತು ಸ್ಯಾಂಡಲ್‌ವುಡ್ ಅಭಿಮಾನಿಗಳಿಗೆ ಈ ಸಿನಿಮಾ ಯಾಕೆ ವಿಶೇಷ, ಇದರ ಪ್ಲಸ್ ಪಾಯಿಂಟ್ಸ್ ಏನು ಎಂಬುದನ್ನು ಕನ್ನಡದಲ್ಲೇ ರೋಚಕವಾಗಿ ವಿವರಿಸು.
3. Google AI Studio Voice (Algenib) ಓದಲು ಸುಲಭವಾಗುವಂತೆ ಕನ್ನಡ ಪದಗಳನ್ನು ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಮತ್ತು ಇಂಗ್ಲಿಷ್ ಪದಗಳನ್ನು (ಉದಾಹರಣೆಗೆ: Trailer, Teaser, Pan-India, Box office, BGM, Action, Review, Subscribe, Collection) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ.
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
        print("ಯಾವುದೇ ಹೊಸ ಟ್ರೈಲರ್ ಅಥವಾ ಬಾಕ್ಸ್ ಆಫೀಸ್ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.")
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
