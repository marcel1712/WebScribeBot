# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WebScribeBot is a personal Telegram bot: a single allowed user sends an audio recording of a university lecture, and the bot transcribes it, generates structured study notes with Claude, and uploads the notes to Google Drive as markdown.

## Running

```
pip install -r requirements.txt
python main.py
```

There is no test suite, linter, or build step in this repo — verify changes by running the bot manually.

Required env vars (see `.env.example`, loaded via `python-dotenv` in [main.py](main.py)):
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — Pyrogram bot credentials
- `ALLOWED_USER_ID` — only this Telegram user ID is served; every handler checks it first
- `GROQ_API_KEY` — Groq Whisper transcription
- `ANTHROPIC_API_KEY` — Claude note generation
- `DRIVE_FOLDER_ID` — destination Google Drive folder
- `GOOGLE_TOKEN_JSON` — OAuth token for Drive, used in production (Railway) instead of a local `token.json` file

Google Drive auth ([src/drive.py](src/drive.py)) needs `credentials.json` (OAuth client secret, not committed) for the first-time interactive `run_local_server` flow, which then produces `token.json` locally. In production, `GOOGLE_TOKEN_JSON` is set directly so no interactive flow runs.

## Deployment

Deployed on Railway (see [railway.json](railway.json), `startCommand: python main.py`). `apt.txt` requests system `ffmpeg`, but transcription actually relies on the `static-ffmpeg` package ([src/transcriber.py](src/transcriber.py)) which vendors its own ffmpeg/ffprobe binaries via `static_ffmpeg.add_paths()` — this was a deliberate fix after issues with system ffmpeg on Railway's build image (see recent commit history).

## Architecture / pipeline

The whole flow is one linear pipeline driven from a single Pyrogram message handler in [src/bot.py](src/bot.py):

1. **Ingest** — `handle_audio` in [src/bot.py](src/bot.py) matches on `filters.audio | filters.voice | filters.document`, filters to `ALLOWED_USER_ID`, and expects the filename to encode the discipline name, e.g. `aula_02RedesComplexas.m4a`. `_extract_discipline` strips the `aula_NN` prefix and splits camelCase into words to derive the discipline name shown to the user and passed downstream.
2. **Transcribe** — [src/transcriber.py](src/transcriber.py) `transcribe()` sends the audio to Groq's `whisper-large-v3`. Files under 24MB (Groq's limit) go straight through; larger files are split into 10-minute mp3 chunks with ffmpeg (`_split_audio`) and transcribed chunk-by-chunk, then joined with spaces.
3. **Summarize** — [src/notes.py](src/notes.py) `generate()` sends the raw transcript plus discipline name to Claude (`claude-sonnet-4-5`) with a large Portuguese system prompt that defines the expected note structure (overview, numbered topics, key points) and domain framing (USP São Carlos, Sistemas de Informação). When editing note quality/behavior, this system prompt is the place to change.
4. **Upload** — [src/drive.py](src/drive.py) `upload()` writes a file as `text/markdown` into `DRIVE_FOLDER_ID` and returns the `webViewLink`. Both the raw transcription (`<stem>_transcricao.md`, useful for feeding into tools like NotebookLM) and the generated notes (`<stem>.md`) are uploaded this way in [src/bot.py](src/bot.py).

Progress is reported back to the user by editing the same status message through each stage (transcribing → notes ready → saving to Drive → done), and temp files (downloaded audio, generated notes markdown) are always cleaned up in a `finally` block.

There's no persistence layer — each message is processed independently and statelessly beyond the temp files used during that single request.