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
KEYWORD_FALLBACK_DISTANCE = 0.20         # best vector distance at which keyword results are added
RRF_K                    = 60            # reciprocal rank fusion constant

# Model provider defaults; override in .env (see .env.example). Embeddings always use OpenAI.
DEFAULT_LLM_PROVIDER     = "openai"
DEFAULT_OLLAMA_MODEL     = "gemma3:4b"
DEFAULT_OLLAMA_BASE_URL  = "http://localhost:11434"
OLLAMA_NUM_CTX           = 16384         # Ollama silently truncates prompts beyond this
OLLAMA_TIMEOUT_SECONDS   = 300
