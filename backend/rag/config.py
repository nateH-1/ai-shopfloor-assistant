from pathlib import Path

KNOWLEDGE_BASE_DIR = Path("knowledge_base")
CHROMA_DB_DIR      = "chroma_db"
DOCUMENTS_JSON     = Path("knowledge_base/documents.json")
MODEL_NAME         = "gpt-4o-mini"
NUM_CHUNKS         = 12         # k=12 for broader recall on dense technical documents
CHUNK_SIZE         = 1000
CHUNK_OVERLAP      = 200
MAX_UPLOAD_MB      = 32
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".json", ".docx", ".csv", ".tsv", ".html", ".htm"}
BROAD_INTENT_PHRASES = {
    "all documents", "all the documents", "all docs", "all the docs",
    "across all", "across documents", "across the documents", "from all",
    "compare", "consolidate", "summarize all", "all relevant",
    "every document", "every doc", "from every",
}
SESSION_TTL_SECONDS      = 2 * 60 * 60   # evict sessions idle for 2 hours
MAX_MULTI_DOC_CHUNKS     = 40            # hard cap on total chunks sent to LLM (≈10K tokens)

KNOWLEDGE_BASE_DIR.mkdir(exist_ok=True)