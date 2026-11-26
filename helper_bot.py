import os
import io
import json
import time
import struct
import urllib.parse
import subprocess
import requests
import yt_dlp
from PIL import Image
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
    "spoof", "reaction", "full movie", "roast", "breakdown", "dubbed",
    "ai", "ai generated", "shorts", "short", "status", "edit", "song", "lyrical"
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
            encoded_q = urllib.parse.quote(f"{custom_topic} Official Trailer Kannada 2026")
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
                if not (85 <= duration <= 360):
                    continue
                if any(bad in title_lower for bad in IGNORE_WORDS):
                    continue
                if not any(req in title_lower for req in REQUIRED_WORDS):
                    continue

                is_kannada_query = ("kannada" in query.lower() or "ಕನ್ನಡ" in query)
                if "ott" in title_lower or "week" in title_lower or "ರಿಲೀಸ್" in title_lower:
                    min_views = 2000 if is_kannada_query else 5000
                else:
                    min_views = 10000 if is_kannada_query else 25000

                if view_count > 0 and view_count < min_views:
                    continue

                return f"https://www.youtube.com/watch?v={vid_id}", vid_id, title
    return None, None, None

def get_real_youtube_thumbnail(vid_id: str):
    """YouTube ನ ಒರಿಜಿನಲ್ HD ಥಂಬ್‌ನೇಲ್ ಫೋಟೋವನ್ನು ಡೌನ್‌ಲೋಡ್ ಮಾಡುತ್ತದೆ"""
    for quality in ["maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"]:
        try:
            r = requests.get(f"https://img.youtube.com/vi/{vid_id}/{quality}", timeout=15)
            if r.status_code == 200 and len(r.content) > 5000:
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                thumb_path = "real_thumbnail.jpg"
                img.save(thumb_path, "JPEG", quality=95)
                print(f"ರಿಯಲ್ YouTube ಥಂಬ್‌ನೇಲ್ ಡೌನ್‌ಲೋಡ್ ಆಗಿದೆ ({quality})", flush=True)
                return thumb_path
        except Exception:
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

def generate_script_and_seo(title, url):
    print("Gemini ಮೂಲಕ 4-6 ನಿಮಿಷದ ಸ್ಕ್ರಿಪ್ಟ್ ಮತ್ತು SEO ಪ್ಯಾಕೇಜ್ ಸಿದ್ಧವಾಗುತ್ತಿದೆ...", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸೀನಿಯರ್ ಫಿಲ್ಮ್ ಕ್ರಿಟಿಕ್, SEO ಎಕ್ಸ್‌ಪರ್ಟ್ ಮತ್ತು ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್.
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ವಿಷಯವನ್ನು ಆಧರಿಸಿ:
1) ಕಡ್ಡಾಯವಾಗಿ **4 ರಿಂದ 6 ನಿಮಿಷ ಓದುವಷ್ಟು (ಕನಿಷ್ಠ 750 ರಿಂದ 900 ಪದಗಳ)** ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆ. ಈ ಸ್ಕ್ರಿಪ್ಟ್‌ನಲ್ಲಿ **ಮೂವಿ ಟ್ರೈಲರ್ ವಿಶ್ಲೇಷಣೆ ಮತ್ತು ಆ ಸಿನಿಮಾದ ಸಂಪೂರ್ಣ ವಿವರ** ಎರಡೂ ಸಮಾನವಾಗಿ ಇರಬೇಕು.
2) YouTube SEO ಪ್ಯಾಕೇಜ್ (3 ಟೈಟಲ್‌ಗಳು, ಡಿಸ್ಕ್ರಿಪ್ಶನ್, ಟ್ಯಾಗ್‌ಗಳು) ಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಈ ಕೆಳಗಿನ ನಿಖರ JSON ಫಾರ್ಮ್ಯಾಟ್‌ನಲ್ಲಿ ಮಾತ್ರ ಉತ್ತರ ಕೊಡು:
{{
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
    custom_topic = check_telegram_topic_command(state)
    
    url, vid_id, search_title = search_video(history, custom_topic=custom_topic)
    if not url:
        print("ಹೊಸ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.", flush=True)
        save_state(state)
        return

    print(f"ವಿಡಿಯೋ ಸಿಕ್ಕಿದೆ: {url}", flush=True)
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # 1. ರಿಯಲ್ YouTube ಥಂಬ್‌ನೇಲ್ ಫೋಟೋ ಮತ್ತು ಲಿಂಕ್ ಕಳುಹಿಸುವುದು
    real_thumb = get_real_youtube_thumbnail(vid_id)
    caption = (
        f"🎬 <b>{search_title}</b>\n"
        f"🔗 <b>YouTube Link:</b> {url}\n\n"
        f"🖼️ <b>ರಿಯಲ್ YouTube ಥಂಬ್‌ನೇಲ್ (Real Thumbnail)</b>"
    )
    if real_thumb and os.path.exists(real_thumb):
        with open(real_thumb, "rb") as tf:
            requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": tf}
            )
    else:
        requests.post(f"{base_url}/sendMessage", data={"chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML"})

    time.sleep(2)

    # 2. Gemini ಮೂಲಕ ಸ್ಕ್ರಿಪ್ಟ್ ಮತ್ತು SEO ಪ್ಯಾಕೇಜ್ ಜನರೇಟ್ ಮಾಡುವುದು
    content_data = generate_script_and_seo(search_title, url)
    script_text = content_data.get("script", "")

    # 3. YouTube SEO ಪ್ಯಾಕೇಜ್ ಕಳುಹಿಸುವುದು
    titles_formatted = "\n".join([f"{i+1}. {t}" for i, t in enumerate(content_data.get("seo_titles", []))])
    seo_msg = (
        f"🚀 <b>YouTube SEO ಪ್ಯಾಕೇಜ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
        f"📌 <b>Titles:</b>\n{titles_formatted}\n\n"
        f"📝 <b>Description:</b>\n{content_data.get('seo_description', '')}\n\n"
        f"🏷️ <b>Tags:</b>\n<code>{content_data.get('seo_tags', '')}</code>"
    )
    requests.post(f"{base_url}/sendMessage", data={"chat_id": CHAT_ID, "text": seo_msg, "parse_mode": "HTML"})

    time.sleep(2)

    # 4. 4-6 ನಿಮಿಷದ ಸ್ಕ್ರಿಪ್ಟ್ ಕಳುಹಿಸುವುದು
    header = "🎙️ <b>4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ AI ಸ್ಕ್ರಿಪ್ಟ್ (ಸಿನಿಮಾ & ಟ್ರೈಲರ್):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

    # 5. Gemini ಮೂಲಕ ಒಂದೇ ಬಾರಿಗೆ ಪೂರ್ತಿ Algenib ವಾಯ್ಸ್ MP3 ಕಳುಹಿಸುವುದು
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
