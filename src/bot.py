import os
import re
import logging
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import Message

from src.transcriber import transcribe, is_supported
from src.notes import generate
from src.drive import upload

log = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])


def _is_allowed(message: Message) -> bool:
    return message.from_user.id == ALLOWED_USER_ID


def _extract_discipline(filename: str) -> str:
    stem = Path(filename).stem
    clean = re.sub(r'^aula[_\-]?\d*[_\-]?', '', stem, flags=re.IGNORECASE)
    spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', clean)
    return spaced.strip() if spaced.strip() else stem


async def _safe_edit(status: Message, text: str) -> None:
    try:
        await status.edit(text)
    except RPCError:
        log.warning("Falha ao atualizar mensagem de status (ignorado)", exc_info=True)


def create_app() -> Client:
    app = Client(
        name="WebScribeBot",
        api_id=int(os.environ["TELEGRAM_API_ID"]),
        api_hash=os.environ["TELEGRAM_API_HASH"],
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
    )

    @app.on_message(filters.command("start"))
    async def start(client, message: Message):
        if not _is_allowed(message):
            return
        await message.reply(
            "👋 Oi! Manda o áudio da aula como arquivo com o nome no formato:\n\n"
            "`aula_02RedesComplexas.m4a`\n\n"
            "Eu transcrevo, gero as anotações e salvo no seu Drive. 🎓"
        )

    @app.on_message(filters.audio | filters.voice | filters.document)
    async def handle_audio(client, message: Message):
        if not _is_allowed(message):
            return

        # Pega o arquivo independente do tipo
        media = message.audio or message.voice or message.document
        if not media:
            return

        original_name = getattr(media, "file_name", None) or "aula.m4a"

        if not is_supported(original_name):
            ext = Path(original_name).suffix.lower()
            await message.reply(f"❌ Formato `{ext}` não suportado.")
            return

        discipline = _extract_discipline(original_name)
        status = await message.reply(f"📚 Disciplina: **{discipline}**\n🎙️ Transcrevendo...")

        tmp_audio = None
        tmp_transcription = None
        tmp_notes = None

        try:
            # Baixa o áudio — Pyrogram suporta arquivos grandes
            ext = Path(original_name).suffix.lower() or ".m4a"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                tmp_audio = Path(f.name)

            await message.download(file_name=str(tmp_audio))

            # Transcreve
            transcription = transcribe(tmp_audio, original_name)
            await _safe_edit(status, f"📚 Disciplina: **{discipline}**\n✅ Transcrito\n🧠 Gerando anotações...")

            # Gera notas
            notes = generate(transcription, discipline)
            await _safe_edit(status, f"📚 Disciplina: **{discipline}**\n✅ Transcrito\n✅ Anotações prontas\n☁️ Salvando no Drive...")

            # Salva e faz upload da transcrição bruta
            transcription_filename = Path(original_name).stem + "_transcricao.md"
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
                f.write(transcription)
                tmp_transcription = Path(f.name)

            transcription_link = upload(tmp_transcription, transcription_filename)

            # Salva e faz upload das anotações
            notes_filename = Path(original_name).stem + ".md"
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
                f.write(notes)
                tmp_notes = Path(f.name)

            drive_link = upload(tmp_notes, notes_filename)

            await _safe_edit(
                status,
                f"✨ **Pronto!**\n\n"
                f"📚 {discipline}\n"
                f"📄 [{notes_filename}]({drive_link})\n"
                f"📝 [{transcription_filename}]({transcription_link})",
            )

        except Exception as e:
            log.exception("Erro no processamento")
            await _safe_edit(status, f"❌ Erro: `{e}`")

        finally:
            if tmp_audio:
                tmp_audio.unlink(missing_ok=True)
            if tmp_transcription:
                tmp_transcription.unlink(missing_ok=True)
            if tmp_notes:
                tmp_notes.unlink(missing_ok=True)

    return app