import os
import json
import time
import requests
import yt_dlp
from google import genai

BOT_TOKEN = os.environ["HELPER_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

HISTORY_FILE = "helper_history.json"
SEARCH_QUERIES = [
    "New Kannada Movie Official Trailer 2026",
    "Kannada Movie Box Office Collection Day 2 2026"
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
        "playlistend": 5
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for query in SEARCH_QUERIES:
            search_url = f"ytsearch5:{query}"
            info = ydl.extract_info(search_url, download=False)
            for entry in info.get("entries", []):
                vid_id = entry.get("id")
                duration = entry.get("duration") or 0
                if vid_id and vid_id not in history_list and 60 <= duration <= 480:
                    return f"https://www.youtube.com/watch?v={vid_id}", vid_id, entry.get("title", "New Video")
    return None, None, None

def generate_script(title, url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್. 
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ಮಾಹಿತಿಯನ್ನು ಆಧರಿಸಿ, ನಮ್ಮ ಚಾನೆಲ್‌ಗೆ ಸರಿಹೊಂದುವಂತೆ 3 ರಿಂದ 4 ನಿಮಿಷ ಓದುವಷ್ಟು (ಸುಮಾರು 450 ರಿಂದ 550 ಪದಗಳ) ಆಕರ್ಷಕ ಕನ್ನಡ ರಿವ್ಯೂ/ಅನಾಲಿಸಿಸ್ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಮುಖ್ಯ ನಿಯಮಗಳು:
1. ಸ್ಕ್ರಿಪ್ಟ್ ನೇರವಾಗಿ Intro ದಿಂದ ಶುರುವಾಗಲಿ (ಯಾವುದೇ ಪೀಠಿಕೆ ಅಥವಾ 'ಇಲ್ಲಿದೆ ಸ್ಕ್ರಿಪ್ಟ್' ಎಂಬ ಸಾಲುಗಳು ಬೇಡ).
2. Google AI Studio Voice (Algenib) ಓದಲು ಸುಲಭವಾಗುವಂತೆ ಕನ್ನಡ ಪದಗಳನ್ನು ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಮತ್ತು ಇಂಗ್ಲಿಷ್ ಪದಗಳನ್ನು (ಉದಾಹರಣೆಗೆ: Trailer, Box office, BGM, Action, Review, Subscribe, Collection) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ.
3. ಯಾವುದೇ ಸ್ಟಾರ್ ಚಿಹ್ನೆಗಳು (* ಅಥವಾ #) ಅಥವಾ ಎಮೋಜಿಗಳನ್ನು ಸ್ಕ್ರಿಪ್ಟ್ ಒಳಗೆ ಬಳಸಬೇಡ, ಏಕೆಂದರೆ ಇದನ್ನು ನೇರವಾಗಿ AI Studio ಗೆ ಕಾಪಿ-ಪೇಸ್ಟ್ ಮಾಡಲಾಗುತ್ತದೆ.
4. ಅಂಕಿಅಂಶಗಳನ್ನು (Numbers) ಸ್ಪಷ್ಟವಾಗಿ ಓದುವಂತೆ ಬರೆ.
5. ಕೊನೆಯಲ್ಲಿ 'MK CINEVIEW ಕನ್ನಡ' ಚಾನೆಲ್‌ಗೆ Subscribe ಮಾಡಲು ಕೇಳುವ Call to Action ಇರಲಿ.
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
        print("ಯಾವುದೇ ಹೊಸ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.")
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
    print("ಯಶಸ್ವಿಯಾಗಿ ಹೊಸ ಲಿಂಕ್ ಮತ್ತು ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸಲಾಗಿದೆ!")

if __name__ == "__main__":
    main()
