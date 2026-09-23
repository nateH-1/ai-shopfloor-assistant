# Kuldeep RAG Chatbot

A Retrieval-Augmented Generation (RAG) chatbot with document upload, multi-document querying, and voice transcription.

**Stack:** Flask + LangChain + ChromaDB + OpenAI (backend) · Next.js 15 + React 19 + TypeScript + Tailwind CSS (frontend)

---

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests targeting `main`, pushes to
`main`, and manual workflow runs. It provides two checks:

- **Backend tests**: Python 3.12 runs the mocked Flask unit tests using
  `backend/requirements-test.txt`. Application package versions are constrained
  by `backend/requirements.txt`. No OpenAI key, running backend, or vector
  database is required. These tests do not validate the full RAG dependency
  installation or live model quality; the evaluation scripts remain separate.
- **Frontend build**: Node.js 22 installs the lockfile with `npm ci`, checks
  TypeScript, and builds the Next.js application. The build needs network access
  to download the Google fonts used by the layout.

To run the same checks locally, from `backend/` in a Python virtual environment:

```shell
python -m pip install -r requirements-test.txt
python -m pytest test_chat_endpoint.py -v
```

From `frontend/`:

```shell
npm ci
npx tsc --noEmit
npm run build
```

## Prerequisites

The following must be installed **manually** before running any startup script. `start-dev.ps1 -InstallDeps` will not install these for you.

### Python 3.10+
Download from [python.org](https://www.python.org/downloads/) or via winget:
```powershell
winget install Python.Python.3.13
```
Make sure `python` is on your `PATH` (tick "Add to PATH" during install on Windows).

### Python virtual environment
Create the venv once at the project root before first use:
```powershell
python -m venv venv
```
The start script looks for `venv\Scripts\python.exe` (root) or `backend\venv\Scripts\python.exe` and will throw an error if neither exists.

### Node.js 18+
Download from [nodejs.org](https://nodejs.org/) or via winget:
```powershell
winget install OpenJS.NodeJS.LTS
```
`npm` must be on your `PATH`. The start script calls `npm run dev` (and `npm install` with `-InstallDeps`) and will fail silently if Node isn't found.

### OpenAI API key
Create a `.env` file in the project root (see **Environment Setup** below). Without a valid key, chat and voice transcription will not work.

---

### What `-InstallDeps` handles automatically
Once the above are in place, passing `-InstallDeps` to the start script will:
- Run `pip install -r backend/requirements.txt` (Python packages: Flask, LangChain, ChromaDB, etc.)
- Run `npm install` in `frontend/` (Next.js and all JS dependencies)

You only need to do this once after cloning, or when dependencies change.

---

## Environment Setup

Create a `.env` file in the project root (one already exists as a template):

```env
OPENAI_API_KEY=your-openai-api-key-here

# Optional overrides
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
```

---

## Startup

### Quick start (both servers)

```powershell
.\start-dev.ps1
```

This opens two terminal windows — one for the backend (port 5000) and one for the frontend (port 3000).

Once both are ready, open: **http://localhost:3000**

---

### First-time setup (install dependencies)

```powershell
.\start-dev.ps1 -InstallDeps
```

This runs `pip install -r requirements.txt` and `npm install` before starting.

---

### Start only one server

```powershell
.\start-dev.ps1 -NoFrontend   # backend only (port 5000)
.\start-dev.ps1 -NoBackend    # frontend only (port 3000)
```

---

## Stopping

```powershell
.\stop-dev.ps1
```

Kills all processes spawned by `start-dev.ps1` and frees ports 5000 and 3000.

---

## Manual Startup (without the scripts)

### Backend

```powershell
# From the project root, with your venv activated:
cd backend
python run.py
```

### Frontend

```powershell
cd frontend
npm run dev
```

---

## Pre-loading Documents (optional)

To bulk-ingest PDFs into the vector database before starting the server (instead of file upload buttons in the app):

```powershell
cd backend
python ingest.py                        # ingest all files in knowledge_ba

se/
python ingest.py path/to/document.pdf   # ingest a single file
```

Supported upload formats (via the UI or ingest script): `.pdf`, `.txt`, `.md`, `.json`, `.docx`, `.csv`, `.tsv`, `.html`

---

## API Endpoints (Backend — port 5000)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Send a message (used by Next.js proxy) |
| `GET` | `/api/documents` | List uploaded documents |
| `POST` | `/api/documents/upload` | Upload and ingest a document |
| `DELETE` | `/api/documents/<filename>` | Delete a document and its vectors |
| `POST` | `/api/clear` | Clear conversation history for a session |
| `GET` | `/api/health` | Health check |

---

## Project Structure

```
kuldeep-chatbot/
├── .env                    # API keys and config
├── start-dev.ps1           # Start both servers
├── stop-dev.ps1            # Stop both servers
├── backend/
│   ├── app.py              # Flask app + RAG pipeline
│   ├── ingest.py           # Batch document ingestion script
│   ├── run.py              # Backend entry point
│   ├── requirements.txt    # Python dependencies
│   ├── knowledge_base/     # Uploaded documents
│   └── chroma_db/          # Vector database (auto-generated)
└── frontend/
    ├── src/
    │   ├── app/            # Next.js pages and API routes
    │   └── components/     # React UI components
    └── package.json
```
