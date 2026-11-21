import os
import json
import time
import glob
import subprocess
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
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history[-100:], f, indent=2)

def search_latest_video(history):
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
                if vid_id and vid_id not in history and 60 <= duration <= 480:
                    return f"https://www.youtube.com/watch?v={vid_id}", vid_id, entry.get("title", "New Video")
    return None, None, None

def try_download_video(url):
    os.makedirs("temp_media", exist_ok=True)
    video_path = "temp_media/video.mp4"
    
    ydl_opts = {
        "format": "best[height<=720][ext=mp4][filesize<48M]/best[height<=480][ext=mp4]/best[ext=mp4]",
        "outtmpl": video_path,
        "quiet": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["tv_embedded", "ios", "android"],
                "player_skip": ["webpage", "configs"]
            }
        },
    }
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if os.path.exists(video_path):
                return video_path, info
    except Exception as e:
        print(f"ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಬ್ಲಾಕ್ ಆಗಿದೆ (Fallback ಬಳಸಲಾಗುತ್ತಿದೆ): {e}")
    return None, {}

def extract_14_frames(video_path, duration):
    os.makedirs("temp_media/frames", exist_ok=True)
    start_sec = 8 if duration > 30 else 2
    usable_duration = max(duration - 16, 10)
    fps_rate = 14 / usable_duration

    cmd = [
        "ffmpeg", "-ss", str(start_sec), "-t", str(usable_duration),
        "-i", video_path, "-vf", f"fps={fps_rate},scale=1280:-1",
        "-vframes", "14", "-q:v", "2", "temp_media/frames/frame_%02d.jpg",
        "-hide_banner", "-loglevel", "error"
    ]
    subprocess.run(cmd, check=True)
    return sorted(glob.glob("temp_media/frames/frame_*.jpg"))

def generate_script(title, channel, description, url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್. 
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ಮಾಹಿತಿಯನ್ನು ಆಧರಿಸಿ, ನಮ್ಮ ಚಾನೆಲ್‌ಗೆ ಸರಿಹೊಂದುವಂತೆ 3 ರಿಂದ 4 ನಿಮಿಷ ಓದುವಷ್ಟು (ಸುಮಾರು 450 ರಿಂದ 550 ಪದಗಳ) ಆಕರ್ಷಕ ಕನ್ನಡ ರಿವ್ಯೂ/ಅನಾಲಿಸಿಸ್ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- Channel: {channel}
- URL: {url}
- Description: {description[:1500]}

ಮುಖ್ಯ ನಿಯಮಗಳು:
1. ಸ್ಕ್ರಿಪ್ಟ್ ನೇರವಾಗಿ Intro ದಿಂದ ಶುರುವಾಗಲಿ (ಯಾವುದೇ ಪೀಠಿಕೆ ಅಥವಾ 'ಇಲ್ಲಿದೆ ಸ್ಕ್ರಿಪ್ಟ್' ಎಂಬ ಸಾಲುಗಳು ಬೇಡ).
2. AI Voice ಓದಲು ಸುಲಭವಾಗುವಂತೆ ಕನ್ನಡ ಪದಗಳನ್ನು ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಮತ್ತು ಇಂಗ್ಲಿಷ್ ಪದಗಳನ್ನು (ಉದಾಹರಣೆಗೆ: Trailer, Box office, BGM, Action, Review, Subscribe, Collection) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ.
3. ಅಂಕಿಅಂಶಗಳನ್ನು (Numbers) ಸ್ಪಷ್ಟವಾಗಿ ಓದುವಂತೆ ಬರೆ.
4. ಕೊನೆಯಲ್ಲಿ 'MK CINEVIEW ಕನ್ನಡ' ಚಾನೆಲ್‌ಗೆ Subscribe ಮಾಡಲು ಕೇಳುವ Call to Action ಇರಲಿ.
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

def send_to_telegram(url, vid_id, video_path, frames, script_text, title):
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    caption = f"🎬 <b>{title}</b>\n\n🔗 <b>YouTube Link:</b> {url}"

    # 1. ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಆಗಿದ್ದರೆ ವಿಡಿಯೋ ಕಳುಹಿಸುತ್ತದೆ, ಇಲ್ಲದಿದ್ದರೆ ಥಂಬ್‌ನೇಲ್ + ಲಿಂಕ್ ಕಳುಹಿಸುತ್ತದೆ
    if video_path and os.path.exists(video_path) and os.path.getsize(video_path) < 49 * 1024 * 1024:
        with open(video_path, "rb") as vf:
            requests.post(
                f"{base_url}/sendVideo",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"video": vf}
            )
    else:
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

    # 2. ಫೋಟೋಗಳು ಕಟ್ ಆಗಿದ್ದರೆ 2 ಆಲ್ಬಮ್‌ಗಳಾಗಿ ಕಳುಹಿಸುತ್ತದೆ
    if frames:
        for i in range(0, len(frames), 7):
            chunk = frames[i:i+7]
            media = []
            files = {}
            for idx, img_path in enumerate(chunk):
                key = f"photo{idx}"
                files[key] = open(img_path, "rb")
                media.append({"type": "photo", "media": f"attach://{key}"})
            
            requests.post(
                f"{base_url}/sendMediaGroup",
                data={"chat_id": CHAT_ID, "media": json.dumps(media)},
                files=files
            )
            for f in files.values():
                f.close()
            time.sleep(2)

    # 3. 3-4 ನಿಮಿಷದ ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸುವುದು
    header = "📝 <b>3-4 ನಿಮಿಷದ AI ಸ್ಕ್ರಿಪ್ಟ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

def main():
    history = load_history()
    url, vid_id, search_title = search_latest_video(history)
    if not url:
        print("ಯಾವುದೇ ಹೊಸ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.")
        return

    print(f"ಹೊಸ ವಿಡಿಯೋ ಸಿಕ್ಕಿದೆ: {url}")
    video_path, info = try_download_video(url)
    
    title = info.get("title") or search_title
    channel = info.get("channel") or "Kannada Cinema"
    description = info.get("description") or title
    duration = info.get("duration") or 120

    frames = []
    if video_path:
        frames = extract_14_frames(video_path, duration)

    script_text = generate_script(title, channel, description, url)
    send_to_telegram(url, vid_id, video_path, frames, script_text, title)

    history.append(vid_id)
    save_history(history)
    print("ಎಲ್ಲವೂ ಯಶಸ್ವಿಯಾಗಿ ಹೊಸ Telegram Bot ಗೆ ರವಾನೆಯಾಗಿದೆ!")

if __name__ == "__main__":
    main()
