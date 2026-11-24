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
  "script": "ಇಲ್ಲಿ 750 ರಿಂದ 900 ಪದಗಳ ಪೂರ್ತಿ 4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆ. ಸ್ಕ್ರಿಪ್ಟ್ ವಿಭಾಗಗಳು ಈ ರೀತಿ ಇರಲಿ: 1) ಮೊದಲ 60 ಪದಗಳು ಸಿನಿಮಾ ಮತ್ತು ಟ್ರೈಲರ್ ಕುರಿತ ಪವರ್‌ಫುಲ್ ಹುಕ್ ಆಗಿರಲಿ, ನಂತರ 'ನಮಸ್ಕಾರ ಸಿನಿಮಾ ಪ್ರಿಯರೇ, MK CINEVIEW ಕನ್ನಡ ಚಾನೆಲ್‌ಗೆ ಸ್ವಾಗತ' ಇರಲಿ. 2) ಸಿನಿಮಾದ ಸಂಪೂರ್ಣ ವಿವರ (ಸುಮಾರು 250 ಪದಗಳು): ಸಿನಿಮಾ ಯಾವ ಜಾನರ್ (Genre), ನಿರ್ದೇಶಕರು ಮತ್ತು ನಿರ್ಮಾಣ ಸಂಸ್ಥೆ ಯಾರು, ಸಂಗೀತ ನಿರ್ದೇಶಕರು, ಪೂರ್ತಿ ತಾರಾಗಣ (Cast), ಸಿನಿಮಾದ ಕಥಾಹಂದರ ಮತ್ತು ಶೂಟಿಂಗ್ ವಿಶೇಷತೆಗಳನ್ನು ವಿವರಿಸು. 3) ಟ್ರೈಲರ್ ಆಳವಾದ ವಿಶ್ಲೇಷಣೆ (ಸುಮಾರು 300 ಪದಗಳು): ಟ್ರೈಲರ್ ಆರಂಭದಿಂದ ಅಂತ್ಯದವರೆಗಿನ ಪ್ರಮುಖ ದೃಶ್ಯಗಳು, ಹೀರೋ ಎಂಟ್ರಿ, ಆಕ್ಷನ್/ಡ್ರಾಮಾ, ಡೈಲಾಗ್‌ಗಳು, BGM, ಕ್ಯಾಮೆರಾ ವರ್ಕ್ (Cinematography) ಮತ್ತು ಟ್ರೈಲರ್‌ನಲ್ಲಿ ಅಡಗಿರುವ ಸೀಕ್ರೆಟ್ ಅಂಶಗಳನ್ನು ವಿಶ್ಲೇಷಿಸು. 4) ಸಿನಿಮಾ ರಿಲೀಸ್ ಡೇಟ್, OTT/ಥಿಯೇಟರ್ ನಿರೀಕ್ಷೆ ಮತ್ತು ಕ್ಲೋಸಿಂಗ್ (ಸುಮಾರು 150 ಪದಗಳು): ಸಿನಿಮಾ ಯಾವಾಗ ರಿಲೀಸ್ ಆಗುತ್ತಿದೆ, ಪ್ರೇಕ್ಷಕರಲ್ಲಿರುವ ಕ್ರೇಜ್ ಹೇಗಿದೆ ಎಂಬುದನ್ನು ಹೇಳಿ, ಕೊನೆಯಲ್ಲಿ ಮಾತ್ರ ವೀಕ್ಷಕರ ಅಭಿಪ್ರಾಯ ಕೇಳುವ ಒಂದು ಪ್ರಶ್ನೆ ಮತ್ತು Subscribe Call to Action ಇರಲಿ. 5) ಇಂಗ್ಲಿಷ್ ಸಿನಿಮಾ ಪದಗಳನ್ನು (Trailer, Teaser, Movie, Release, OTT, Box office, BGM, Cinematography, Prime Video, Netflix, Zee5, JioHotstar, Subscribe) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ. 6) ಯಾವುದೇ ಸ್ಟಾರ್ (*, #) ಅಥವಾ ಎಮೋಜಿ ಬಳಸಬೇಡ."
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

