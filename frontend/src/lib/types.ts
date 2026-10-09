// Shared types used across UI components and the API layer.

export interface Message {
  id: string;
  role: "assistant" | "user";
  content: string;
  /** Server-issued ID for locally stored answer feedback. */
  feedbackId?: string;
  feedbackUnavailable?: boolean;
  /** ISO timestamp — populated by the backend or set client-side as fallback */
  timestamp?: string;
  /** Source references returned by the RAG backend (assistant messages only) */
  sources?: Source[];
  /** Clarification prompt when the query was ambiguous (assistant messages only) */
  clarification?: Clarification;
}

// ── Source reference (from Nahom's chunk metadata format) ───────────────────

export interface Source {
  id: number;
  file: string;
  page: number;       // 1-indexed
  snippet: string;
  full_snippet?: string;
}

export interface ClarificationOption {
  label: string;   // human-readable, e.g. "SOP-001 Assembly Line Startup"
  value: string;   // filename or "__all__"
}

export interface Clarification {
  question: string;
  options: ClarificationOption[];
}

// ── Request / Response shapes sent to/from the Flask backend ────────────────

/** POST /api/chat  →  Flask */
export interface ChatRequest {
  message: string;
  /**
   * Full conversation history (oldest first, newest last, excluding the
   * message above). Send to give the model conversation context.
   * Omit or send [] for single-turn mode.
   */
  history: Pick<Message, "role" | "content">[];
  /** Optional: session / thread ID for stateful backends */
  session_id?: string;
}

/** Flask /chat response body */
export interface ChatResponse {
  reply: string;
  message_id?: string;
  feedback_unavailable?: boolean;
  /** Backend echoes or assigns a session ID */
  session_id?: string;
  /** Metadata including source references */
  metadata?: {
    sources?: Source[];
    clarification?: Clarification;
    [key: string]: unknown;
  };
}

// ── Document management ──────────────────────────────────────────────────────

export interface Document {
  filename: string;
  chunks: number;
  uploaded_at: string;
}

export interface DocumentsResponse {
  documents: Document[];
}

export interface UploadResponse {
  success: boolean;
  message: string;
  filename?: string;
  chunks?: number;
}

export interface DeleteResponse {
  success: boolean;
  message: string;
}
