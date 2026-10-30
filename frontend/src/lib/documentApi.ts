import { tabFetch } from "./tabSession";

/**
 * documentApi.ts — client for the Flask document-management endpoints.
 *
 * Endpoints proxied through Next.js /api/documents/* routes, or called
 * directly as same-origin paths if you add rewrite rules in next.config.ts.
 *
 * For simplicity these calls go directly to the Flask backend via the
 * Next.js proxy routes defined alongside /api/chat.
 */

import type {
  Document,
  DocumentsResponse,
  UploadResponse,
  DeleteResponse,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/** Fetch the list of ingested documents from the knowledge base. */
export async function listDocuments(): Promise<Document[]> {
  const res = await tabFetch(`${API_BASE}/api/documents`);
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Failed to list documents (${res.status}): ${text}`);
  }
  const data: DocumentsResponse = await res.json();
  return data.documents;
}

/**
 * Upload a PDF file to the knowledge base.
 * The backend ingests, chunks, embeds, and stores the document.
 */
export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await tabFetch(`${API_BASE}/api/documents/upload`, {
    method: "POST",
    body: form,
  });

  const data: UploadResponse = await res.json();
  if (!res.ok) {
    throw new Error(data.message ?? `Upload failed (${res.status})`);
  }
  return data;
}

/** Delete a document from the knowledge base by filename. */
export async function deleteDocument(filename: string): Promise<DeleteResponse> {
  const encoded = encodeURIComponent(filename);
  const res = await tabFetch(`${API_BASE}/api/documents/${encoded}`, {
    method: "DELETE",
  });

  const data: DeleteResponse = await res.json();
  if (!res.ok) {
    throw new Error(data.message ?? `Delete failed (${res.status})`);
  }
  return data;
}

