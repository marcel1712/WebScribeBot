import os
import tempfile
import subprocess
from pathlib import Path
from groq import Groq
import static_ffmpeg

# Garante que os binários estão disponíveis antes de usar
static_ffmpeg.add_paths()

SUPPORTED_FORMATS = {".m4a", ".mp3", ".wav", ".mp4", ".ogg", ".flac", ".webm"}
CHUNK_MINUTES = 10
MAX_FILE_SIZE = 24 * 1024 * 1024  # 24MB

client = Groq(api_key=os.environ["GROQ_API_KEY"])


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_FORMATS


def _transcribe_chunk(chunk_path: Path, name: str) -> str:
    with open(chunk_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(name, f),
            model="whisper-large-v3",
            language="pt",
            response_format="text",
        )
    return result


def _get_duration_seconds(audio_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def _split_audio(audio_path: Path, chunk_minutes: int) -> list[Path]:
    duration = _get_duration_seconds(audio_path)
    chunk_secs = chunk_minutes * 60
    chunks = []
    start = 0

    while start < duration:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(chunk_secs),
            "-i", str(audio_path),
            "-q:a", "3",
            str(tmp_path)
        ], capture_output=True)

        chunks.append(tmp_path)
        start += chunk_secs

    return chunks


def transcribe(audio_path: Path, original_name: str) -> str:
    file_size = audio_path.stat().st_size

    if file_size <= MAX_FILE_SIZE:
        return _transcribe_chunk(audio_path, original_name)

    chunks = _split_audio(audio_path, CHUNK_MINUTES)
    transcriptions = []

    try:
        for i, chunk in enumerate(chunks):
            text = _transcribe_chunk(chunk, f"chunk_{i}.mp3")
            transcriptions.append(text)
    finally:
        for chunk in chunks:
            chunk.unlink(missing_ok=True)

    return " ".join(transcriptions)