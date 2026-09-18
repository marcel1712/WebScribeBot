# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

WebScribeBot is a personal Telegram bot: a single allowed user sends an audio recording of a university lecture, and the bot transcribes it, generates structured study notes with Codex, and uploads the notes to Google Drive as markdown.

## Running

```
pip install -r requirements.txt
python main.py
```

There is no test suite, linter, or build step in this repo — verify changes by running the bot manually.

Required env vars (see `.env.example`, loaded via `python-dotenv` in [main.py](main.py)):
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — Pyrogram bot credentials
- `ALLOWED_USER_ID` — only this Telegram user ID is served; every handler checks it first
- `ASSEMBLYAI_API_KEY` — AssemblyAI transcription
- `ANTHROPIC_API_KEY` — Codex note generation
- `DRIVE_FOLDER_ID` — destination Google Drive folder
- `GOOGLE_TOKEN_JSON` — OAuth token for Drive, used in production (Railway) instead of a local `token.json` file

Google Drive auth ([src/drive.py](src/drive.py)) needs `credentials.json` (OAuth client secret, not committed) for the first-time interactive `run_local_server` flow, which then produces `token.json` locally. In production, `GOOGLE_TOKEN_JSON` is set directly so no interactive flow runs.

## Deployment

Deployed on Railway (see [railway.json](railway.json), `startCommand: python main.py`). `apt.txt` requests system `ffmpeg`, but transcription actually relies on the `static-ffmpeg` package ([src/transcriber.py](src/transcriber.py)) which vendors its own ffmpeg/ffprobe binaries via `static_ffmpeg.add_paths()` — this was a deliberate fix after issues with system ffmpeg on Railway's build image (see recent commit history).

## Architecture / pipeline

The flow spans two Pyrogram handlers in [src/bot.py](src/bot.py), split around a button the user has to click:

1. **Ingest** — `handle_audio` matches on `filters.audio | filters.voice | filters.document`, filters to `ALLOWED_USER_ID`, downloads the file, then validates it with `has_audio_stream()` ([src/transcriber.py](src/transcriber.py)) — an `ffprobe` check on the actual file content, not the extension, so any format ffmpeg can decode is accepted regardless of how the filename looks. `_extract_discipline` optionally strips an `aula_NN` prefix and splits camelCase into words to derive a discipline name if the filename encodes one (e.g. `aula_02RedesComplexas.m4a`); if it doesn't, the raw filename stem is used instead — nothing about ingestion depends on the filename matching that convention.
2. **Mode choice** — once the audio is downloaded and validated, `handle_audio` stores it in the in-memory `_pending_jobs` dict and replies with an inline keyboard ("Só transcrição" vs "Transcrição + anotações"). `handle_mode_choice` (the `on_callback_query` handler, matched via `filters.regex(r"^mode:...")`) picks the job back up once the user taps a button and drives the rest of the pipeline. This exists so a Codex API call isn't made (and paid for) for lectures where only the raw transcript is wanted.
3. **Transcribe** — [src/transcriber.py](src/transcriber.py) `transcribe()` first normalizes the input to a standard mp3 via ffmpeg (`_normalize_audio`) regardless of the original container/codec, then sends it to AssemblyAI (`aai.Transcriber().transcribe()`) with `language_code="pt"` and a `word_boost` list derived from the discipline name (`_build_word_boost`) to bias vocabulary. AssemblyAI accepts the file directly (handling its own upload) and supports audio up to 10 hours long, so there's no manual chunking/splitting step.
4. **Summarize (optional)** — only when the user picked "Transcrição + anotações". [src/notes.py](src/notes.py) `generate()` sends the raw transcript plus discipline name to Codex (`Codex-sonnet-4-5`) with a large Portuguese system prompt that defines the expected note structure (overview, numbered topics, key points) and domain framing (USP São Carlos, Sistemas de Informação). When editing note quality/behavior, this system prompt is the place to change.
5. **Upload** — [src/drive.py](src/drive.py) `upload()` writes a file as `text/markdown` into `DRIVE_FOLDER_ID` and returns the `webViewLink`. The raw transcription (`<stem>_transcricao.md`, useful for feeding into tools like NotebookLM) is always uploaded; the generated notes (`<stem>.md`) only when that mode was picked.

Progress is reported back to the user by editing the same status message through each stage, and temp files (downloaded audio, generated notes markdown) are always cleaned up in a `finally` block.

There's no persistence layer beyond `_pending_jobs`, which only bridges the gap between download and the user's button tap — if the bot restarts in that window, the job is lost and the user just resends the audio.