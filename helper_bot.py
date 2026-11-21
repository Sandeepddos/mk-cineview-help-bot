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

def load_data():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {"videos": data, "last_update_id": 0}
            return data
    return {"videos": [], "last_update_id": 0}

def save_data(data):
    data["videos"] = data["videos"][-100:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def extract_14_frames(video_path, duration):
    os.makedirs("temp_media/frames", exist_ok=True)
    start_sec = 8 if duration > 30 else 2
    usable_duration = max(duration - 16, 10)
    fps_rate = 14 / usable_duration

    vf_filter = (
        f"fps={fps_rate},"
        "crop=iw*0.86:ih*0.86:(iw-iw*0.86)/2:(ih-ih*0.86)/2,"
        "scale=1920:-1:flags=lanczos,"
        "unsharp=5:5:0.8:5:5:0.0"
    )

    cmd = [
        "ffmpeg", "-ss", str(start_sec), "-t", str(usable_duration),
        "-i", video_path, "-vf", vf_filter,
        "-vframes", "14", "-q:v", "1", "temp_media/frames/frame_%02d.jpg",
        "-hide_banner", "-loglevel", "error"
    ]
    subprocess.run(cmd, check=True)
    return sorted(glob.glob("temp_media/frames/frame_*.jpg"))

def send_frames_album(frames):
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
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

def check_cut_command_video(data):
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    offset = data.get("last_update_id", 0) + 1
    res = requests.get(f"{base_url}/getUpdates", params={"offset": offset}).json()
    
    cut_video_obj = None
    for update in res.get("result", []):
        data["last_update_id"] = max(data.get("last_update_id", 0), update["update_id"])
        msg = update.get("message", {})
        if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
            continue
        
        video_obj = msg.get("video") or msg.get("document")
        caption = (msg.get("caption") or "").lower()
        
        # ವಿಡಿಯೋ ಜೊತೆಗೆ /cut ಅಥವಾ cut ಅಥವಾ 'ವಿಡಿಯೋ' ಕಮಾಂಡ್ ಇದ್ದರೆ ಮಾತ್ರ ಹಿಡಿಯುತ್ತದೆ
        if video_obj and any(cmd in caption for cmd in ["/cut", "cut", "ವಿಡಿಯೋ", "video"]):
            cut_video_obj = video_obj

    if not cut_video_obj:
        return False

    file_size_mb = cut_video_obj.get("file_size", 0) / (1024 * 1024)
    if file_size_mb >= 49:
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": f"⚠️ ವಿಡಿಯೋ {file_size_mb:.1f} MB ಇದೆ (50MB ಗಿಂತ ಹೆಚ್ಚಿದೆ). ದಯವಿಟ್ಟು 480p ಅಥವಾ 720p (50MB ಒಳಗಿನ) ವಿಡಿಯೋಗೆ /cut ಹಾಕಿ ಕಳುಹಿಸು."}
        )
        return True

    file_id = cut_video_obj["file_id"]
    duration = cut_video_obj.get("duration", 120)
    file_info = requests.get(f"{base_url}/getFile", params={"file_id": file_id}).json()
    file_path = file_info.get("result", {}).get("file_path")

    if file_path:
        os.makedirs("temp_media", exist_ok=True)
        local_video = "temp_media/tg_upload.mp4"
        dl_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        with open(local_video, "wb") as f:
            f.write(requests.get(dl_url).content)
        
        frames = extract_14_frames(local_video, duration)
        if frames:
            requests.post(
                f"{base_url}/sendMessage",
                data={"chat_id": CHAT_ID, "text": "✂️ '/cut' ಕಮಾಂಡ್ ಸ್ವೀಕರಿಸಲಾಗಿದೆ! ಲೋಗೋ ತೆಗೆದು ಕಟ್ ಮಾಡಿದ 14 HD ಫೋಟೋಗಳು ಇಲ್ಲಿವೆ:"}
            )
            send_frames_album(frames)
            return True
    return False

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
            return response.text
        except Exception:
            continue
    raise RuntimeError("ಯಾವುದೇ Gemini ಮಾಡೆಲ್ ಲಭ್ಯವಾಗಲಿಲ್ಲ.")

def main():
    data = load_data()
    
    # 1. ನೀನು ವಿಡಿಯೋ ಜೊತೆ /cut ಅಥವಾ 'ವಿಡಿಯೋ' ಕಮಾಂಡ್ ಕಳುಹಿಸಿದ್ದರೆ ಕೇವಲ 14 ಫೋಟೋ ಮಾತ್ರ ಕಟ್ ಮಾಡುತ್ತದೆ
    if check_cut_command_video(data):
        save_data(data)
        print("ಕಮಾಂಡ್ ವಿಡಿಯೋದಿಂದ 14 HD ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಿ ಕಳುಹಿಸಲಾಗಿದೆ!")
        return

    # 2. ಇಲ್ಲದಿದ್ದರೆ ಹೊಸ YouTube ಲಿಂಕ್ ಮತ್ತು ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸುತ್ತದೆ
    url, vid_id, search_title = search_latest_video(data["videos"])
    if not url:
        save_data(data)
        return

    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    caption = f"🎬 <b>{search_title}</b>\n\n🔗 <b>YouTube Link:</b> {url}\n\n💡 <i>ಈ ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ ಕ್ಯಾಪ್ಶನ್‌ನಲ್ಲಿ <b>/cut</b> ಅಂತ ಹಾಕಿ ಕಳುಹಿಸಿದರೆ 14 HD ಫೋಟೋ ಕಟ್ ಮಾಡಿ ಕೊಡುತ್ತೇನೆ!</i>"
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
    script_text = generate_script(search_title, "Kannada Cinema", search_title, url)
    
    header = "📝 <b>3-4 ನಿಮಿಷದ AI ಸ್ಕ್ರಿಪ್ಟ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

    data["videos"].append(vid_id)
    save_data(data)

if __name__ == "__main__":
    main()
