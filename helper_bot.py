import os
import json
import time
import glob
import subprocess
import requests
import yt_dlp
from google import genai

# Environment Variables (GitHub Secrets ನಿಂದ ಬರುತ್ತವೆ)
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
                # 1 ನಿಮಿಷದಿಂದ 8 ನಿಮಿಷದ ಒಳಗಿನ ಹೊಸ ವಿಡಿಯೋ ಮಾತ್ರ ಆಯ್ಕೆ ಮಾಡುತ್ತದೆ
                if vid_id and vid_id not in history and 60 <= duration <= 480:
                    return f"https://www.youtube.com/watch?v={vid_id}", vid_id
    return None, None

def download_video_and_info(url):
    os.makedirs("temp_media", exist_ok=True)
    video_path = "temp_media/video.mp4"
    
    ydl_opts = {
        # Telegram 50MB ಲಿಮಿಟ್ ಒಳಗಿರಲು 480p/720p MP4 ಫಾರ್ಮ್ಯಾಟ್
        "format": "best[height<=720][ext=mp4][filesize<48M]/best[height<=480][ext=mp4]/best[ext=mp4]",
        "outtmpl": video_path,
        "quiet": True,
    }
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return video_path, info

def extract_14_frames(video_path, duration):
    os.makedirs("temp_media/frames", exist_ok=True)
    # ಮೊದಲ 8 ಸೆಕೆಂಡ್ ಮತ್ತು ಕೊನೆಯ 8 ಸೆಕೆಂಡ್ ಟೈಟಲ್ ಕಾರ್ಡ್ ಬಿಟ್ಟು ಮಧ್ಯದ ಭಾಗ ಕಟ್ ಮಾಡುತ್ತದೆ
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

def generate_script(info, url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    title = info.get("title", "")
    channel = info.get("channel", "")
    description = (info.get("description") or "")[:1500]

    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್. 
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ಮಾಹಿತಿಯನ್ನು ಆಧರಿಸಿ, ನಮ್ಮ ಚಾನೆಲ್‌ಗೆ ಸರಿಹೊಂದುವಂತೆ 3 ರಿಂದ 4 ನಿಮಿಷ ಓದುವಷ್ಟು (ಸುಮಾರು 450 ರಿಂದ 550 ಪದಗಳ) ಆಕರ್ಷಕ ಕನ್ನಡ ರಿವ್ಯೂ/ಅನಾಲಿಸಿಸ್ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- Channel: {channel}
- URL: {url}
- Description: {description}

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

def send_to_telegram(url, video_path, frames, script_text, title):
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # 1. ಯೂಟ್ಯೂಬ್ ಲಿಂಕ್ ಮತ್ತು ವಿಡಿಯೋ ಫೈಲ್ ಕಳುಹಿಸುವುದು
    caption = f"🎬 <b>{title}</b>\n\n🔗 <b>YouTube Link:</b> {url}"
    if os.path.exists(video_path) and os.path.getsize(video_path) < 49 * 1024 * 1024:
        with open(video_path, "rb") as vf:
            requests.post(
                f"{base_url}/sendVideo",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"video": vf}
            )
    else:
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"}
        )

    time.sleep(2)

    # 2. 14 ಫೋಟೋಗಳನ್ನು 2 ಆಲ್ಬಮ್‌ಗಳಾಗಿ (7 + 7) ಕಳುಹಿಸುವುದು (Telegram ಒಂದೇ ಆಲ್ಬಮ್‌ನಲ್ಲಿ ಗರಿಷ್ಠ 10 ಫೋಟೋ ಮಾತ್ರ ಅನುಮತಿಸುತ್ತದೆ)
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

    # 3. 3-4 ನಿಮಿಷದ ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸುವುದು (4000 ಅಕ್ಷರಕ್ಕಿಂತ ಹೆಚ್ಚಿದ್ದರೆ ಭಾಗ ಮಾಡಿ ಕಳುಹಿಸುತ್ತದೆ)
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
    url, vid_id = search_latest_video(history)
    if not url:
        print("ಯಾವುದೇ ಹೊಸ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.")
        return

    print(f"ಹೊಸ ವಿಡಿಯೋ ಸಿಕ್ಕಿದೆ: {url}")
    video_path, info = download_video_and_info(url)
    duration = info.get("duration", 120)
    frames = extract_14_frames(video_path, duration)
    script_text = generate_script(info, url)
    send_to_telegram(url, video_path, frames, script_text, info.get("title", "New Video"))

    history.append(vid_id)
    save_history(history)
    print("ಎಲ್ಲವೂ ಯಶಸ್ವಿಯಾಗಿ ಹೊಸ Telegram Bot ಗೆ ರವಾನೆಯಾಗಿದೆ!")

if __name__ == "__main__":
    main()
