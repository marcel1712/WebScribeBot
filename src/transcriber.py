import os
import tempfile
from pathlib import Path
from groq import Groq
from pydub import AudioSegment

SUPPORTED_FORMATS = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm"}
CHUNK_DURATION_MS = 10 * 60 * 1000  # 10 minutos por chunk
MAX_FILE_SIZE = 24 * 1024 * 1024    # 24MB (margem de segurança)

client = Groq(api_key=os.environ["GROQ_API_KEY"])


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_FORMATS


def _transcribe_chunk(chunk_path: Path, original_name: str) -> str:
    with open(chunk_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(original_name, f),
            model="whisper-large-v3",
            language="pt",
            response_format="text",
        )
    return result


def transcribe(audio_path: Path, original_name: str) -> str:
    file_size = audio_path.stat().st_size

    # Arquivo dentro do limite — transcreve direto
    if file_size <= MAX_FILE_SIZE:
        return _transcribe_chunk(audio_path, original_name)

    # Arquivo grande — divide em chunks e transcreve cada um
    ext = Path(original_name).suffix.lower().lstrip(".")
    audio = AudioSegment.from_file(audio_path, format=ext if ext != "m4a" else "mp4")

    chunks = [audio[i:i + CHUNK_DURATION_MS] for i in range(0, len(audio), CHUNK_DURATION_MS)]
    transcriptions = []

    for i, chunk in enumerate(chunks):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        chunk.export(tmp_path, format="mp3")
        chunk_text = _transcribe_chunk(tmp_path, f"chunk_{i}.mp3")
        transcriptions.append(chunk_text)
        tmp_path.unlink(missing_ok=True)

    return " ".join(transcriptions)