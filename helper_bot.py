import os
import json
import time
import struct
import urllib.parse
import subprocess
import requests
import yt_dlp
from google import genai
from google.genai import types

BOT_TOKEN = os.environ["HELPER_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

HISTORY_FILE = "helper_history.json"
VOICE_NAME = "Algenib"

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

IGNORE_WORDS = [
    "review", "explained", "ending", "concept", "fan made", "fan-made",
    "spoof", "reaction", "full movie", "roast", "breakdown", "dubbed"
]

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
    print("ಹೊಸ ಕನ್ನಡ ವಿಡಿಯೋ ಹುಡುಕಲಾಗುತ್ತಿದೆ...", flush=True)
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": 10
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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

def generate_script(title, url):
    print("4 ರಿಂದ 6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆಯಲಾಗುತ್ತಿದೆ...", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸೀನಿಯರ್ ಫಿಲ್ಮ್ ಕ್ರಿಟಿಕ್ ಮತ್ತು ಪ್ರೊಫೆಷನಲ್ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್.
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ವಿಷಯವನ್ನು ಆಧರಿಸಿ, ವೀಕ್ಷಕರನ್ನು ಕೊನೆಯವರೆಗೂ ಹಿಡಿದಿಟ್ಟುಕೊಳ್ಳುವ (High-Retention), ಅತ್ಯಂತ ಪ್ರೊಫೆಷನಲ್ ಮತ್ತು ಸಿನಿಮ್ಯಾಟಿಕ್ ಶೈಲಿಯ **ಕಡ್ಡಾಯವಾಗಿ 4 ರಿಂದ 6 ನಿಮಿಷ ಓದುವಷ್ಟು (ಕನಿಷ್ಠ 750 ರಿಂದ 900 ಪದಗಳ)** ಸುದೀರ್ಘ ಮತ್ತು ಆಳವಾದ ಕನ್ನಡ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು. ಯಾವುದೇ ಕಾರಣಕ್ಕೂ ಸ್ಕ್ರಿಪ್ಟ್ ಚಿಕ್ಕದಾಗಿರಬಾರದು!

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಸ್ಕ್ರಿಪ್ಟ್ ರಚನೆ ಮತ್ತು ಪ್ರೊಫೆಷನಲ್ ನಿಯಮಗಳು (ಪ್ರತಿ ವಿಭಾಗವನ್ನೂ ವಿಸ್ತಾರವಾಗಿ ಬರೆ):
1. ಪವರ್‌ಫುಲ್ ಹುಕ್ (The Hook - ಸುಮಾರು 60 ಪದಗಳು): ಬೋರಿಂಗ್ ಆಗಿ 'ನಮಸ್ಕಾರ ಸ್ವಾಗತ' ಎಂದು ಶುರು ಮಾಡಬೇಡ! ನೇರವಾಗಿ ಈ ಸಿನಿಮಾದ ಅತ್ಯಂತ ರೋಚಕ ಅಂಶ ಅಥವಾ ಬಾಕ್ಸ್ ಆಫೀಸ್ ಸಂಚಲನದ ಪಂಚ್ ಲೈನ್‌ನೊಂದಿಗೆ ಶುರುಮಾಡು. ನಂತರ 'ನಮಸ್ಕಾರ ಸಿನಿಮಾ ಪ್ರಿಯರೇ, MK CINEVIEW ಕನ್ನಡ ಚಾನೆಲ್‌ಗೆ ಸ್ವಾಗತ' ಎಂದು ಮುಂದುವರಿಸು.
2. ಸಿನಿಮಾದ ಹಿನ್ನೆಲೆ ಮತ್ತು ಕಥೆಯ ಆಳವಾದ ವಿಶ್ಲೇಷಣೆ (ಸುಮಾರು 250 ಪದಗಳು):
   - ಟ್ರೈಲರ್/ಟೀಸರ್ ಆಗಿದ್ದರೆ: ಸಿನಿಮಾದ ಜಾನರ್ (Genre), ಕಥೆಯ ತಿರುಳು, ಟ್ರೈಲರ್‌ನಲ್ಲಿ ತೋರಿಸಿರುವ ಪ್ರಮುಖ ತಿರುವುಗಳು ಮತ್ತು ಸಿನಿಮಾದ ಒಟ್ಟಾರೆ ಥೀಮ್ ಏನು ಎಂಬುದನ್ನು ವಿವರವಾಗಿ ಬಿಡಿಸಿ ಹೇಳು.
   - OTT/ವಾರದ ರಿಲೀಸ್ ಆಗಿದ್ದರೆ: ಪ್ರತಿ ಸಿನಿಮಾದ ಕಥೆ, ಯಾವ OTT ಪ್ಲಾಟ್‌ಫಾರ್ಮ್ (Prime Video, Netflix, Zee5, JioHotstar, Sun NXT), ರಿಲೀಸ್ ದಿನಾಂಕ ಮತ್ತು ವಿಶೇಷತೆಗಳನ್ನು ವಿಸ್ತಾರವಾಗಿ ವಿವರಿಸು.
   - ಬಾಕ್ಸ್ ಆಫೀಸ್ ಕಲೆಕ್ಷನ್ ಆಗಿದ್ದರೆ: ಮೊದಲ ದಿನದಿಂದ ಇಲ್ಲಿಯವರೆಗಿನ ಕಲೆಕ್ಷನ್ ಏರಿಳಿತ, ಕರ್ನಾಟಕದ ಗಳಿಕೆ, ವರ್ಲ್ಡ್‌ವೈಡ್ ಕಲೆಕ್ಷನ್ ಮತ್ತು ಬಜೆಟ್ ರಿಕವರಿ ಲೆಕ್ಕಾಚಾರವನ್ನು ವಿವರಿಸು.
3. ಪಾತ್ರವರ್ಗ ಮತ್ತು ಅಭಿನಯದ ವಿಶ್ಲೇಷಣೆ (ಸುಮಾರು 180 ಪದಗಳು): ಹೀರೋ, ಹೀರೋಯಿನ್ ಮತ್ತು ಪೋಷಕ ಕಲಾವಿದರ ಲುಕ್, ಡೈಲಾಗ್ ಡೆಲಿವರಿ, ಸ್ಕ್ರೀನ್ ಪ್ರೆಸೆನ್ಸ್ ಮತ್ತು ಪಾತ್ರಗಳ ಮಹತ್ವವನ್ನು ಒಬ್ಬ ಸೀನಿಯರ್ ವಿಮರ್ಶಕನ ಶೈಲಿಯಲ್ಲಿ ವಿಶ್ಲೇಷಿಸು.
4. ತಾಂತ್ರಿಕ ಅಂಶಗಳು ಮತ್ತು ನಿರ್ದೇಶನ (ಸುಮಾರು 180 ಪದಗಳು): ನಿರ್ದೇಶಕರ ಮೇಕಿಂಗ್ ಶೈಲಿ, BGM ಮತ್ತು ಮ್ಯೂಸಿಕ್, ಕ್ಯಾಮೆರಾ ವರ್ಕ್ (Cinematography), ಕಲರ್ ಗ್ರೇಡಿಂಗ್, ಆಕ್ಷನ್ ಅಥವಾ ಎಡಿಟಿಂಗ್ ಹೇಗೆ ಮೂಡಿಬಂದಿದೆ ಎಂಬುದನ್ನು ತಾಂತ್ರಿಕವಾಗಿ ವಿವರಿಸು.
5. ನಿರೀಕ್ಷೆ ಮತ್ತು ಪ್ರೊಫೆಷನಲ್ ಕ್ಲೋಸಿಂಗ್ (ಸುಮಾರು 120 ಪದಗಳು - ಕೊನೆಯಲ್ಲಿ ಮಾತ್ರ ಪ್ರಶ್ನೆ): ಸಿನಿಮಾದ ಪ್ಲಸ್-ಮೈನಸ್ ಅಂಶಗಳನ್ನು ಸಾರಾಂಶ ಮಾಡಿ, ಕೊನೆಯಲ್ಲಿ ಮಾತ್ರ ಪ್ರೇಕ್ಷಕರ ಅಭಿಪ್ರಾಯ ಕೇಳುವ ಒಂದು ಪ್ರಶ್ನೆ ಮತ್ತು 'MK CINEVIEW ಕನ್ನಡ' ಚಾನೆಲ್‌ಗೆ Subscribe ಮಾಡಲು ಕೇಳುವ Call to Action ಇರಲಿ.

ಪ್ರಮುಖ ತಾಂತ್ರಿಕ ನಿಯಮಗಳು:
- ಸ್ಕ್ರಿಪ್ಟ್ ಮಧ್ಯದಲ್ಲಿ ಯಾವುದೇ ಪ್ರಶ್ನೆಗಳನ್ನು ಕೇಳದೆ ನಿರಂತರವಾಗಿ ನಿರೂಪಿಸು.
- AI Voice (Algenib) ಉಚ್ಚಾರಣೆಗೆ ಅನುಕೂಲವಾಗುವಂತೆ ಕನ್ನಡ ಪದಗಳನ್ನು ಶುದ್ಧ ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಮತ್ತು ಇಂಗ್ಲಿಷ್ ಸಿನಿಮಾ ಪದಗಳನ್ನು (Trailer, Teaser, Pan-India, Box office, BGM, Cinematography, Screenplay, Thriller, Action, OTT, Prime Video, Netflix, Zee5, JioHotstar, Blockbuster, Subscribe) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ.
- ಸ್ಕ್ರಿಪ್ಟ್ ಒಳಗೆ ಯಾವುದೇ ಸ್ಟಾರ್ ಚಿಹ್ನೆಗಳು (*, **, #), ಬ್ರಾಕೆಟ್ ಸೂಚನೆಗಳು ([Music], [Pause]), ಹೆಡಿಂಗ್‌ಗಳು ಅಥವಾ ಎಮೋಜಿಗಳನ್ನು ಬಳಸಬೇಡ — ಕೇವಲ ಶುದ್ಧ ಪ್ಯಾರಾಗ್ರಾಫ್‌ಗಳಿರಲಿ.
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
            print(f"ಯಶಸ್ವಿಯಾಗಿ ಬಳಸಿದ ಮಾಡೆಲ್: {model_name}", flush=True)
            return response.text
        except Exception:
            continue
    raise RuntimeError("ಯಾವುದೇ Gemini ಮಾಡೆಲ್ ಲಭ್ಯವಾಗಲಿಲ್ಲ.")

def split_script_cleanly(text: str, target_parts: int = 3) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paragraphs) <= target_parts:
        return paragraphs

    total_len = sum(len(p) for p in paragraphs)
    chunk_target = total_len // target_parts
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) <= chunk_target + 250 or len(chunks) >= target_parts - 1:
            current += ("\n\n" if current else "") + p
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
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

def generate_single_chunk_wav(client, text_part: str, part_index: int) -> str | None:
    model = "gemini-2.5-flash-preview-tts"
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"## Transcript:\n{text_part}")],
        ),
    ]
    temps = [0.45, 0.55, 0.7]
    best_wav = None
    best_dur = 0.0

    for attempt, temp in enumerate(temps, start=1):
        print(f"ಭಾಗ {part_index+1} - ಪ್ರಯತ್ನ {attempt}/3 (temperature={temp})...", flush=True)
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
                print(f"ಭಾಗ {part_index+1} (ಪ್ರಯತ್ನ {attempt}) ಉದ್ದ: {dur:.1f} ಸೆಕೆಂಡ್‌ಗಳು", flush=True)

                if dur > best_dur:
                    best_dur = dur
                    best_wav = wav_path

                # ಪ್ರತಿ ಭಾಗ ಕನಿಷ್ಠ 45 ಸೆಕೆಂಡ್‌ಗಿಂತ ಹೆಚ್ಚಿದ್ದರೆ ಕಟ್ ಆಗಿಲ್ಲ ಅಂತ ಅರ್ಥ
                if dur >= 45.0:
                    return wav_path
                else:
                    print(f"ಭಾಗ {part_index+1} ಅರ್ಧಕ್ಕೆ ಕಟ್ ಆಗಿದೆ, ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ...", flush=True)
                    time.sleep(2)
        except Exception as e:
            print(f"ಭಾಗ {part_index+1} ಪ್ರಯತ್ನ {attempt} ಎರರ್: {e}", flush=True)
            time.sleep(2)

    return best_wav

