# Local speech-to-text

The microphone records audio in the browser. Next.js forwards it to Flask's
`POST /api/transcribe`; faster-whisper transcribes it on the local backend host.
The existing text input receives the result for review before sending it as chat.
No recording is sent to OpenAI, Hugging Face, or Ollama. There is no cloud fallback.
Ollama is not required for speech recognition, and switching the chat model to
Ollama later does not require changing this speech path.

This change is speech-only. Chat, feedback rewriting, document embeddings, and
retrieval retain their existing configuration. The whole chatbot is not yet offline.

## One-time setup

From the repository root, with Python 3.10+ and the project's virtual environment:

```powershell
.\backend\venv\Scripts\python.exe -m pip install -r backend/requirements-stt.txt
.\backend\venv\Scripts\python.exe backend/prepare_stt.py
```

The complete backend requirements also include the speech dependency. The setup
command downloads the `base.en` model into `.models/whisper-base.en`, ignored by
Git. Internet is needed to download dependencies/model files once; transcription
loads local files only (`local_files_only=True`). Copy that complete model folder
and install dependencies in advance for an offline client deployment. The model
origin is Whisper, but inference does not use OpenAI's hosted service or API key.

Restart Flask and Next.js after setup. The microphone's existing click-to-start,
click-to-stop behavior is unchanged. On another computer in a LAN, browsers
require HTTPS for microphone permission; localhost works during development.

## Configuration

Flask reads these settings from the existing root `.env` at startup:

| Setting | Default | Meaning |
|---|---|---|
| `STT_MODEL_PATH` | Repo `.models/whisper-base.en` | Local model directory; use an absolute path when overriding. |
| `STT_DEVICE` | `cpu` | CPU works without CUDA. GPU setup is optional and separate. |
| `STT_COMPUTE_TYPE` | `int8` | Low-memory CPU inference. |
| `STT_LANGUAGE` | `en` | English; `auto` enables detection with a multilingual model. |
| `STT_MAX_SECONDS` | `120` | Maximum decoded recording length. |

For another model, download it explicitly, then point `STT_MODEL_PATH` to the
output directory. For example:

```powershell
.\backend\venv\Scripts\python.exe backend/prepare_stt.py --model small.en --output .models/whisper-small.en
```

For multiple languages use `base` or `small` rather than the English-only `.en`
models. Larger models can improve accuracy but take more memory and time. Test
manufacturing names, numbers, background noise, and accents with the client's
actual microphone before choosing a deployment model.

## Checking it

- `GET http://localhost:5000/api/transcribe/health` reports local provider, model
  files, and whether the model has loaded. Loading is lazy on the first recording.
- Record: "What are the three basic steps of heat treatment of carbon steel?"
  Stop and confirm the text appears in the input before sending it.
- Silence should report that no speech was detected rather than invent a question.
- With model files installed, speech still works without `OPENAI_API_KEY` and
  without internet. Chat may still need the key until migrated separately.
- API: multipart form field `audio`; success is `{ "text": "..." }`.

The upload limit is 25 MB, decoded duration is limited, and one transcription runs
at a time per Flask process. Empty/missing audio returns 400, invalid/silent audio
422, excessive size/duration 413, busy 429, and local setup/inference failures 503.
The proxy returns 502 if Flask is unreachable or times out. Audio formats are
decoded by bundled PyAV/FFmpeg libraries; no system FFmpeg installation is needed.
The app does not save recordings/transcripts. Flask can temporarily spool larger
multipart uploads on the local host while handling a request.

## Automated tests

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_local_stt.py -q -p no:cacheprovider
cd ../frontend
node --test tests/transcribe.test.cjs
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
```

Unit tests use controlled model/decoder outputs; they verify API behavior, local
loading, and failure handling, not real microphone transcription quality.
