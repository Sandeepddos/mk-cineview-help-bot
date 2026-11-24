import os
import re
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

IMDB_SEARCH_URLS = [
    # 1. ಕನ್ನಡದ ಹೊಸ 2026 ಸಿನಿಮಾಗಳು (ಮೊದಲ ಆದ್ಯತೆ)
    "https://www.imdb.com/search/title/?title_type=feature&release_date=2026-01-01,2026-12-31&primary_language=kn&sort=popularity,asc",
    # 2. ಇತ್ತೀಚಿನ ಟ್ರೆಂಡಿಂಗ್ ಭಾರತೀಯ ಸಿನಿಮಾಗಳು (Pan-India)
    "https://www.imdb.com/search/title/?title_type=feature&release_date=2026-01-01,2026-12-31&country_of_origin=IN&sort=moviemeter,asc"
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

def check_telegram_command(state):
    """ಟೆಲಿಗ್ರಾಂನಲ್ಲಿ IMDb ಲಿಂಕ್ ಅಥವಾ /topic ಬಂದಿದೆಯಾ ಅಂತ ಚೆಕ್ ಮಾಡುತ್ತದೆ"""
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    last_id = state.get("last_update_id", 0)
    custom_imdb_id = None
    custom_topic = None
    try:
        res = requests.get(f"{base_url}/getUpdates", params={"offset": last_id + 1, "timeout": 5}, timeout=10).json()
        for upd in res.get("result", []):
            state["last_update_id"] = upd["update_id"]
            msg = upd.get("message", {})
            text = (msg.get("text") or "").strip()
            if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                continue
            imdb_match = re.search(r"(tt\d{7,10})", text)
            if imdb_match:
                custom_imdb_id = imdb_match.group(1)
            elif text.lower().startswith("/topic"):
                custom_topic = text[6:].strip()
    except Exception as e:
        print(f"Telegram update ಚೆಕ್ ಎರರ್: {e}", flush=True)
    return custom_imdb_id, custom_topic

def get_imdb_movie_details(imdb_id: str):
    """IMDb ಪುಟದಿಂದ ಸಿನಿಮಾದ ಹೆಸರು, ವಿವರ, ಪೋಸ್ಟರ್ ಮತ್ತು ಟ್ರೈಲರ್ ವಿಡಿಯೋ ಲಿಂಕ್ ತೆಗೆಯುತ್ತದೆ"""
    url = f"https://www.imdb.com/title/{imdb_id}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        html = r.text

        # JSON-LD ಮೆಟಾಡೇಟಾ ಓದುವುದು
        ld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        ld_data = json.loads(ld_match.group(1)) if ld_match else {}

        title = ld_data.get("name") or imdb_id
        description = ld_data.get("description") or ""
        poster_url = ld_data.get("image") or ""
        genres = ", ".join(ld_data.get("genre", [])) if isinstance(ld_data.get("genre"), list) else str(ld_data.get("genre", ""))
        actors = ", ".join([a.get("name", "") for a in ld_data.get("actor", [])[:6]])
        directors = ", ".join([d.get("name", "") for d in ld_data.get("director", [])[:3]])

        trailer_obj = ld_data.get("trailer") or {}
        trailer_embed = trailer_obj.get("embedUrl") or trailer_obj.get("url") or ""
        if trailer_embed and trailer_embed.startswith("/"):
            trailer_embed = f"https://www.imdb.com{trailer_embed}"

        # HTML ನಲ್ಲಿರುವ /video/vi... ಲಿಂಕ್ ಹುಡುಕುವುದು
        if not trailer_embed:
            vi_match = re.search(r'(/video/vi\d+)', html)
            if vi_match:
                trailer_embed = f"https://www.imdb.com{vi_match.group(1)}/"

        details_summary = (
            f"Movie Title: {title}\n"
            f"Genre: {genres}\n"
            f"Director: {directors}\n"
            f"Cast: {actors}\n"
            f"Storyline: {description}"
        )

        return {
            "imdb_id": imdb_id,
            "url": url,
            "title": title,
            "details": details_summary,
            "poster_url": poster_url,
            "trailer_url": trailer_embed
        }
    except Exception as e:
        print(f"IMDb ವಿವರ ಪಡೆಯುವಲ್ಲಿ ಎರರ್ ({imdb_id}): {e}", flush=True)
        return None

def auto_find_imdb_movie(history_list, custom_imdb_id=None, custom_topic=None):
    """IMDb ನಿಂದ ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಟ್ರೈಲರ್ ಇರುವ ಹೊಸ ಕನ್ನಡ/ಭಾರತೀಯ ಸಿನಿಮಾ ಹುಡುಕುತ್ತದೆ"""
    if custom_imdb_id:
        print(f"ನಿರ್ದಿಷ್ಟ IMDb ಸಿನಿಮಾ ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ: {custom_imdb_id}", flush=True)
        return get_imdb_movie_details(custom_imdb_id)

    if custom_topic:
        print(f"IMDb ನಲ್ಲಿ ಟಾಪಿಕ್ ಹುಡುಕಲಾಗುತ್ತಿದೆ: {custom_topic}", flush=True)
        q = urllib.parse.quote(custom_topic)
        r = requests.get(f"https://www.imdb.com/find/?q={q}&s=tt&ttype=ft", headers=HEADERS, timeout=15)
        ids = list(dict.fromkeys(re.findall(r"/title/(tt\d{7,10})/", r.text)))
        for tid in ids[:5]:
            info = get_imdb_movie_details(tid)
            if info:
                return info

    print("IMDb ನಿಂದ ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಹೊಸ ಕನ್ನಡ ಸಿನಿಮಾ & ಟ್ರೈಲರ್ ಹುಡುಕಲಾಗುತ್ತಿದೆ...", flush=True)
    for search_url in IMDB_SEARCH_URLS:
        try:
            r = requests.get(search_url, headers=HEADERS, timeout=20)
            ids = list(dict.fromkeys(re.findall(r"/title/(tt\d{7,10})/", r.text)))
            for tid in ids[:15]:
                if tid in history_list:
                    continue
                info = get_imdb_movie_details(tid)
                if info and info.get("trailer_url"):
                    print(f"ಟ್ರೈಲರ್ ಇರುವ ಸಿನಿಮಾ ಸಿಕ್ಕಿದೆ: {info['title']} ({tid})", flush=True)
                    return info
        except Exception as e:
            print(f"IMDb ಸರ್ಚ್ ಎರರ್: {e}", flush=True)
            continue
    return None

def get_available_text_models(client):
    models = ["gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-2.5-flash"]
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "")
            if (
                "gemini" in name
                and ("flash" in name or "pro" in name)
                and "tts" not in name
                and "image" not in name
                and name not in models
            ):
                models.append(name)
    except Exception:
        pass
    return models