def extract_4_hd_frames(youtube_url: str, vid_id: str) -> list[str]:
    """ಯಾವುದೇ Gemini API ಕೋಟಾ ಖರ್ಚು ಮಾಡದೆ 4 ಅತ್ಯುತ್ತಮ HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳನ್ನು ಸಿದ್ಧಪಡಿಸುತ್ತದೆ"""
    print("ವಿಡಿಯೋದಿಂದ 4 ಅತ್ಯುತ್ತಮ HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳನ್ನು ತೆಗೆಯಲಾಗುತ್ತಿದೆ...", flush=True)
    video_file = "temp_trailer.mp4"
    duration = 0

    for clients in [["tv_embedded", "mweb"], ["ios", "android"]]:
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
                break
        except Exception:
            continue

    final_frames = []
    if os.path.exists(video_file) and os.path.getsize(video_file) > 100000:
        start_sec = max(4.0, duration * 0.12)
        end_sec = max(start_sec + 8.0, duration * 0.85)
        usable_dur = end_sec - start_sec
        sample_count = 12
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
            top_4 = sorted(scored_frames[:4], key=lambda x: x[1])
            for idx, (_, _, path) in enumerate(top_4, start=1):
                clean_name = f"hd_scene_{idx:02d}.jpg"
                os.replace(path, clean_name)
                final_frames.append(clean_name)
            print(f"ವಿಡಿಯೋದಿಂದ {len(final_frames)} HD ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಲಾಗಿದೆ!", flush=True)
            return final_frames

    # YouTube ಡೌನ್‌ಲೋಡ್ ಬ್ಲಾಕ್ ಆಗಿದ್ದರೆ YouTube ನ 4 ಒರಿಜಿನಲ್ ಫ್ರೇಮ್‌ಗಳನ್ನು ನೀಡುವುದು (API ಕೋಟಾ ಉಳಿಯುತ್ತದೆ)
    for yt_thumb in ["maxresdefault.jpg", "hq1.jpg", "hq2.jpg", "hq3.jpg"]:
        if len(final_frames) >= 4:
            break
        try:
            r = requests.get(f"https://img.youtube.com/vi/{vid_id}/{yt_thumb}", timeout=10)
            if r.status_code == 200 and len(r.content) > 4000:
                img = Image.open(io.BytesIO(r.content)).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
                fname = f"hd_scene_{len(final_frames)+1:02d}.jpg"
                img.save(fname, "JPEG", quality=95)
                final_frames.append(fname)
        except Exception:
            pass

    print(f"ಒಟ್ಟು {len(final_frames)} HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳು ಸಿದ್ಧವಾಗಿವೆ!", flush=True)
    return final_frames

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

def generate_algenib_voice(script_text: str):
    """ಆಡಿಯೋ ಕತ್ತರಿಸದೆ ಒಂದೇ ಬಾರಿಗೆ temperature=0.45 ನಲ್ಲಿ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ ಜನರೇಟ್ ಮಾಡುತ್ತದೆ"""
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    model = "gemini-2.5-flash-preview-tts"
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"## Transcript:\n{script_text}")],
        ),
    ]

    # ಎಲ್ಲಾ ಪ್ರಯತ್ನಗಳಲ್ಲೂ ಕಡ್ಡಾಯವಾಗಿ temperature=0.45 ಮಾತ್ರ ಬಳಸುತ್ತದೆ (ಗರಿಷ್ಠ 2 ಪ್ರಯತ್ನ — ಫ್ರೀ API ಕೋಟಾ ಉಳಿಯುತ್ತದೆ)
    temps = [0.45, 0.45]
    best_mp3 = None
    best_dur = 0.0

    for attempt, temp in enumerate(temps, start=1):
        print(f"ಒಂದೇ ಬಾರಿಗೆ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ ಜನರೇಟ್ ಆಗುತ್ತಿದೆ (ಪ್ರಯತ್ನ {attempt}/2, temperature={temp})...", flush=True)
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
                wav_path = f"voiceover_{attempt}.wav"
                mp3_path = f"voiceover_{attempt}.mp3"
                with open(wav_path, "wb") as f:
                    f.write(wav_bytes)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", wav_path, "-b:a", "128k", mp3_path, "-hide_banner", "-loglevel", "error"],
                    check=True
                )
                dur = get_audio_duration(mp3_path)
                print(f"ಪ್ರಯತ್ನ {attempt} ಆಡಿಯೋ ಉದ್ದ: {dur/60:.2f} ನಿಮಿಷಗಳು ({dur:.1f} ಸೆಕೆಂಡ್)", flush=True)

                if dur > best_dur:
                    best_dur = dur
                    best_mp3 = mp3_path

                # 120 ಸೆಕೆಂಡ್‌ಗಿಂತ (2 ನಿಮಿಷ) ಹೆಚ್ಚಿದ್ದರೆ ಪೂರ್ತಿ ಆಡಿಯೋ ಬಂದಿದೆ ಅಂತ ಅರ್ಥ
                if dur >= 120.0:
                    print("ಪೂರ್ತಿ Algenib ಆಡಿಯೋ ಒಂದೇ ಬಾರಿಗೆ ಸಿದ್ಧವಾಗಿದೆ!", flush=True)
                    return mp3_path
                elif attempt < len(temps):
                    print("ಆಡಿಯೋ ಚಿಕ್ಕದಾಗಿ ಬಂದಿದೆ, 5 ಸೆಕೆಂಡ್ ಕಾದು ಒಮ್ಮೆ ರಿಟ್ರೈ ಮಾಡಲಾಗುತ್ತಿದೆ...", flush=True)
                    time.sleep(5)
        except Exception as e:
            print(f"Algenib TTS ಪ್ರಯತ್ನ {attempt} ಎರರ್: {e}", flush=True)
            time.sleep(5)

    return best_mp3

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

    time.sleep(3)

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

    # 3. 4 ಅತ್ಯುತ್ತಮ HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳನ್ನು ಕಳುಹಿಸುವುದು
    hd_frames = extract_4_hd_frames(url, vid_id)
    if hd_frames:
        media_group = []
        files_dict = {}
        for idx, fpath in enumerate(hd_frames):
            attach_key = f"photo_{idx}"
            item = {"type": "photo", "media": f"attach://{attach_key}"}
            if idx == 0:
                item["caption"] = "📸 <b>ಎಡಿಟಿಂಗ್‌ಗಾಗಿ 4 HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳು</b>"
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

    # 6. ಒಂದೇ ಬಾರಿಗೆ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ MP3 ಕಳುಹಿಸುವುದು
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
