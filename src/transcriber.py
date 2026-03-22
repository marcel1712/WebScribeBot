import os
from pathlib import Path
from groq import Groq

SUPPORTED_FORMATS = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm"}

client = Groq(api_key=os.environ["GROQ_API_KEY"])


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_FORMATS


def transcribe(audio_path: Path, original_name: str) -> str:
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(original_name, f),
            model="whisper-large-v3",
            language="pt",
            response_format="text",
        )
    return result