def generate_script_and_seo(movie_info):
    print("Gemini ಮೂಲಕ 4-6 ನಿಮಿಷದ ಸ್ಕ್ರಿಪ್ಟ್ ಮತ್ತು SEO ಪ್ಯಾಕೇಜ್ ಸಿದ್ಧವಾಗುತ್ತಿದೆ...", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸೀನಿಯರ್ ಫಿಲ್ಮ್ ಕ್ರಿಟಿಕ್, SEO ಎಕ್ಸ್‌ಪರ್ಟ್ ಮತ್ತು ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್.
ಈ ಕೆಳಗಿನ IMDb ಅಧಿಕೃತ ಸಿನಿಮಾ ವಿವರವನ್ನು ಆಧರಿಸಿ:
1) ಕಡ್ಡಾಯವಾಗಿ **4 ರಿಂದ 6 ನಿಮಿಷ ಓದುವಷ್ಟು (ಕನಿಷ್ಠ 750 ರಿಂದ 900 ಪದಗಳ)** ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆ. ಈ ಸ್ಕ್ರಿಪ್ಟ್‌ನಲ್ಲಿ **ಸಿನಿಮಾದ ಸಂಪೂರ್ಣ ವಿವರ (Cast, Director, Story) ಮತ್ತು ಟ್ರೈಲರ್ ವಿಶ್ಲೇಷಣೆ** ಎರಡೂ ಸಮಾನವಾಗಿ ಇರಬೇಕು.
2) YouTube SEO ಪ್ಯಾಕೇಜ್ (3 ಟೈಟಲ್‌ಗಳು, ಡಿಸ್ಕ್ರಿಪ್ಶನ್, ಟ್ಯಾಗ್‌ಗಳು), ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್‌ನ **TOP_TEXT** ಹಾಗೂ **BOTTOM_TEXT**, ಮತ್ತು Free Image AI (Flux) ಗಾಗಿ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಸಿನಿಮ್ಯಾಟಿಕ್ **thumbnail_image_prompt** ಕೊಡು.