def generate_algenib_voice(script_text: str):
    # 4-6 ನಿಮಿಷದ ದೊಡ್ಡ ಸ್ಕ್ರಿಪ್ಟ್ ಕಟ್ ಆಗದಂತೆ 3 ಭಾಗಗಳಾಗಿ ಸ್ಟ್ರೀಮ್ ಮಾಡಿ ಒಂದೇ MP3 ಮಾಡುತ್ತದೆ
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    parts = split_script_cleanly(script_text, target_parts=3)
    print(f"4-6 ನಿಮಿಷದ ಆಡಿಯೋ ಕಟ್ ಆಗದಂತೆ {len(parts)} ಭಾಗಗಳಲ್ಲಿ ಸಿದ್ಧಪಡಿಸಲಾಗುತ್ತಿದೆ...", flush=True)

    final_wavs = []
    for idx, part_text in enumerate(parts):
        wav_file = generate_single_chunk_wav(client, part_text, idx)
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
    history = load_history()
    url, vid_id, search_title = search_latest_video(history)
    
    if not url:
        print("ಕಳೆದ 24 ಗಂಟೆಗಳಲ್ಲಿ ಯಾವುದೇ ಹೊಸ ಟ್ರೈಲರ್, OTT ಅಥವಾ ಬಾಕ್ಸ್ ಆಫೀಸ್ ವಿಡಿಯೋ ಸಿಗಲಿಲ್ಲ.", flush=True)
        return

    print(f"ಹೊಸ ವಿಡಿಯೋ ಸಿಕ್ಕಿದೆ: {url}", flush=True)
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
    
    header = "📝 <b>4-6 ನಿಮಿಷದ ಪ್ರೊಫೆಷನಲ್ AI ಸ್ಕ್ರಿಪ್ಟ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

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
    else:
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": "⚠️ ಸದ್ಯಕ್ಕೆ Algenib ಆಡಿಯೋ ಜನರೇಟ್ ಆಗಲಿಲ್ಲ, ಮೇಲಿನ ಸ್ಕ್ರಿಪ್ಟ್ ಅನ್ನು AI Studio ದಲ್ಲಿ ಬಳಸಿಕೋ."}
        )

    history.append(vid_id)
    save_history(history)
    print("ಯಶಸ್ವಿಯಾಗಿ ಎಲ್ಲಾ ಕೆಲಸ ಪೂರ್ಣಗೊಂಡಿದೆ!", flush=True)

if __name__ == "__main__":
    main()
