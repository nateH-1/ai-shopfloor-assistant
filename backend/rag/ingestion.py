import csv
import json
import traceback
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.config import CHUNK_OVERLAP, CHUNK_SIZE


def _load_docs(filepath: Path) -> list:
    """Return a list of LangChain Documents for any supported file type."""
    ext = filepath.suffix.lower()

    if ext == ".pdf":
        return PyPDFLoader(str(filepath)).load()

    if ext in (".txt", ".md"):
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(filepath), encoding="utf-8").load()

    if ext == ".json":
        text = filepath.read_text(encoding="utf-8")
        try:
            content = json.dumps(json.loads(text), indent=2)
        except json.JSONDecodeError:
            content = text
        return [Document(page_content=content, metadata={"source": str(filepath)})]

    if ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        return Docx2txtLoader(str(filepath)).load()

    if ext in (".csv", ".tsv"):
        delimiter = "\t" if ext == ".tsv" else ","
        rows = []
        with filepath.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                rows.append(", ".join(f"{k}: {v}" for k, v in row.items()))
        return [Document(page_content="\n".join(rows), metadata={"source": str(filepath)})]

    if ext in (".html", ".htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(filepath.read_text(encoding="utf-8"), "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return [Document(page_content=soup.get_text(separator="\n", strip=True), metadata={"source": str(filepath)})]

    return []


# ── Helper: ingest a single file ──────────────────────────────────────────────
def _ingest_file(filepath: Path, collection) -> tuple[bool, str, int]:
    """Chunk and embed any supported file into the given Chroma collection. Returns (ok, message, chunk_count)."""
    try:
        docs = _load_docs(filepath)
        if not docs:
            return False, f"No content extracted from {filepath.name}.", 0

        splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        chunks   = splitter.split_documents(docs)

        # Remove any existing vectors for this file (handles re-uploads cleanly)
        collection.delete(where={"source": str(filepath)})

        ids       = [f"{filepath.name}__chunk_{i}" for i in range(len(chunks))]
        texts     = [c.page_content for c in chunks]
        metadatas = [{"source": str(filepath), **{k: v for k, v in c.metadata.items() if isinstance(v, (str, int, float, bool))}} for c in chunks]

        # Send in batches to stay under OpenAI's 300k token-per-request limit.
        EMBED_BATCH = 100
        for start in range(0, len(ids), EMBED_BATCH):
            end = start + EMBED_BATCH
            collection.add(ids=ids[start:end], documents=texts[start:end], metadatas=metadatas[start:end])

        return True, f"Ingested {len(chunks)} chunks.", len(chunks)
    except Exception as exc:
        traceback.print_exc()
        return False, f"Ingestion error: {exc}", 0
