<div align="center">

<img src="docs/assets/logo.svg" alt="Looplish" width="128" height="128" />

# Looplish

**Split any video or audio into sentences, then loop them one at a time for focused listening practice.**

[简体中文](README.md) · English

[![License: MIT](https://img.shields.io/badge/license-MIT-F0A22E.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB.svg?logo=python&logoColor=white)](.python-version)
[![Node.js 24](https://img.shields.io/badge/node-24-5FA04E.svg?logo=nodedotjs&logoColor=white)](.nvmrc)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](apps/api)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=black)](apps/web)

</div>

---

## About

Looplish is a listening-practice tool that runs on your own machine. Paste a video link (or upload a file) and it downloads the media, picks up existing subtitles or transcribes the speech with Whisper, then splits the whole thing into sentences using pauses and punctuation. In the practice view you can play each sentence on its own: loop it, slow it down, or hide the text and listen blind, like the repeat button on a language-lab tape deck.

All processing happens locally. Media, subtitles and speech models are stored on your machine, and audio never leaves it unless you choose a cloud transcription backend.

> The web UI is currently in Simplified Chinese.

## Why Looplish

**Hear it first. Read it later.**

We learn our first language by ear, years before we learn to read. With a new language we usually start from the text, and our ears never catch up.

Looplish puts listening first again: hide the text, loop each sentence until you can hear every word, then look.

## Demo

<p align="center">
  <img src="docs/assets/demo.gif" alt="Demo: upload audio, split it into sentences, then listen blind sentence by sentence with looping, slower playback and reveal" width="900" />
  <br />
  <sub>Upload audio and it is split into sentences; in the practice view, listen with the text hidden, loop and slow down, then reveal the sentence</sub>
</p>

## Features

- **Flexible input**: paste any link [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports (YouTube, Bilibili, …). You can paste a whole share message and the link is extracted from it automatically. You can also upload or drag in a local audio/video file, or enter a file path directly when the server runs on your machine.
- **Subtitles first, ASR as fallback**: existing human-made subtitles are used by default, with speech recognition when none are available. In auto mode with local recognition, subtitles without punctuation are re-recognized instead. You can also choose "existing subtitles only" or "always transcribe".
- **Local or cloud ASR**: runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and switches to [MLX](https://github.com/ml-explore/mlx) for GPU acceleration on Apple silicon. OpenAI, Groq and other OpenAI-compatible services are supported too.
- **Smart segmentation**: sentences are cut from word-level timestamps, pauses and punctuation, with padding before and after each one so no syllables get clipped. Minimum/maximum length, pause threshold and padding are all adjustable, and you can re-segment a finished job without transcribing it again.
- **Practice view**:
  - Loop each sentence 1 / 2 / 3 / 5 times or forever; playback speed from 0.60× to 1.25×
  - Shadowing gap: a fixed 0 – 5 seconds, or "as long as the sentence"
  - Hide the text for blind listening, reveal it on demand, or keep it always hidden
  - Auto-advance, sentence search and practice progress
  - Full keyboard shortcuts
- **Export**: subtitles as SRT / VTT / TXT, or a ZIP bundle that can include an MP3 clip for every sentence.
- **Visible progress**: live progress for downloading, audio preparation, transcription and segmentation. Jobs run in a background queue. When the server restarts, jobs it didn't finish are marked as interrupted, so none are left stuck in "processing".

## How it works

```text
link / file ──► download (yt-dlp) ──► prepare audio (ffmpeg) ──► existing subtitles or ASR ──► segmentation ──► practice / export
```

| Stage | What happens |
| --- | --- |
| Download | Link jobs only; existing subtitles are downloaded at the same time when available |
| Prepare audio | ffmpeg probes the duration and converts the media to `m4a` for browser playback |
| Get text | Depending on the subtitle-source setting, use existing subtitles or send the audio to an ASR backend to get a word-level timeline |
| Segment | Split the word stream into sentences by pauses, punctuation and length limits |

## Getting started

### One-command start with Docker (recommended)

All you need is [Docker](https://docs.docker.com/get-docker/):

```bash
git clone https://github.com/ramblincole/looplish.git
cd looplish
```

```bash
docker compose up -d
```

The first run builds the image, which takes a few minutes. Then open <http://127.0.0.1:8756>.

- Media, subtitles and downloaded Whisper models live in the `looplish-data` Docker volume, so they survive container rebuilds.
- To change the ASR model or language, or to use cloud ASR, run `cp .env.example .env`, edit `.env`, then run `docker compose up -d` again.
- ASR runs on the CPU inside the container. On Apple silicon Macs, run from source (below) to get MLX GPU acceleration.
- Local file paths are not available inside the container; upload or drag and drop local files instead.

### Run from source

#### Prerequisites

| Dependency | Version | Notes |
| --- | --- | --- |
| [Python](https://www.python.org/) | 3.13 | Backend |
| [uv](https://docs.astral.sh/uv/) | latest | Python dependencies and virtualenv |
| [Node.js](https://nodejs.org/) | 24 | Frontend |
| [pnpm](https://pnpm.io/) | 10 | Frontend package manager; enable with `corepack enable` |
| [FFmpeg](https://ffmpeg.org/) | any recent | `ffmpeg` and `ffprobe` must be on `PATH`, or set their paths in the config |

#### 1. Clone and install

```bash
git clone https://github.com/ramblincole/looplish.git
cd looplish
```

```bash
uv sync --project apps/api --extra local-asr
```

```bash
pnpm install
```

> If you only plan to use cloud ASR, drop `--extra local-asr` to skip the local Whisper dependencies.

#### 2. Configure

```bash
cp .env.example .env
```

The defaults use local ASR (the `small.en` model, English). The model is downloaded automatically the first time you transcribe something. See [Configuration](#configuration) for every option.

#### 3. Start the backend

Run it from the repository root (the backend reads `.env` from the current directory):

```bash
uv run --project apps/api --extra local-asr uvicorn looplish_api.main:app --host 127.0.0.1 --port 8756
```

#### 4. Start the frontend

In a second terminal:

```bash
pnpm --dir apps/web dev
```

Open <http://127.0.0.1:5173>, paste a video link or pick a local file, and start processing. The dev server proxies `/api` and `/health` to `127.0.0.1:8756`.

#### Single-port mode (optional)

To run a single process, build the frontend and let the backend serve it:

```bash
pnpm --dir apps/web build
```

```bash
LOOPLISH_WEB_DIST_DIR=apps/web/dist uv run --project apps/api --extra local-asr uvicorn looplish_api.main:app --host 127.0.0.1 --port 8756
```

Then open <http://127.0.0.1:8756>.

## Speech recognition backends

Choose a backend with `LOOPLISH_ASR_BACKEND`:

| Value | Description | Requires |
| --- | --- | --- |
| `local` (default) | Local Whisper. With `LOOPLISH_ASR_ENGINE=auto`, it uses the GPU via MLX on Apple silicon when `mlx-whisper` is installed, and faster-whisper otherwise | `--extra local-asr` |
| `openai` | OpenAI transcription API, default model `whisper-1` | `LOOPLISH_ASR_API_KEY` |
| `groq` | Groq transcription API, default model `whisper-large-v3-turbo` | `LOOPLISH_ASR_API_KEY` |
| `fake` | Generates placeholder data, for development and tests only | — |

Cloud backends can point at any other OpenAI-compatible service through `LOOPLISH_ASR_BASE_URL`, with `LOOPLISH_ASR_API_MODEL` choosing the model. Audio over the API's size limit is split into chunks and uploaded automatically.

## Configuration

Every setting is an environment variable prefixed with `LOOPLISH_`, and can also go in `.env` (template: [`.env.example`](.env.example)). Empty values fall back to the defaults.

<details>
<summary>Common settings</summary>

| Variable | Default | Description |
| --- | --- | --- |
| `LOOPLISH_HOST` / `LOOPLISH_PORT` | `127.0.0.1` / `8756` | Listen address (also decides whether the server counts as local-only) |
| `LOOPLISH_WEB_ORIGIN` | `http://127.0.0.1:5173` | Frontend origin allowed by CORS |
| `LOOPLISH_WEB_DIST_DIR` | empty | Frontend build directory; when set, the backend serves the UI |
| `LOOPLISH_DATA_DIR` | OS user data dir | Where media and results are stored |
| `LOOPLISH_MODELS_DIR` | OS user cache dir | Where local ASR models are stored |
| `LOOPLISH_LOG_DIR` | OS user log dir | Log location |
| `LOOPLISH_FFMPEG_PATH` / `LOOPLISH_FFPROBE_PATH` | looked up on `PATH` | FFmpeg executables |
| `LOOPLISH_MAX_WORKERS` | `1` | Jobs processed concurrently (1 – 4) |
| `LOOPLISH_MAX_UPLOAD_BYTES` / `LOOPLISH_MAX_DOWNLOAD_BYTES` | 2 GiB | Upload / download size limits |
| `LOOPLISH_MAX_MEDIA_SECONDS` | `14400` | Maximum media duration (seconds) |
| `LOOPLISH_ASR_BACKEND` | `local` | ASR backend, see above |
| `LOOPLISH_ASR_MODEL` | `small.en` | Local Whisper model |
| `LOOPLISH_LANGUAGE` | `en` | Recognition language; `auto` to detect |
| `LOOPLISH_ASR_ENGINE` | `auto` | Local engine: `auto` / `faster-whisper` / `mlx` |
| `LOOPLISH_ASR_DEVICE` / `LOOPLISH_ASR_COMPUTE_TYPE` | `auto` / `int8` | faster-whisper device and precision |
| `LOOPLISH_ASR_CPU_THREADS` | empty | faster-whisper CPU threads (0 – 64); empty or `0` picks a count from the CPU cores (2/3 of the cores, clamped to 4 – 12) |
| `LOOPLISH_SUBTITLE_SOURCE` | `auto` | Subtitle source: `auto` / `existing` / `asr` |
| `LOOPLISH_SUBTITLE_LANGUAGES` | `en,en-US,en-GB` | Preferred subtitle languages |
| `LOOPLISH_SEG_MIN_SECONDS` / `LOOPLISH_SEG_MAX_SECONDS` | `1.0` / `30.0` | Minimum / maximum sentence length; the maximum is only a safety net, and long sentences are split only at pauses or commas |
| `LOOPLISH_SEG_HARD_PAUSE_SECONDS` | `0.75` | When the transcript lacks punctuation, a pause longer than this ends a sentence; punctuated transcripts follow sentence-ending punctuation |
| `LOOPLISH_SEG_LEAD_PAD_SECONDS` / `LOOPLISH_SEG_TAIL_PAD_SECONDS` | `0.30` / `0.40` | Padding before / after each sentence, up to the whole gap but never into a neighbouring sentence |
| `LOOPLISH_ALLOW_LOCAL_PATHS` | empty | Allow creating jobs from paths on the server; when empty, allowed only on a loopback address |

</details>

> **Security note**: the server listens on `127.0.0.1` by default. If you expose it (e.g. on `0.0.0.0`), local-path input is turned off by default, but you should still put authentication or other protection in front of it.

## Keyboard shortcuts

Available in the practice view (ignored while typing in a text field):

| Key | Action |
| --- | --- |
| `Space` | Play / pause the current sentence |
| `R` | Replay the current sentence from the start |
| `←` / `→` | Previous / next sentence |
| `Enter` | Show / hide the text |
| `L` | Cycle the loop count |
| `[` / `]` | Slower / faster |
| `A` | Toggle auto-advance |
| `Esc` | Close dialogs |

## API

The backend is a REST service. Once it's running, interactive docs are at <http://127.0.0.1:8756/docs>. The contract lives in [`packages/contracts/openapi.json`](packages/contracts/openapi.json), and every error response uses [Problem Details](https://www.rfc-editor.org/rfc/rfc9457) (`application/problem+json`).

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/jobs` | Create a job from a link or a local path |
| `POST` | `/api/v1/jobs/upload` | Create a job from an uploaded file |
| `GET` | `/api/v1/jobs` | List jobs (paginated, filterable by status) |
| `GET` / `DELETE` | `/api/v1/jobs/{id}` | Get / delete a job |
| `GET` | `/api/v1/jobs/{id}/result` | Segmentation result |
| `POST` | `/api/v1/jobs/{id}/resegment` | Re-segment with new parameters |
| `GET` | `/api/v1/jobs/{id}/audio` | Playback audio (supports Range) |
| `GET` | `/api/v1/jobs/{id}/subtitles.{srt,vtt,txt}` | Export subtitles |
| `GET` | `/api/v1/jobs/{id}/clips/{index}` | Single-sentence MP3 |
| `GET` | `/api/v1/jobs/{id}/bundle.zip` | Download everything as a ZIP |
| `GET` | `/api/v1/config` | Available backends and defaults |
| `GET` | `/health/live`, `/health/ready` | Health checks |

## Project structure

```text
looplish/
├── apps/
│   ├── api/                 # Backend: FastAPI + Python 3.13 (layers: domain / application / infrastructure / api)
│   └── web/                 # Frontend: React 19 + Vite + TanStack Query, CSS Modules
├── packages/
│   └── contracts/           # TypeScript types generated from OpenAPI, shared by both sides
├── scripts/
│   └── export_openapi.py    # Exports the OpenAPI contract
├── docs/                    # Design docs and static assets
└── .github/                 # CI and AI code review
```

## Development

Backend (from `apps/api`):

```bash
cd apps/api
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

Frontend:

```bash
pnpm --dir apps/web check
pnpm --dir apps/web exec vitest run
```

After changing the backend API, regenerate the contract and frontend types:

```bash
uv run --project apps/api python scripts/export_openapi.py
pnpm --dir packages/contracts generate
```

## Contributing

Issues and pull requests are welcome.

1. Fork the repository and create a branch such as `feat/xxx` or `fix/xxx`
2. Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat:`, `fix:`, `docs:`, …)
3. Make sure all the checks and tests above pass
4. Open a pull request against `main`

Non-draft pull requests into `main` from branches in this repository are reviewed automatically by an AI reviewer (draft PRs and PRs from forks are not). See [`.github/ai-review/README.md`](.github/ai-review/README.md) (in Chinese) for how the review works and when a PR is merged automatically.

## Disclaimer

Looplish is intended for personal study. When downloading media from a link, follow the site's terms of service and copyright rules, and only process content you have the right to use.

## License

[MIT](LICENSE) © 2026 Nathan Cole
