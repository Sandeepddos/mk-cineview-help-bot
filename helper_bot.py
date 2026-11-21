import os
import json
import time
import wave
import subprocess
import requests
import yt_dlp
from google import genai
from google.genai import types

BOT_TOKEN = os.environ["HELPER_BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

HISTORY_FILE = "helper_history.json"
SEARCH_QUERIES = [
    "New Kannada Movie Official Trailer 2026",
    "Kannada Movie Box Office Collection Day 2 2026"
]

# ನಿನ್ನ Google AI Studio ದ ಫೇವರಿಟ್ ಧ್ವನಿ: Algenib
VOICE_NAME = "Algenib"

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

def generate_script(client, title, url):
    prompt = f"""
ನೀನು 'MK CINEVIEW ಕನ್ನಡ' ಯೂಟ್ಯೂಬ್ ಚಾನೆಲ್‌ನ ಸ್ಕ್ರಿಪ್ಟ್ ರೈಟರ್. 
ಈ ಕೆಳಗಿನ ಯೂಟ್ಯೂಬ್ ವಿಡಿಯೋ ಮಾಹಿತಿಯನ್ನು ಆಧರಿಸಿ, ನಮ್ಮ ಚಾನೆಲ್‌ಗೆ ಸರಿಹೊಂದುವಂತೆ 3 ರಿಂದ 4 ನಿಮಿಷ ಓದುವಷ್ಟು (ಸುಮಾರು 450 ರಿಂದ 550 ಪದಗಳ) ಆಕರ್ಷಕ ಕನ್ನಡ ರಿವ್ಯೂ/ಅನಾಲಿಸಿಸ್ ಸ್ಕ್ರಿಪ್ಟ್ ಬರೆದುಕೊಡು.

ವಿಡಿಯೋ ವಿವರ:
- Title: {title}
- URL: {url}

ಮುಖ್ಯ ನಿಯಮಗಳು:
1. ಸ್ಕ್ರಿಪ್ಟ್ ನೇರವಾಗಿ Intro ದಿಂದ ಶುರುವಾಗಲಿ (ಯಾವುದೇ ಪೀಠಿಕೆ ಅಥವಾ 'ಇಲ್ಲಿದೆ ಸ್ಕ್ರಿಪ್ಟ್' ಎಂಬ ಸಾಲುಗಳು ಬೇಡ).
2. AI Voice ಓದಲು ಸುಲಭವಾಗುವಂತೆ ಕನ್ನಡ ಪದಗಳನ್ನು ಕನ್ನಡ ಲಿಪಿಯಲ್ಲಿ ಮತ್ತು ಇಂಗ್ಲಿಷ್ ಪದಗಳನ್ನು (ಉದಾಹರಣೆಗೆ: Trailer, Box office, BGM, Action, Review, Subscribe, Collection) ಇಂಗ್ಲಿಷ್ ಲಿಪಿಯಲ್ಲೇ ಬರೆ.
3. ಯಾವುದೇ ಸ್ಟಾರ್ ಚಿಹ್ನೆಗಳು (* ಅಥವಾ #) ಅಥವಾ ಎಮೋಜಿಗಳನ್ನು ಸ್ಕ್ರಿಪ್ಟ್ ಒಳಗೆ ಬಳಸಬೇಡ, ಏಕೆಂದರೆ ಇದನ್ನು ನೇರವಾಗಿ AI Voice ಓದುತ್ತದೆ.
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
            print(f"ಸ್ಕ್ರಿಪ್ಟ್ ಮಾಡೆಲ್: {model_name}")
            return response.text
        except Exception:
            continue
    raise RuntimeError("ಯಾವುದೇ Gemini ಮಾಡೆಲ್ ಲಭ್ಯವಾಗಲಿಲ್ಲ.")

def generate_voiceover(client, script_text):
    tts_models = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
    tts_prompt = f"Read the following Kannada movie review script naturally, clearly, and enthusiastically like an engaging Kannada YouTube narrator:\n\n{script_text}"

    for tts_model in tts_models:
        try:
            print(f"Algenib ವಾಯ್ಸ್ ಜನರೇಟ್ ಮಾಡಲಾಗುತ್ತಿದೆ ({tts_model})...")
            response = client.models.generate_content(
                model=tts_model,
                contents=tts_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=VOICE_NAME
                            )
                        )
                    )
                )
            )
            
            audio_bytes = response.candidates[0].content.parts[0].inline_data.data
            wav_path = "voiceover.wav"
            mp3_path = "voiceover.mp3"
            
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_bytes)
                
            subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-b:a", "128k", mp3_path, "-hide_banner", "-loglevel", "error"],
                check=True
            )
            print("Algenib ವಾಯ್ಸ್ MP3 ಯಶಸ್ವಿಯಾಗಿ ಸಿದ್ಧವಾಗಿದೆ!")
            return mp3_path
        except Exception as e:
            print(f"{tts_model} ಎರರ್: {e}")
    return None

def main():
    client = genai.Client(api_key=GEMINI_API_KEY)
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
    
    script_text = generate_script(client, search_title, url)
    header = "📝 <b>3-4 ನಿಮಿಷದ AI ಸ್ಕ್ರಿಪ್ಟ್ (MK CINEVIEW ಕನ್ನಡ):</b>\n\n"
    full_msg = header + script_text
    for i in range(0, len(full_msg), 4000):
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": full_msg[i:i+4000], "parse_mode": "HTML"}
        )
        time.sleep(1)

    mp3_path = generate_voiceover(client, script_text)
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
        print("Algenib ವಾಯ್ಸ್ ಆಡಿಯೋ ಫೈಲ್ Telegram ಗೆ ಕಳುಹಿಸಲಾಗಿದೆ!")
    else:
        requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": CHAT_ID, "text": "⚠️ ಸದ್ಯಕ್ಕೆ TTS ವಾಯ್ಸ್ ಕೋಟಾ ಮಿತಿಯಿಂದ ಆಡಿಯೋ ಜನರೇಟ್ ಆಗಲಿಲ್ಲ, ಮೇಲಿನ ಸ್ಕ್ರಿಪ್ಟ್ ಬಳಸಿಕೋ."}
        )

    history.append(vid_id)
    save_history(history)

if __name__ == "__main__":
    main()
