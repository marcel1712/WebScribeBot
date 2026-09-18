import os
import subprocess
from pathlib import Path
import assemblyai as aai
import static_ffmpeg

# Garante que os binários estão disponíveis antes de usar (ffprobe, pra
# validar o áudio antes de subir pra AssemblyAI)
static_ffmpeg.add_paths()

# Lista informativa dos formatos de áudio mais comuns (celular, gravador,
# WhatsApp etc). Não é usada como bloqueio, só documentação — a AssemblyAI
# aceita praticamente qualquer container de áudio/vídeo comum, e quem decide
# se o arquivo é aceito de fato é o ffprobe em has_audio_stream(), que olha
# o conteúdo real, não a extensão.
COMMON_AUDIO_FORMATS = {
    ".m4a",   # iPhone (Gravador/Memorandos, WhatsApp em alguns casos)
    ".mp3",
    ".mp4",   # iPhone às vezes salva áudio/vídeo assim
    ".wav",
    ".ogg", ".oga", ".opus",  # WhatsApp/Android (Opus)
    ".flac",
    ".webm",
    ".aac",
    ".wma",
    ".amr",   # gravador de celulares mais antigos
    ".3gp", ".3gpp",
    ".caf",   # Apple Core Audio (raro, alguns apps de gravação)
    ".mpga", ".mpeg", ".mp2",
}

# AssemblyAI aceita até 5GB / 10h de áudio numa chamada só, então uma aula de
# 1h40 sobe inteira sem precisar fatiar em nenhuma hipótese — nada de
# chunking, normalização de formato nem detecção de silêncio aqui.

aai.settings.api_key = os.environ["ASSEMBLYAI_API_KEY"]

# Termos que ajudam a travar vocabulário técnico (Keyterms Prompting).
# Fixos por padrão + o nome da disciplina extraído do arquivo. Se algum termo
# específico da matéria estiver saindo errado com frequência (nome de autor,
# sigla etc), é só acrescentar aqui.
_BASE_KEYTERMS = ["USP São Carlos", "Sistemas de Informação"]


def has_audio_stream(path: Path) -> bool:
    """Verifica pelo conteúdo real do arquivo (não pela extensão) se existe
    uma trilha de áudio decodificável. É o que decide se um arquivo enviado
    é aceito, então funciona pra qualquer formato que o ffmpeg reconheça,
    mesmo com extensão incomum, errada ou ausente."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    return "audio" in result.stdout


def _build_keyterms(discipline: str) -> list[str]:
    terms = list(_BASE_KEYTERMS)
    if discipline:
        terms.append(discipline)
    return terms


def transcribe(audio_path: Path, discipline: str = "") -> str:
    config = aai.TranscriptionConfig(
        language_code="pt",
        keyterms_prompt=_build_keyterms(discipline),
    )

    transcript = aai.Transcriber().transcribe(str(audio_path), config=config)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"Falha na transcrição (AssemblyAI): {transcript.error}")

    return transcript.text
