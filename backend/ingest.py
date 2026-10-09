"""
ingest.py — Batch PDF ingestion script
=======================================
Use this to pre-load PDFs into the vector database before starting the server,
or to re-build the database after manual changes to the knowledge_base/ folder.

Usage:
    python ingest.py                          # ingest all PDFs in knowledge_base/
    python ingest.py path/to/document.pdf     # ingest a single PDF
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.config import (
    KNOWLEDGE_BASE_DIR,
    CHROMA_DB_DIR,
    DOCUMENTS_JSON,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    ALLOWED_EXTENSIONS,
)
from rag.ingestion import _load_docs

load_dotenv()


def load_registry() -> dict:
    if DOCUMENTS_JSON.exists():
        return json.loads(DOCUMENTS_JSON.read_text())
    return {}


def save_registry(registry: dict) -> None:
    DOCUMENTS_JSON.write_text(json.dumps(registry, indent=2))


def ingest_files(file_paths: list[Path]) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("❌  OPENAI_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  Collective RAG — Batch Ingestion")
    print(f"{'='*60}\n")

    splitter   = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
    registry   = load_registry()
    all_chunks = []

    # Open the store now (if it exists) so we can delete stale vectors per file
    # before re-ingesting — prevents duplicate chunks on repeated runs.
    existing_store = (
        Chroma(persist_directory=CHROMA_DB_DIR, embedding_function=embeddings)
        if os.path.exists(CHROMA_DB_DIR)
        else None
    )

    for filepath in file_paths:
        print(f"📄  Loading: {filepath.name}")
        # Remove any existing vectors for this file before re-ingesting
        if existing_store is not None:
            existing_store.delete(where={"source": str(filepath)})
        docs   = _load_docs(filepath)
        chunks = splitter.split_documents(docs)
        all_chunks.extend(chunks)
        registry[filepath.name] = {
            "chunks":      len(chunks),
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        print(f"    → {len(chunks)} chunks")

    if not all_chunks:
        print("⚠️  No chunks to ingest.")
        return

    print(f"\n🔧  Embedding {len(all_chunks)} total chunks into Chroma DB …")

    if existing_store is not None:
        existing_store.add_documents(all_chunks)
    else:
        Chroma.from_documents(all_chunks, embedding=embeddings, persist_directory=CHROMA_DB_DIR)

    save_registry(registry)
    print(f"\n✅  Done! {len(all_chunks)} chunks stored in {CHROMA_DB_DIR}/")
    print(f"    Registry updated: {DOCUMENTS_JSON}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Specific file(s) provided as arguments
        files = [Path(p) for p in sys.argv[1:]]
        missing = [p for p in files if not p.exists()]
        if missing:
            print(f"❌  Files not found: {missing}")
            sys.exit(1)
        unsupported = [p for p in files if p.suffix.lower() not in ALLOWED_EXTENSIONS]
        if unsupported:
            print(f"❌  Unsupported file types: {[p.name for p in unsupported]}")
            print(f"    Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
            sys.exit(1)
    else:
        # Default: ingest all supported files in knowledge_base/
        files = sorted(
            p for ext in ALLOWED_EXTENSIONS for p in KNOWLEDGE_BASE_DIR.glob(f"*{ext}")
        )
        if not files:
            ext_list = ", ".join(sorted(ALLOWED_EXTENSIONS))
            print(f"⚠️  No supported files found in {KNOWLEDGE_BASE_DIR}/")
            print(f"    Supported formats: {ext_list}")
            print("    Place files there and re-run, or upload via the web UI.")
            sys.exit(0)

    ingest_files(files)

