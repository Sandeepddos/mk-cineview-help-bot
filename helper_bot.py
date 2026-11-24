import os
import io
import json
import time
import struct
import urllib.parse
import subprocess
import requests
import yt_dlp
from PIL import Image, ImageDraw, ImageFont, ImageStat, ImageFilter
from google import genai
from google.genai import types

BOT_TOKEN = os.environ["HELPER_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

HISTORY_FILE = "helper_history.json"
VOICE_NAME = "Algenib"

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

IGNORE_WORDS = [
    "review", "explained", "ending", "concept", "fan made", "fan-made",
    "spoof", "reaction", "full movie", "roast", "breakdown", "dubbed"
]

REQUIRED_WORDS = [
    "official trailer", "official teaser", "releasing this week",
    "ott release", "ott releases", "box office", "new trailer",
    "ಟ್ರೈಲರ್", "ಟೀಸರ್", "ಬಾಕ್ಸ್ ಆಫೀಸ್", "ರಿಲೀಸ್"
]

def load_state():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {"videos": data, "last_update_id": 0}
    return {"videos": [], "last_update_id": 0}

def save_state(state):
    state["videos"] = state.get("videos", [])[-100:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(state, f, indent=2)

def check_telegram_topic_command(state):
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    last_id = state.get("last_update_id", 0)
    try:
        res = requests.get(f"{base_url}/getUpdates", params={"offset": last_id + 1, "timeout": 5}, timeout=10).json()
        topic_query = None
        for upd in res.get("result", []):
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            if str(msg.get("chat", {}).get("id")) == str(CHAT_ID) and text.lower().startswith("/topic"):
                topic_query = text[6:].strip()
        return topic_query
    except Exception as e:
        print(f"Telegram update ಚೆಕ್ ಎರರ್: {e}", flush=True)
        return None

def search_video(history_list, custom_topic=None):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": 10
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if custom_topic:
            print(f"ನಿರ್ದಿಷ್ಟ ಟಾಪಿಕ್ ಹುಡುಕಲಾಗುತ್ತಿದೆ: {custom_topic}", flush=True)
            encoded_q = urllib.parse.quote(f"{custom_topic} Kannada 2026")
            search_url = f"https://www.youtube.com/results?search_query={encoded_q}"
            info = ydl.extract_info(search_url, download=False)
            for entry in info.get("entries", []):
                vid_id = entry.get("id")
                title = entry.get("title") or custom_topic
                duration = entry.get("duration") or 0
                if vid_id and (duration == 0 or duration <= 900):
                    return f"https://www.youtube.com/watch?v={vid_id}", vid_id, title
            return None, None, None

        print("ಹೊಸ ಕನ್ನಡ ವಿಡಿಯೋ ಹುಡುಕಲಾಗುತ್ತಿದೆ...", flush=True)
        for query in SEARCH_QUERIES:
            encoded_q = urllib.parse.quote(query)
            search_url = f"https://www.youtube.com/results?search_query={encoded_q}&sp=EgIIAg%253D%253D"
            try:
                info = ydl.extract_info(search_url, download=False)
            except Exception as e:
                print(f"ಸರ್ಚ್ ಎರರ್: {e}", flush=True)
                continue

            for entry in info.get("entries", []):
                vid_id = entry.get("id")
                title = entry.get("title") or ""
                title_lower = title.lower()
                duration = entry.get("duration") or 0
                view_count = entry.get("view_count") or 0
                
                if not vid_id or vid_id in history_list:
                    continue
                if not (60 <= duration <= 360):
                    continue
                if any(bad in title_lower for bad in IGNORE_WORDS):
                    continue
                if not any(req in title_lower for req in REQUIRED_WORDS):
                    continue

                is_kannada_query = ("kannada" in query.lower() or "ಕನ್ನಡ" in query)
                if "ott" in title_lower or "week" in title_lower or "ರಿಲೀಸ್" in title_lower:
                    min_views = 1000 if is_kannada_query else 3000
                else:
                    min_views = 5000 if is_kannada_query else 15000

                if view_count > 0 and view_count < min_views:
                    continue

                return f"https://www.youtube.com/watch?v={vid_id}", vid_id, title
    return None, None, None

def get_available_text_models(client):
    models = ["gemini-3.0-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "")
            if (
                "gemini" in name
                and ("flash" in name or "pro" in name)
                and "tts" not in name
                and "image" not in name
                and "2.5-flash" not in name
                and name not in models
            ):
                models.append(name)
    except Exception:
        pass
    return models

def generate_script_and_seo(title, url):
    print("4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ ಸ್ಕ್ರಿಪ್ಟ್ (ಮೂವಿ & ಟ್ರೈಲರ್) ಮತ್ತು SEO ಪ್ಯಾಕೇಜ್ ಸಿದ್ಧವಾಗುತ್ತಿದೆ...", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸೀನಿಯರ್ ಫಿಲ್ಮ್ ಕ್ರಿಟಿಕ್, SEO ಎಕ್ಸ್‌ಪರ್ಟ್ ಮತ್ತು ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್.
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ವಿಷಯವನ್ನು ಆಧರಿಸಿ:
1) ಕಡ್ಡಾಯವಾಗಿ **4 ರಿಂದ 6 ನಿಮಿಷ ಓದುವಷ್ಟು (ಕನಿಷ್ಠ 750 ರಿಂದ 900 ಪದಗಳ)** ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆ. ಈ ಸ್ಕ್ರಿಪ್ಟ್‌ನಲ್ಲಿ **ಮೂವಿ ಟ್ರೈಲರ್ ವಿಶ್ಲೇಷಣೆ ಮತ್ತು ಆ ಸಿನಿಮಾದ ಸಂಪೂರ್ಣ ವಿವರ** ಎರಡೂ ಸಮಾನವಾಗಿ ಇರಬೇಕು.
2) YouTube SEO ಪ್ಯಾಕೇಜ್ (3 ಟೈಟಲ್‌ಗಳು, ಡಿಸ್ಕ್ರಿಪ್ಶನ್, ಟ್ಯಾಗ್‌ಗಳು) ಮತ್ತು ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್‌ನ **TOP_TEXT** (ಮೇಲ್ಭಾಗಕ್ಕೆ 2-3 ಪದಗಳ ಕ್ಯೂರಿಯಾಸಿಟಿ ಟೆಕ್ಸ್ಟ್) ಹಾಗೂ **BOTTOM_TEXT** (ಕೆಳಭಾಗಕ್ಕೆ 2-3 ಪದಗಳ ಪಂಚ್ ಟೆಕ್ಸ್ಟ್) ಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಈ ಕೆಳಗಿನ ನಿಖರ JSON ಫಾರ್ಮ್ಯಾಟ್‌ನಲ್ಲಿ ಮಾತ್ರ ಉತ್ತರ ಕೊಡು:
{{
  "top_text": "ಥಂಬ್‌ನೇಲ್ ಮೇಲ್ಭಾಗಕ್ಕೆ 2-3 ಪದಗಳ ಕನ್ನಡ ಪಂಚ್ ಟೆಕ್ಸ್ಟ್ (ಉದಾ: ಟ್ರೈಲರ್ ಧಮಾಕಾ!)",
  "bottom_text": "ಥಂಬ್‌ನೇಲ್ ಕೆಳಭಾಗಕ್ಕೆ 2-3 ಪದಗಳ ಕನ್ನಡ ಪಂಚ್ ಟೆಕ್ಸ್ಟ್ (ಉದಾ: ಸಿನಿಮಾ ಕಥೆ & ರಿವ್ಯೂ!)",
  "seo_titles": [
    "ಆಕರ್ಷಕ ಕನ್ನಡ + ಇಂಗ್ಲಿಷ್ YouTube Title 1",
    "ಆಕರ್ಷಕ ಕನ್ನಡ + ಇಂಗ್ಲಿಷ್ YouTube Title 2",
    "ಆಕರ್ಷಕ ಕನ್ನಡ + ಇಂಗ್ಲಿಷ್ YouTube Title 3"
  ],
  "seo_description": "YouTube ವಿಡಿಯೋಗಾಗಿ 4-5 ಸಾಲುಗಳ SEO ಡಿಸ್ಕ್ರಿಪ್ಶನ್ ಮತ್ತು ಹ್ಯಾಶ್‌ಟ್ಯಾಗ್‌ಗಳು (#KannadaMovies #MKCineviewKannada ಇತ್ಯಾದಿ)",
  "seo_tags": "ಕಾಮಾ (,) ಹಾಕಿ ಬೇರ್ಪಡಿಸಿದ 15 YouTube SEO ಟ್ಯಾಗ್‌ಗಳು",
  "script": "ಇಲ್ಲಿ 750 ರಿಂದ 900 ಪದಗಳ ಪೂರ್ತಿ 4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆ. ಕನಿಷ್ಠ 8 ರಿಂದ 10 ಚಿಕ್ಕ ಪ್ಯಾರಾಗ್ರಾಫ್‌ಗಳಾಗಿ ವಿಂಗಡಿಸಿ ಬರೆ. ಸ್ಕ್ರಿಪ್ಟ್ ವಿಭಾಗಗಳು: 1) ಮೊದಲ 60 ಪದಗಳು ಸಿನಿಮಾ ಮತ್ತು ಟ್ರೈಲರ್ ಕುರಿತ ಪವರ್‌ಫುಲ್ ಹುಕ್ ಆಗಿರಲಿ, ನಂತರ 'ನಮಸ್ಕಾರ ಸಿನಿಮಾ ಪ್ರಿಯರೇ, MK CINEVIEW ಕನ್ನಡ ಚಾನೆಲ್‌ಗೆ ಸ್ವಾಗತ' ಇರಲಿ. 2) ಸಿನಿಮಾದ ಸಂಪೂರ್ಣ ವಿವರ (ಸುಮಾರು 250 ಪದಗಳು): ಸಿನಿಮಾ ಜಾನರ್, ನಿರ್ದೇಶಕರು, ನಿರ್ಮಾಪಕರು, ಸಂಗೀತ ನಿರ್ದೇಶಕರು, ತಾರಾಗಣ, ಕಥಾಹಂದರ ಮತ್ತು ಶೂಟಿಂಗ್ ವಿಶೇಷತೆ. 3) ಟ್ರೈಲರ್ ಆಳವಾದ ವಿಶ್ಲೇಷಣೆ (ಸುಮಾರು 300 ಪದಗಳು): ಟ್ರೈಲರ್ ಪ್ರಮುಖ ದೃಶ್ಯಗಳು, ಹೀರೋ ಎಂಟ್ರಿ, ಆಕ್ಷನ್/ಡ್ರಾಮಾ, ಡೈಲಾಗ್‌ಗಳು, BGM, ಕ್ಯಾಮೆರಾ ವರ್ಕ್ ಮತ್ತು ಸೀಕ್ರೆಟ್ ಅಂಶಗಳು. 4) ಸಿನಿಮಾ ರಿಲೀಸ್ ಡೇಟ್, OTT/ಥಿಯೇಟರ್ ನಿರೀಕ್ಷೆ ಮತ್ತು ಕ್ಲೋಸಿಂಗ್ (ಸುಮಾರು 150 ಪದಗಳು): ಕೊನೆಯಲ್ಲಿ ಮಾತ್ರ ವೀಕ್ಷಕರ ಅಭಿಪ್ರಾಯ ಕೇಳುವ ಒಂದು ಪ್ರಶ್ನೆ ಮತ್ತು Subscribe Call to Action ಇರಲಿ. 5) ಇಂಗ್ಲಿಷ್ ಸಿನಿಮಾ ಪದಗಳನ್ನು (Trailer, Teaser, Movie, Release, OTT, Box office, BGM, Cinematography, Prime Video, Netflix, Zee5, JioHotstar, Subscribe) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ. 6) ಯಾವುದೇ ಸ್ಟಾರ್ (*, #) ಅಥವಾ ಎಮೋಜಿ ಬಳಸಬೇಡ."
}}
"""
    for model_name in get_available_text_models(client):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            print(f"ಯಶಸ್ವಿಯಾಗಿ ಬಳಸಿದ ಮಾಡೆಲ್: {model_name}", flush=True)
            return json.loads(response.text)
        except Exception as e:
            print(f"{model_name} ಸ್ಕಿಪ್ ಆಗಿದೆ: {e}", flush=True)
            continue
    raise RuntimeError("ಯಾವುದೇ Gemini ಮಾಡೆಲ್ ಲಭ್ಯವಾಗಲಿಲ್ಲ.")

def create_both_thumbnails(vid_id: str, top_text: str, bottom_text: str):
    print("ಒರಿಜಿನಲ್ ಥಂಬ್‌ನೇಲ್ ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ ಅಕ್ಷರಗಳನ್ನು ತೆಗೆಯಲಾಗುತ್ತಿದೆ...", flush=True)
    img_bytes = None
    for quality in ["maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"]:
        r = requests.get(f"https://img.youtube.com/vi/{vid_id}/{quality}", timeout=15)
        if r.status_code == 200 and len(r.content) > 5000:
            img_bytes = r.content
            break

    if not img_bytes:
        return None, None

    clean_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        edit_prompt = (
            "Remove all text, titles, movie logos, watermarks, dates, and typography from this image completely. "
            "Keep the actors, faces, background scene, colors, and lighting 100% identical and natural, "
            "leaving a clean text-free cinematic image."
        )
        res = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                edit_prompt
            ],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"])
        )
        for part in res.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                clean_img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
                print("ಒರಿಜಿನಲ್ ಫೋಟೋದ ಎಲ್ಲಾ ಅಕ್ಷರಗಳನ್ನು ಯಶಸ್ವಿಯಾಗಿ ತೆಗೆಯಲಾಗಿದೆ!", flush=True)
                break
    except Exception as e:
        print(f"AI ಇಮೇಜ್ ಕ್ಲೀನ್ ಎಚ್ಚರಿಕೆ: {e}", flush=True)

    clean_img = clean_img.resize((1280, 720), Image.Resampling.LANCZOS)
    clean_photo_path = "clean_photo.jpg"
    clean_img.save(clean_photo_path, "JPEG", quality=95)

    ready_img = clean_img.copy()
    draw = ImageDraw.Draw(ready_img, "RGBA")
    draw.rectangle([(0, 0), (1280, 115)], fill=(0, 0, 0, 195))
    draw.rectangle([(0, 605), (1280, 720)], fill=(180, 0, 0, 215))

    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansKannada-Bold.ttf"
    ]
    font_path = next((fp for fp in font_paths if os.path.exists(fp)), None)
    font_top = ImageFont.truetype(font_path, 56) if font_path else ImageFont.load_default()
    font_bottom = ImageFont.truetype(font_path, 58) if font_path else ImageFont.load_default()

    def draw_centered_text(text_str, y_pos, font, fill_color):
        bbox = draw.textbbox((0, 0), text_str, font=font)
        text_w = bbox[2] - bbox[0]
        x_pos = max(20, (1280 - text_w) // 2)
        draw.text(
            (x_pos, y_pos),
            text_str,
            font=font,
            fill=fill_color,
            stroke_width=4,
            stroke_fill=(0, 0, 0, 255)
        )

    draw_centered_text(top_text, 22, font_top, (255, 230, 0, 255))
    draw_centered_text(bottom_text, 625, font_bottom, (255, 255, 255, 255))

    final_thumb_path = "readymade_thumbnail.jpg"
    ready_img.save(final_thumb_path, "JPEG", quality=95)
    print("ಖಾಲಿ HD ಫೋಟೋ ಮತ್ತು ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್ ಎರಡೂ ಸಿದ್ಧವಾಗಿವೆ!", flush=True)
    return clean_photo_path, final_thumb_path

def extract_16_hd_frames(youtube_url: str, vid_id: str, movie_title: str, target_count: int = 16) -> list[str]:
    """ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ 16 HD ಫೋಟೋಗಳನ್ನು ತೆಗೆಯುತ್ತದೆ (YouTube ಬ್ಲಾಕ್ ಆದರೆ YouTube HQ ಫ್ರೇಮ್‌ಗಳು + AI ಸಿನಿಮ್ಯಾಟಿಕ್ ದೃಶ್ಯಗಳನ್ನು ಸಿದ್ಧಪಡಿಸುತ್ತದೆ)"""
    print("ಟ್ರೈಲರ್ ವಿಡಿಯೋದಿಂದ 16 HD ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಲು ಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ...", flush=True)
    video_file = "temp_trailer.mp4"
    duration = 0

    # ವಿಧಾನ 1: tv_embedded / mweb / ios ಕ್ಲೈಂಟ್ ಮೂಲಕ MP4 ಡೌನ್‌ಲೋಡ್
    client_orders = [
        ["tv_embedded", "mweb"],
        ["ios", "android"],
        ["web_creator", "mweb"]
    ]
    for clients in client_orders:
        if os.path.exists(video_file):
            os.remove(video_file)
        dl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": video_file,
            "format": "best[height<=720][ext=mp4]/best[ext=mp4]/best",
            "extractor_args": {"youtube": {"player_client": clients}}
        }
        try:
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                duration = info.get("duration") or 120
            if os.path.exists(video_file) and os.path.getsize(video_file) > 100000:
                print(f"ವಿಡಿಯೋ ಯಶಸ್ವಿಯಾಗಿ ಡೌನ್‌ಲೋಡ್ ಆಗಿದೆ (client: {clients})!", flush=True)
                break
        except Exception as e:
            print(f"ಡೌನ್‌ಲೋಡ್ ಪ್ರಯತ್ನ ({clients}) ವಿಫಲ: {e}", flush=True)

    final_frames = []
    if os.path.exists(video_file) and os.path.getsize(video_file) > 100000:
        start_sec = max(3.0, duration * 0.08)
        end_sec = max(start_sec + 10.0, duration * 0.88)
        usable_dur = end_sec - start_sec
        sample_count = 32
        step = usable_dur / sample_count

        scored_frames = []
        for i in range(sample_count):
            ts = start_sec + (i * step)
            raw_path = f"raw_frame_{i:02d}.jpg"
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", video_file,
                        "-frames:v", "1", "-q:v", "1",
                        "-vf", "scale=1280:720:flags=lanczos",
                        raw_path, "-hide_banner", "-loglevel", "error"
                    ],
                    timeout=15,
                    check=True
                )
                if os.path.exists(raw_path):
                    img = Image.open(raw_path).convert("L")
                    brightness = ImageStat.Stat(img).mean[0]
                    if brightness < 25 or brightness > 235:
                        continue
                    sharpness = ImageStat.Stat(img.filter(ImageFilter.FIND_EDGES)).stddev[0]
                    scored_frames.append((sharpness, i, raw_path))
            except Exception:
                continue

        if scored_frames:
            scored_frames.sort(key=lambda x: x[0], reverse=True)
            top_frames = sorted(scored_frames[:target_count], key=lambda x: x[1])
            for idx, (_, _, path) in enumerate(top_frames, start=1):
                clean_name = f"hd_scene_{idx:02d}.jpg"
                os.replace(path, clean_name)
                final_frames.append(clean_name)
            print(f"ವಿಡಿಯೋದಿಂದ {len(final_frames)} HD ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಲಾಗಿದೆ!", flush=True)
            return final_frames

    # ವಿಧಾನ 2 (ಬ್ಯಾಕಪ್): YouTube IP ಬ್ಲಾಕ್ ಆಗಿದ್ದರೆ, YouTube HQ ಫ್ರೇಮ್‌ಗಳು + ಒರಿಜಿನಲ್ ಥಂಬ್‌ನೇಲ್ ಆಧರಿಸಿ Gemini AI ಮೂಲಕ ವಿಭಿನ್ನ ಸಿನಿಮ್ಯಾಟಿಕ್ ದೃಶ್ಯಗಳ 16 HD ಫೋಟೋಗಳನ್ನು ಸಿದ್ಧಪಡಿಸುವುದು
    print("YouTube IP ಬ್ಲಾಕ್ ಇರುವುದರಿಂದ YouTube ಫ್ರೇಮ್‌ಗಳು + AI ಸಿನಿಮ್ಯಾಟಿಕ್ ದೃಶ್ಯಗಳ 16 HD ಫೋಟೋ ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ...", flush=True)
    for yt_thumb in ["hq1.jpg", "hq2.jpg", "hq3.jpg", "sddefault.jpg"]:
        try:
            r = requests.get(f"https://img.youtube.com/vi/{vid_id}/{yt_thumb}", timeout=10)
            if r.status_code == 200 and len(r.content) > 4000:
                img = Image.open(io.BytesIO(r.content)).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
                fname = f"hd_scene_{len(final_frames)+1:02d}.jpg"
                img.save(fname, "JPEG", quality=95)
                final_frames.append(fname)
        except Exception:
            pass

    if os.path.exists("clean_photo.jpg"):
        with open("clean_photo.jpg", "rb") as cf:
            base_bytes = cf.read()
        client = genai.Client(api_key=GEMINI_API_KEY)
        angles = [
            "dramatic wide angle action scene with the same main character in intense cinematic lighting, no text",
            "close-up emotional portrait of the main hero in moody film lighting, 16:9 widescreen, no text",
            "high-octane chase or fight sequence in a cinematic location with the same character, no text",
            "intense confrontation scene at night with dramatic rain and neon/fire reflections, no text",
            "hero walking in slow motion with dramatic smoke and backlight, South Indian cinema style, no text",
            "mysterious suspense scene in an old heritage building or forest with cinematic shadows, no text",
            "powerful mass elevation shot of the protagonist looking intensely at camera, 16:9 HD, no text",
            "dramatic aerial wide shot of the movie setting and action chaos, blockbuster cinematography, no text",
            "hero standing before a roaring crowd or fiery backdrop, epic movie still, no text",
            "tense thriller interrogation or secret meeting scene in dim cinematic lighting, no text",
            "dynamic side-angle vehicle or action stunt frame from the same movie universe, no text",
            "emotional climax still with dramatic golden hour sunlight and lens flare, no text"
        ]
        for prompt_angle in angles:
            if len(final_frames) >= target_count:
                break
            try:
                res = client.models.generate_content(
                    model="gemini-2.5-flash-image",
                    contents=[
                        types.Part.from_bytes(data=base_bytes, mime_type="image/jpeg"),
                        f"Create a new 16:9 movie still frame from '{movie_title}' matching this character and visual tone: {prompt_angle}"
                    ],
                    config=types.GenerateContentConfig(response_modalities=["IMAGE"])
                )
                for part in res.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        gen_img = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
                        fname = f"hd_scene_{len(final_frames)+1:02d}.jpg"
                        gen_img.save(fname, "JPEG", quality=95)
                        final_frames.append(fname)
                        break
                time.sleep(1)
            except Exception as e:
                print(f"AI ಫ್ರೇಮ್ ಜನರೇಷನ್ ಸ್ಕಿಪ್: {e}", flush=True)

    print(f"ಒಟ್ಟು {len(final_frames)} HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳು ಸಿದ್ಧವಾಗಿವೆ!", flush=True)
    return final_frames

def split_script_into_small_chunks(text: str, max_words_per_chunk: int = 135) -> list[str]:
    """ವಾಯ್ಸ್ ಅರ್ಧಕ್ಕೆ ಕಟ್ ಆಗದಂತೆ ಸ್ಕ್ರಿಪ್ಟ್ ಅನ್ನು 120-140 ಪದಗಳ 6-7 ಚಿಕ್ಕ ಭಾಗಗಳಾಗಿ ಕತ್ತರಿಸುತ್ತದೆ"""
    import re
    sentences = re.split(r'(?<=[.!?।])\s+|\n+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_chunk = []
    current_words = 0

    for sent in sentences:
        w_count = len(sent.split())
        if current_words + w_count > max_words_per_chunk and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sent]
            current_words = w_count
        else:
            current_chunk.append(sent)
            current_words += w_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

def parse_audio_mime_type(mime_type: str) -> dict:
    bits_per_sample = 16
    rate = 24000
    for param in mime_type.split(";"):
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}

def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE", b"fmt ",
        16, 1, num_channels, sample_rate,
        byte_rate, block_align, bits_per_sample,
        b"data", data_size
    )
    return header + audio_data

def get_audio_duration(file_path: str) -> float:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, check=True
        )
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def generate_single_chunk_wav(client, text_part: str, part_index: int, total_parts: int) -> str | None:
    model = "gemini-2.5-flash-preview-tts"
    word_count = len(text_part.split())
    # ಪ್ರತಿ ಪದಕ್ಕೆ ಕನಿಷ್ಠ 0.28 ಸೆಕೆಂಡ್ ಆಡಿಯೋ ಇರಲೇಬೇಕು (ಇಲ್ಲದಿದ್ದರೆ ಅರ್ಧಕ್ಕೆ ಕಟ್ ಆಗಿದೆ ಅಂತ ಅರ್ಥ)
    min_expected_sec = max(12.0, word_count * 0.28)

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Read this complete Kannada cinema narration smoothly from start to finish:\n\n{text_part}")],
        ),
    ]
    temps = [0.55, 0.7, 0.85, 0.45]
    best_wav = None
    best_dur = 0.0

    for attempt, temp in enumerate(temps, start=1):
        print(f"ಭಾಗ {part_index+1}/{total_parts} ({word_count} ಪದಗಳು) - ಪ್ರಯತ್ನ {attempt}/4 (temp={temp})...", flush=True)
        config = types.GenerateContentConfig(
            temperature=temp,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
                )
            ),
        )
        try:
            audio_data = bytearray()
            mime_type = ""
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if chunk.parts is None:
                    continue
                if chunk.parts[0].inline_data and chunk.parts[0].inline_data.data:
                    inline_data = chunk.parts[0].inline_data
                    audio_data.extend(inline_data.data)
                    mime_type = inline_data.mime_type

            if audio_data:
                wav_bytes = convert_to_wav(bytes(audio_data), mime_type or "audio/L16;rate=24000")
                wav_path = f"part_{part_index}_try_{attempt}.wav"
                with open(wav_path, "wb") as f:
                    f.write(wav_bytes)
                dur = get_audio_duration(wav_path)
                print(f"ಭಾಗ {part_index+1} (ಪ್ರಯತ್ನ {attempt}) ಉದ್ದ: {dur:.1f}s (ಅಪೇಕ್ಷಿತ: >{min_expected_sec:.1f}s)", flush=True)

                if dur > best_dur:
                    best_dur = dur
                    best_wav = wav_path

                if dur >= min_expected_sec:
                    return wav_path
                else:
                    print(f"ಭಾಗ {part_index+1} ಕಟ್ ಆಗಿದೆ, ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ...", flush=True)
                    time.sleep(2.5)
        except Exception as e:
            print(f"ಭಾಗ {part_index+1} ಪ್ರಯತ್ನ {attempt} ಎರರ್: {e}", flush=True)
            time.sleep(3)

    return best_wav

def generate_algenib_voice(script_text: str):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    parts = split_script_into_small_chunks(script_text, max_words_per_chunk=135)
    print(f"ವಾಯ್ಸ್ ಕಟ್ ಆಗದಂತೆ ಸ್ಕ್ರಿಪ್ಟ್ ಅನ್ನು {len(parts)} ಚಿಕ್ಕ ಭಾಗಗಳಲ್ಲಿ ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ...", flush=True)

    final_wavs = []
    for idx, part_text in enumerate(parts):
        wav_file = generate_single_chunk_wav(client, part_text, idx, len(parts))
        if wav_file and os.path.exists(wav_file):
            final_wavs.append(wav_file)
        time.sleep(2)

    if final_wavs:
        with open("concat_list.txt", "w") as lf:
            for wf in final_wavs:
                lf.write(f"file '{wf}'\n")
        mp3_path = "voiceover.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat_list.txt", "-b:a", "128k", mp3_path, "-hide_banner", "-loglevel", "error"],
            check=True
        )
        total_dur = get_audio_duration(mp3_path)
        print(f"ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ MP3 ಸಿದ್ಧವಾಗಿದೆ! ಒಟ್ಟು ಉದ್ದ: {total_dur/60:.2f} ನಿಮಿಷಗಳು ({total_dur:.1f} ಸೆಕೆಂಡ್)", flush=True)
        return mp3_path
    return None

def main():
    state = load_state()
    history = state.get("videos", [])
    custom_topic = check_telegram_topic_command(state)
    
    url, vid_id, search_title = search_video(history, custom_topic=custom_topic)
    if not url:
        print("ಹೊಸ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.", flush=True)
        save_state(state)
        return

    print(f"ವಿಡಿಯೋ ಸಿಕ್ಕಿದೆ: {url}", flush=True)
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # 1. ಸ್ಕ್ರಿಪ್ಟ್, SEO ಪ್ಯಾಕೇಜ್ ಮತ್ತು ಥಂಬ್‌ನೇಲ್ ಟೆಕ್ಸ್ಟ್ ಜನರೇಟ್ ಮಾಡುವುದು
    content_data = generate_script_and_seo(search_title, url)
    top_txt = content_data.get("top_text", "ಟ್ರೈಲರ್ ಧಮಾಕಾ!")
    bottom_txt = content_data.get("bottom_text", "ಸಿನಿಮಾ ಕಥೆ & ರಿವ್ಯೂ!")
    script_text = content_data.get("script", "")

    # 2. ಖಾಲಿ HD ಫೋಟೋ + ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್ ಎರಡನ್ನೂ ಕಳುಹಿಸುವುದು
    clean_path, thumb_path = create_both_thumbnails(vid_id, top_txt, bottom_txt)

    if clean_path and os.path.exists(clean_path):
        clean_caption = (
            f"🎬 <b>{search_title}</b>\n"
            f"🔗 <b>YouTube Link:</b> {url}\n\n"
            f"🖼️ <b>1) ಅಕ್ಷರಗಳಿಲ್ಲದ ಖಾಲಿ HD ಫೋಟೋ (Clean Photo)</b>"
        )
        with open(clean_path, "rb") as cf:
            requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": clean_caption, "parse_mode": "HTML"},
                files={"photo": cf}
            )
        time.sleep(1.5)

    ready_caption = (
        f"✅ <b>2) ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್ (Ready Thumbnail)</b>\n"
        f"🔺 <b>Top:</b> {top_txt}\n"
        f"🔻 <b>Bottom:</b> {bottom_txt}"
    )
    if thumb_path and os.path.exists(thumb_path):
        with open(thumb_path, "rb") as tf:
            requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": ready_caption, "parse_mode": "HTML"},
                files={"photo": tf}
            )
    else:
        requests.post(f"{base_url}/sendMessage", data={"chat_id": CHAT_ID, "text": ready_caption, "parse_mode": "HTML"})

    time.sleep(2)

    # 3. 16 HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳನ್ನು ಕಳುಹಿಸುವುದು
    hd_frames = extract_16_hd_frames(url, vid_id, search_title, target_count=16)
    if hd_frames:
        for batch_idx in range(0, len(hd_frames), 8):
            batch = hd_frames[batch_idx:batch_idx + 8]
            media_group = []
            files_dict = {}
            for idx, fpath in enumerate(batch):
                attach_key = f"photo_{idx}"
                item = {"type": "photo", "media": f"attach://{attach_key}"}
                if idx == 0:
                    item["caption"] = f"📸 <b>ಎಡಿಟಿಂಗ್‌ಗಾಗಿ HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳು (ಭಾಗ {batch_idx//8 + 1})</b>"
                    item["parse_mode"] = "HTML"
                media_group.append(item)
                files_dict[attach_key] = open(fpath, "rb")

            requests.post(
                f"{base_url}/sendMediaGroup",
                data={"chat_id": CHAT_ID, "media": json.dumps(media_group)},
                files=files_dict
            )
            for fobj in files_dict.values():
                fobj.close()
            time.sleep(2)

    # 4. YouTube SEO ಪ್ಯಾಕೇಜ್ ಕಳುಹಿಸುವುದು
    titles_formatted = "\n".join([f"{i+1}. {t}" for i, t in enumerate(content_data.get("seo_titles", []))])
    seo_msg = (
        f"🚀 <b>YouTube SEO ಪ್ಯಾಕೇಜ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
        f"📌 <b>Titles:</b>\n{titles_formatted}\n\n"
        f"📝 <b>Description:</b>\n{content_data.get('seo_description', '')}\n\n"
        f"🏷️ <b>Tags:</b>\n<code>{content_data.get('seo_tags', '')}</code>"
    )
    requests.post(f"{base_url}/sendMessage", data={"chat_id": CHAT_ID, "text": seo_msg, "parse_mode": "HTML"})

    time.sleep(2)

    # 5. 4-6 ನಿಮಿಷದ ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸುವುದು
    header = "🎙️ <b>4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ AI ಸ್ಕ್ರಿಪ್ಟ್ (ಸಿನಿಮಾ & ಟ್ರೈಲರ್):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

    # 6. ಕಟ್ ಆಗದ Algenib ವಾಯ್ಸ್ MP3 ಕಳುಹಿಸುವುದು
    mp3_path = generate_algenib_voice(script_text)
    if mp3_path and os.path.exists(mp3_path):
        with open(mp3_path, "rb") as af:
            requests.post(
                f"{base_url}/sendAudio",
                data={
                    "chat_id": CHAT_ID,
                    "title": f"{search_title[:40]} - Algenib Voice",
                    "performer": "MK CINEVIEW ಕನ್ನಡ"
                },
                files={"audio": af}
            )
        print("Algenib ವಾಯ್ಸ್ MP3 ಫೈಲ್ Telegram ಗೆ ಕಳುಹಿಸಲಾಗಿದೆ!", flush=True)

    if vid_id not in history:
        history.append(vid_id)
    state["videos"] = history
    save_state(state)
    print("ಯಶಸ್ವಿಯಾಗಿ ಎಲ್ಲಾ ಕೆಲಸ ಪೂರ್ಣಗೊಂಡಿದೆ!", flush=True)

if __name__ == "__main__":
    main()