IMDb ಸಿನಿಮಾ ವಿವರ:
{movie_info['details']}
IMDb URL: {movie_info['url']}

ಈ ಕೆಳಗಿನ ನಿಖರ JSON ಫಾರ್ಮ್ಯಾಟ್‌ನಲ್ಲಿ ಮಾತ್ರ ಉತ್ತರ ಕೊಡು:
{{
  "top_text": "ಥಂಬ್‌ನೇಲ್ ಮೇಲ್ಭಾಗಕ್ಕೆ 2-3 ಪದಗಳ ಕನ್ನಡ ಪಂಚ್ ಟೆಕ್ಸ್ಟ್ (ಉದಾ: ಟ್ರೈಲರ್ ಧಮಾಕಾ!)",
  "bottom_text": "ಥಂಬ್‌ನೇಲ್ ಕೆಳಭಾಗಕ್ಕೆ 2-3 ಪದಗಳ ಕನ್ನಡ ಪಂಚ್ ಟೆಕ್ಸ್ಟ್ (ಉದಾ: ಸಿನಿಮಾ ಕಥೆ & ರಿವ್ಯೂ!)",
  "thumbnail_image_prompt": "A dramatic high-budget South Indian Kannada cinema poster scene matching this movie theme, intense action lighting, rich cinematic colors, 8k resolution, photorealistic, strictly no text, no letters, no watermark",
  "seo_titles": [
    "ಆಕರ್ಷಕ ಕನ್ನಡ + ಇಂಗ್ಲಿಷ್ YouTube Title 1",
    "ಆಕರ್ಷಕ ಕನ್ನಡ + ಇಂಗ್ಲಿಷ್ YouTube Title 2",
    "ಆಕರ್ಷಕ ಕನ್ನಡ + ಇಂಗ್ಲಿಷ್ YouTube Title 3"
  ],
  "seo_description": "YouTube ವಿಡಿಯೋಗಾಗಿ 4-5 ಸಾಲುಗಳ SEO ಡಿಸ್ಕ್ರಿಪ್ಶನ್ ಮತ್ತು ಹ್ಯಾಶ್‌ಟ್ಯಾಗ್‌ಗಳು (#KannadaMovies #MKCineviewKannada ಇತ್ಯಾದಿ)",
  "seo_tags": "ಕಾಮಾ (,) ಹಾಕಿ ಬೇರ್ಪಡಿಸಿದ 15 YouTube SEO ಟ್ಯಾಗ್‌ಗಳು",
  "script": "ಇಲ್ಲಿ 750 ರಿಂದ 900 ಪದಗಳ ಪೂರ್ತಿ 4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆ. ಸ್ಕ್ರಿಪ್ಟ್ ವಿಭಾಗಗಳು ಈ ರೀತಿ ಇರಲಿ: 1) ಮೊದಲ 60 ಪದಗಳು ಸಿನಿಮಾ ಮತ್ತು ಟ್ರೈಲರ್ ಕುರಿತ ಪವರ್‌ಫುಲ್ ಹುಕ್ ಆಗಿರಲಿ, ನಂತರ 'ನಮಸ್ಕಾರ ಸಿನಿಮಾ ಪ್ರಿಯರೇ, MK CINEVIEW ಕನ್ನಡ ಚಾನೆಲ್‌ಗೆ ಸ್ವಾಗತ' ಇರಲಿ. 2) ಸಿನಿಮಾದ ಸಂಪೂರ್ಣ ವಿವರ (ಸುಮಾರು 250 ಪದಗಳು): IMDb ನಲ್ಲಿರುವ ನಿಖರವಾದ ನಿರ್ದೇಶಕರು, ತಾರಾಗಣ (Cast), ಜಾನರ್ (Genre) ಮತ್ತು ಸಿನಿಮಾದ ಕಥಾಹಂದರವನ್ನು ವಿವರಿಸು. 3) ಟ್ರೈಲರ್ ಆಳವಾದ ವಿಶ್ಲೇಷಣೆ (ಸುಮಾರು 300 ಪದಗಳು): ಟ್ರೈಲರ್‌ನ ಪ್ರಮುಖ ದೃಶ್ಯಗಳು, ಹೀರೋ ಎಂಟ್ರಿ, ಆಕ್ಷನ್/ಡ್ರಾಮಾ, BGM, ಕ್ಯಾಮೆರಾ ವರ್ಕ್ (Cinematography) ಮತ್ತು ಸೀಕ್ರೆಟ್ ಅಂಶಗಳನ್ನು ವಿಶ್ಲೇಷಿಸು. 4) ಸಿನಿಮಾ ರಿಲೀಸ್ ನಿರೀಕ್ಷೆ ಮತ್ತು ಕ್ಲೋಸಿಂಗ್ (ಸುಮಾರು 150 ಪದಗಳು): ಪ್ರೇಕ್ಷಕರಲ್ಲಿರುವ ಕ್ರೇಜ್ ಹೇಗಿದೆ ಎಂಬುದನ್ನು ಹೇಳಿ, ಕೊನೆಯಲ್ಲಿ ಮಾತ್ರ ವೀಕ್ಷಕರ ಅಭಿಪ್ರಾಯ ಕೇಳುವ ಒಂದು ಪ್ರಶ್ನೆ ಮತ್ತು Subscribe Call to Action ಇರಲಿ. 5) ಇಂಗ್ಲಿಷ್ ಸಿನಿಮಾ ಪದಗಳನ್ನು (Trailer, Teaser, Movie, Release, OTT, Box office, BGM, Cinematography, Prime Video, Netflix, Zee5, JioHotstar, Subscribe) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ. 6) ಯಾವುದೇ ಸ್ಟಾರ್ (*, #) ಅಥವಾ ಎಮೋಜಿ ಬಳಸಬೇಡ."
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

def create_both_thumbnails(poster_url: str, image_prompt: str, top_text: str, bottom_text: str):
    """Free Pollinations AI (Flux) ಅಥವಾ IMDb HD ಪೋಸ್ಟರ್ ಬಳಸಿ ಖಾಲಿ HD ಫೋಟೋ + ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್ ಸಿದ್ಧಪಡಿಸುತ್ತದೆ"""
    print("100% Free Pollinations AI (Flux) ಮೂಲಕ ಖಾಲಿ HD ಥಂಬ್‌ನೇಲ್ ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ...", flush=True)
    clean_img = None

    try:
        full_prompt = f"{image_prompt}, 16:9 widescreen cinematic movie still, ultra detailed, no text, no letters, no watermark"
        encoded_prompt = urllib.parse.quote(full_prompt)
        seed = int(time.time()) % 100000
        poll_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&model=flux&nologo=true&seed={seed}"
        r = requests.get(poll_url, timeout=45)
        if r.status_code == 200 and len(r.content) > 15000:
            clean_img = Image.open(io.BytesIO(r.content)).convert("RGB")
            print("Pollinations AI (Flux) ಮೂಲಕ ಖಾಲಿ HD ಫೋಟೋ ಯಶಸ್ವಿಯಾಗಿ ಸಿದ್ಧವಾಗಿದೆ!", flush=True)
    except Exception as e:
        print(f"Pollinations AI ಎಚ್ಚರಿಕೆ: {e}", flush=True)

    if clean_img is None and poster_url:
        try:
            r = requests.get(poster_url, timeout=15)
            if r.status_code == 200 and len(r.content) > 5000:
                clean_img = Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:
            pass

    if clean_img is None:
        return None, None

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
    return clean_photo_path, final_thumb_path

def extract_16_hd_frames_from_imdb(trailer_url: str, target_count: int = 16) -> list[str]:
    """IMDb ಟ್ರೈಲರ್ ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ FFmpeg ಮೂಲಕ 16 ಅತ್ಯಂತ ಸ್ಪಷ್ಟ HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡುತ್ತದೆ"""
    if not trailer_url:
        return []

    print(f"IMDb ಟ್ರೈಲರ್ ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಮಾಡಲಾಗುತ್ತಿದೆ: {trailer_url}", flush=True)
    video_file = "imdb_trailer.mp4"
    dl_opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": video_file,
        "format": "best[height<=1080][ext=mp4]/best[ext=mp4]/best",
        "http_headers": HEADERS
    }
    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.extract_info(trailer_url, download=True)
    except Exception as e:
        print(f"IMDb ಟ್ರೈಲರ್ ಡೌನ್‌ಲೋಡ್ ಎರರ್: {e}", flush=True)
        return []

    if not os.path.exists(video_file) or os.path.getsize(video_file) < 150000:
        return []

    print("IMDb ಟ್ರೈಲರ್ ಯಶಸ್ವಿಯಾಗಿ ಡೌನ್‌ಲೋಡ್ ಆಗಿದೆ! 16 HD ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಲಾಗುತ್ತಿದೆ...", flush=True)
    try:
        dur_res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_file],
            capture_output=True, text=True, check=True
        )
        duration = float(dur_res.stdout.strip())
    except Exception:
        duration = 120.0

    start_sec = max(3.0, duration * 0.06)
    end_sec = max(start_sec + 10.0, duration * 0.90)
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

    final_frames = []
    if scored_frames:
        scored_frames.sort(key=lambda x: x[0], reverse=True)
        top_frames = sorted(scored_frames[:target_count], key=lambda x: x[1])
        for idx, (_, _, path) in enumerate(top_frames, start=1):
            clean_name = f"hd_scene_{idx:02d}.jpg"
            os.replace(path, clean_name)
            final_frames.append(clean_name)
        print(f"IMDb ಟ್ರೈಲರ್‌ನಿಂದ {len(final_frames)} ಅತ್ಯುತ್ತಮ HD ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಲಾಗಿದೆ!", flush=True)

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
    """Gemini API ಬಳಸಿ ಒಂದೇ ಬಾರಿಗೆ temperature=0.45 ನಲ್ಲಿ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ ಜನರೇಟ್ ಮಾಡುತ್ತದೆ"""
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

    temps = [0.45, 0.45]
    best_mp3 = None
    best_dur = 0.0

    for attempt, temp in enumerate(temps, start=1):
        print(f"Gemini ಮೂಲಕ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ ಜನರೇಟ್ ಆಗುತ್ತಿದೆ (ಪ್ರಯತ್ನ {attempt}/2, temperature={temp})...", flush=True)
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
    custom_imdb_id, custom_topic = check_telegram_command(state)
    
    movie_info = auto_find_imdb_movie(history, custom_imdb_id=custom_imdb_id, custom_topic=custom_topic)
    if not movie_info:
        print("ಹೊಸ IMDb ಸಿನಿಮಾ ಸಿಗಲಿಲ್ಲ.", flush=True)
        save_state(state)
        return

    imdb_id = movie_info["imdb_id"]
    movie_title = movie_info["title"]
    imdb_url = movie_info["url"]
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # 1. Gemini ಮೂಲಕ ಸ್ಕ್ರಿಪ್ಟ್, SEO ಪ್ಯಾಕೇಜ್ ಮತ್ತು ಥಂಬ್‌ನೇಲ್ ಟೆಕ್ಸ್ಟ್ ಜನರೇಟ್ ಮಾಡುವುದು
    content_data = generate_script_and_seo(movie_info)
    top_txt = content_data.get("top_text", "ಟ್ರೈಲರ್ ಧಮಾಕಾ!")
    bottom_txt = content_data.get("bottom_text", "ಸಿನಿಮಾ ಕಥೆ & ರಿವ್ಯೂ!")
    img_prompt = content_data.get("thumbnail_image_prompt", f"Cinematic South Indian movie scene for {movie_title}, dramatic lighting, 8k, no text")
    script_text = content_data.get("script", "")

    # 2. Free Pollinations AI (Flux) ಮೂಲಕ ಖಾಲಿ HD ಫೋಟೋ + ರೆಡಿಮೇಡ್ ಥಂಬ್‌ನೇಲ್ ಎರಡನ್ನೂ ಸಿದ್ಧಪಡಿಸುವುದು
    clean_path, thumb_path = create_both_thumbnails(movie_info.get("poster_url"), img_prompt, top_txt, bottom_txt)

    if clean_path and os.path.exists(clean_path):
        clean_caption = (
            f"🎬 <b>{movie_title}</b>\n"
            f"🔗 <b>IMDb Link:</b> {imdb_url}\n\n"
            f"🖼️ <b>1) ಅಕ್ಷರಗಳಿಲ್ಲದ ಖಾಲಿ HD ಫೋಟೋ (Free AI Clean Photo)</b>"
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

    time.sleep(2)

    # 3. IMDb ಟ್ರೈಲರ್ ವಿಡಿಯೋ ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ 16 HD ದೃಶ್ಯಗಳ ಫೋಟೋಗಳನ್ನು ಕಟ್ ಮಾಡಿ ಕಳುಹಿಸುವುದು
    hd_frames = extract_16_hd_frames_from_imdb(movie_info.get("trailer_url"), target_count=16)
    if hd_frames:
        for batch_idx in range(0, len(hd_frames), 8):
            batch = hd_frames[batch_idx:batch_idx + 8]
            media_group = []
            files_dict = {}
            for idx, fpath in enumerate(batch):
                attach_key = f"photo_{idx}"
                item = {"type": "photo", "media": f"attach://{attach_key}"}
                if idx == 0:
                    item["caption"] = f"📸 <b>IMDb ಟ್ರೈಲರ್‌ನಿಂದ ಕಟ್ ಮಾಡಿದ HD ಫೋಟೋಗಳು (ಭಾಗ {batch_idx//8 + 1})</b>"
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
    header = "🎙️ <b>4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ AI ಸ್ಕ್ರಿಪ್ಟ್ (IMDb ಸಿನಿಮಾ & ಟ್ರೈಲರ್):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

    # 6. Gemini ಮೂಲಕ ಒಂದೇ ಬಾರಿಗೆ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ MP3 ಕಳುಹಿಸುವುದು
    mp3_path = generate_algenib_voice(script_text)
    if mp3_path and os.path.exists(mp3_path):
        with open(mp3_path, "rb") as af:
            requests.post(
                f"{base_url}/sendAudio",
                data={
                    "chat_id": CHAT_ID,
                    "title": f"{movie_title[:40]} - Algenib Voice",
                    "performer": "MK CINEVIEW ಕನ್ನಡ"
                },
                files={"audio": af}
            )
        print("Algenib ವಾಯ್ಸ್ MP3 ಫೈಲ್ Telegram ಗೆ ಕಳುಹಿಸಲಾಗಿದೆ!", flush=True)

    if imdb_id not in history:
        history.append(imdb_id)
    state["videos"] = history
    save_state(state)
    print("ಯಶಸ್ವಿಯಾಗಿ ಎಲ್ಲಾ ಕೆಲಸ ಪೂರ್ಣಗೊಂಡಿದೆ!", flush=True)

if __name__ == "__main__":
    main()
