import os
import re
import uuid
import logging
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.transcriber import transcribe, has_audio_stream
from src.notes import generate
from src.drive import upload

log = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])

# Jobs aguardando o usuário escolher "só transcrição" ou "transcrição +
# anotações", indexados por um id curto que vai no callback_data do botão.
# Em memória mesmo (sem persistência): se o bot reiniciar antes do clique, o
# usuário só precisa reenviar o áudio.
_pending_jobs: dict[str, dict] = {}


def _is_allowed(message: Message) -> bool:
    return message.from_user.id == ALLOWED_USER_ID


def _extract_discipline(filename: str) -> str:
    stem = Path(filename).stem
    clean = re.sub(r'^aula[_\-]?\d*[_\-]?', '', stem, flags=re.IGNORECASE)
    spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', clean)
    return spaced.strip() if spaced.strip() else stem


async def _safe_edit(status: Message, text: str, reply_markup=None) -> None:
    try:
        await status.edit(text, reply_markup=reply_markup)
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
            "👋 Oi! Manda o áudio da aula do jeito que você salvou, aceito "
            "praticamente qualquer formato comum (m4a, mp3, mp4, wav, ogg, "
            "opus, flac, aac, entre outros).\n\n"
            "Se puser o nome da disciplina no arquivo eu uso ele nas "
            "anotações, tipo `aula_02RedesComplexas.m4a`, mas não é "
            "obrigatório, qualquer nome funciona.\n\n"
            "Depois que eu receber o áudio, te pergunto se você quer só a "
            "transcrição ou transcrição + anotações. 🎓"
        )

    @app.on_message(filters.audio | filters.voice | filters.document)
    async def handle_audio(client, message: Message):
        if not _is_allowed(message):
            return

        # Pega o arquivo independente do tipo
        media = message.audio or message.voice or message.document
        if not media:
            return

        original_name = getattr(media, "file_name", None) or f"aula_{message.date:%Y%m%d_%H%M}.ogg"
        ext = Path(original_name).suffix.lower() or ".m4a"

        status = await message.reply("⬇️ Baixando áudio...")

        tmp_audio = None
        try:
            # Baixa o áudio — Pyrogram suporta arquivos grandes
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                tmp_audio = Path(f.name)

            await message.download(file_name=str(tmp_audio))

            # Quem decide se aceita é o conteúdo do arquivo, não a extensão
            if not has_audio_stream(tmp_audio):
                await _safe_edit(status, "❌ Não consegui identificar uma trilha de áudio nesse arquivo.")
                tmp_audio.unlink(missing_ok=True)
                return

            discipline = _extract_discipline(original_name)
            job_id = uuid.uuid4().hex[:8]
            _pending_jobs[job_id] = {
                "tmp_audio": tmp_audio,
                "original_name": original_name,
                "discipline": discipline,
            }

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Só transcrição", callback_data=f"mode:transcricao:{job_id}"),
                InlineKeyboardButton("🧠 Transcrição + anotações", callback_data=f"mode:completo:{job_id}"),
            ]])
            await _safe_edit(
                status,
                f"📚 Disciplina: **{discipline}**\n✅ Áudio recebido\n\nO que você quer que eu faça?",
                reply_markup=keyboard,
            )

        except Exception as e:
            log.exception("Erro ao baixar/validar áudio")
            await _safe_edit(status, f"❌ Erro: `{e}`")
            if tmp_audio:
                tmp_audio.unlink(missing_ok=True)

    @app.on_callback_query(filters.regex(r"^mode:(transcricao|completo):"))
    async def handle_mode_choice(client, callback_query: CallbackQuery):
        if callback_query.from_user.id != ALLOWED_USER_ID:
            await callback_query.answer("Não autorizado", show_alert=True)
            return

        _, mode, job_id = callback_query.data.split(":", 2)
        job = _pending_jobs.pop(job_id, None)

        if job is None:
            await callback_query.answer("Esse pedido expirou, manda o áudio de novo.", show_alert=True)
            return

        await callback_query.answer()

        status = callback_query.message
        tmp_audio = job["tmp_audio"]
        original_name = job["original_name"]
        discipline = job["discipline"]
        want_notes = mode == "completo"

        tmp_transcription = None
        tmp_notes = None

        try:
            await _safe_edit(status, f"📚 Disciplina: **{discipline}**\n🎙️ Transcrevendo...")

            # Transcreve
            transcription = transcribe(tmp_audio, discipline)

            notes_filename = None
            drive_link = None

            if want_notes:
                await _safe_edit(status, f"📚 Disciplina: **{discipline}**\n✅ Transcrito\n🧠 Gerando anotações...")
                notes = generate(transcription, discipline)
                await _safe_edit(status, f"📚 Disciplina: **{discipline}**\n✅ Transcrito\n✅ Anotações prontas\n☁️ Salvando no Drive...")

                notes_filename = Path(original_name).stem + ".md"
                with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
                    f.write(notes)
                    tmp_notes = Path(f.name)
                drive_link = upload(tmp_notes, notes_filename)
            else:
                await _safe_edit(status, f"📚 Disciplina: **{discipline}**\n✅ Transcrito\n☁️ Salvando no Drive...")

            # Salva e faz upload da transcrição bruta (sempre)
            transcription_filename = Path(original_name).stem + "_transcricao.md"
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
                f.write(transcription)
                tmp_transcription = Path(f.name)
            transcription_link = upload(tmp_transcription, transcription_filename)

            lines = [f"✨ **Pronto!**\n", f"📚 {discipline}"]
            if want_notes:
                lines.append(f"📄 [{notes_filename}]({drive_link})")
            lines.append(f"📝 [{transcription_filename}]({transcription_link})")

            await _safe_edit(status, "\n".join(lines))

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