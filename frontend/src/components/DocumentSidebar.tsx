"use client";

/**
 * DocumentSidebar — slide-in panel for managing the RAG knowledge base.
 *
 * Features:
 *  • List all ingested documents with chunk counts
 *  • Upload one or more files at once (click)
 *  • Upload a folder (click or drag-and-drop) — top-level files only
 *  • Delete a document with confirmation
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type { Document } from "@/lib/types";
import { listDocuments, uploadDocument, deleteDocument } from "@/lib/documentApi";

const ALLOWED_EXT = new Set([".pdf", ".txt", ".md", ".json", ".docx", ".csv", ".tsv", ".html", ".htm"]);

interface DocumentSidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function DocumentSidebar({ isOpen, onClose }: DocumentSidebarProps) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [uploadSource, setUploadSource] = useState<"files" | "folder" | null>(null);
  const [folderProgress, setFolderProgress] = useState<{ current: number; total: number } | null>(null);
  const [deletingFile, setDeletingFile] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const docs = await listDocuments();
      setDocuments(docs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) fetchDocuments();
  }, [isOpen, fetchDocuments]);

  const handleUpload = async (file: File) => {
    if (!ALLOWED_EXT.has(getExt(file.name))) {
      setError("Unsupported file type. Allowed: PDF, TXT, MD, JSON, DOCX, CSV, TSV, HTML.");
      return;
    }
    setUploadSource("files");
    setError(null);
    setSuccessMsg(null);
    try {
      const result = await uploadDocument(file);
      setSuccessMsg(`"${result.filename}" uploaded — ${result.chunks} chunks indexed.`);
      await fetchDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploadSource(null);
    }
  };

  const uploadFiles = useCallback(async (files: File[], source: "files" | "folder" = "folder") => {
    const supported = files.filter((f) => ALLOWED_EXT.has(getExt(f.name)));
    const skipped = files.length - supported.length;

    if (supported.length === 0) {
      setError("No supported files found in the folder.");
      return;
    }

    setUploadSource(source);
    setError(null);
    setSuccessMsg(null);
    setFolderProgress({ current: 0, total: supported.length });

    let uploaded = 0;
    const failedFiles: { name: string; reason: string }[] = [];

    for (const file of supported) {
      try {
        await uploadDocument(file);
        uploaded++;
      } catch (err) {
        failedFiles.push({
          name: file.name,
          reason: err instanceof Error ? err.message : "Unknown error",
        });
      }
      setFolderProgress({ current: uploaded + failedFiles.length, total: supported.length });
    }

    await fetchDocuments();
    setFolderProgress(null);
    setUploadSource(null);

    const parts: string[] = [];
    if (uploaded > 0) parts.push(`${uploaded} file${uploaded !== 1 ? "s" : ""} uploaded`);
    if (skipped > 0) parts.push(`${skipped} skipped (unsupported type)`);
    if (parts.length > 0) setSuccessMsg(parts.join(", ") + ".");

    if (failedFiles.length > 0) {
      const details = failedFiles.map((f) => `• ${f.name}: ${f.reason}`).join("\n");
      setError(`${failedFiles.length} file${failedFiles.length !== 1 ? "s" : ""} failed:\n${details}`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchDocuments]);

  const handleFolderInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    // webkitRelativePath format: "folderName/file.ext" — filter to top-level only
    const topLevel = files.filter((f) => f.webkitRelativePath.split("/").length === 2);
    e.target.value = "";
    if (topLevel.length > 0) uploadFiles(topLevel, "folder");
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);

    const items = Array.from(e.dataTransfer.items);
    const collectedFiles: File[] = [];
    let pending = 0;

    const tryFinish = () => {
      if (pending === 0 && collectedFiles.length > 0) {
        uploadFiles(collectedFiles, "folder");
      } else if (pending === 0) {
        setError("No files found in the dropped folder.");
      }
    };

    for (const item of items) {
      const entry = item.webkitGetAsEntry?.();
      if (!entry) continue;

      if (entry.isDirectory) {
        pending++;
        (entry as FileSystemDirectoryEntry).createReader().readEntries((entries) => {
          for (const child of entries) {
            if (!child.isDirectory) {
              pending++;
              (child as FileSystemFileEntry).file((file) => {
                collectedFiles.push(file);
                pending--;
                tryFinish();
              });
            }
          }
          pending--;
          tryFinish();
        });
      } else if (entry.isFile) {
        pending++;
        (entry as FileSystemFileEntry).file((file) => {
          collectedFiles.push(file);
          pending--;
          tryFinish();
        });
      }
    }

    if (pending === 0) tryFinish();
  };

  const handleDelete = async (filename: string) => {
    setDeletingFile(filename);
    setError(null);
    setSuccessMsg(null);
    try {
      await deleteDocument(filename);
      setSuccessMsg(`"${filename}" removed from knowledge base.`);
      await fetchDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    } finally {
      setDeletingFile(null);
    }
  };

  const isBusy = uploadSource !== null;

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`fixed top-0 left-0 h-full w-72 bg-card shadow-xl z-50 flex flex-col overflow-hidden transition-transform duration-300 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        } ${isDragOver ? "ring-2 ring-inset ring-purple-400" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ background: "linear-gradient(135deg, #a855f7 0%, #3b82f6 100%)" }}
        >
          <span className="text-white font-semibold text-sm">Knowledge Base</span>
          <button
            onClick={onClose}
            className="text-white/80 hover:text-white transition-colors"
            aria-label="Close sidebar"
          >
            <XIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Upload area */}
        <div className="px-4 py-3 border-b border-border flex flex-col gap-2">
          {/* Hidden multi-file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.md,.json,.docx,.csv,.tsv,.html,.htm"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length === 1) handleUpload(files[0]);
              else if (files.length > 1) uploadFiles(files, "files");
              e.target.value = "";
            }}
          />
          {/* Hidden folder input */}
          <input
            ref={folderInputRef}
            type="file"
            /* @ts-expect-error webkitdirectory is not in React's types */
            webkitdirectory=""
            multiple
            className="hidden"
            onChange={handleFolderInputChange}
          />

          {/* Multi-file button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isBusy}
            className="w-full flex items-center justify-center gap-2 rounded-lg border-2 border-dashed border-purple-300 px-3 py-2.5 text-sm text-purple-600 hover:bg-purple-50 disabled:opacity-50 transition-colors dark:border-purple-800 dark:text-purple-300 dark:hover:bg-purple-950"
          >
            {uploadSource === "files" ? (
              <>
                <SpinnerIcon className="w-4 h-4 animate-spin" />
                {folderProgress !== null
                  ? `Uploading ${folderProgress.current} / ${folderProgress.total}…`
                  : "Uploading…"}
              </>
            ) : (
              <>
                <UploadIcon className="w-4 h-4" /> Upload Files
              </>
            )}
          </button>

          {/* Folder button */}
          <button
            onClick={() => folderInputRef.current?.click()}
            disabled={isBusy}
            className="w-full flex items-center justify-center gap-2 rounded-lg border-2 border-dashed border-blue-button-outline-border px-3 py-2.5 text-sm text-blue-button-outline-text hover:bg-blue-button-outline-hover disabled:opacity-50 transition-colors"
          >
            {uploadSource === "folder" && folderProgress !== null ? (
              <>
                <SpinnerIcon className="w-4 h-4 animate-spin" />
                Uploading {folderProgress.current} / {folderProgress.total}…
              </>
            ) : (
              <>
                <FolderIcon className="w-4 h-4" /> Upload Folder
              </>
            )}
          </button>

          {isDragOver && (
            <p className="text-center text-xs text-purple-500 font-medium animate-pulse">
              Drop folder here
            </p>
          )}
        </div>

        {/* Status messages */}
        {(error || successMsg) && (
          <div className="px-4 py-2">
            {error && (
              <p className="text-xs text-red-600 bg-red-50 rounded px-2 py-1 wrap-break-word whitespace-pre-line dark:text-red-300 dark:bg-red-950">{error}</p>
            )}
            {successMsg && (
              <p className="text-xs text-green-700 bg-green-50 rounded px-2 py-1 wrap-break-word dark:text-green-300 dark:bg-green-950">{successMsg}</p>
            )}
          </div>
        )}

        {/* Document list */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <SpinnerIcon className="w-5 h-5 animate-spin text-purple-500" />
            </div>
          ) : documents.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-8">
              No documents yet. Upload a file to get started.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {documents.map((doc) => (
                <li
                  key={doc.filename}
                  className="flex items-start gap-2 rounded-lg border border-border bg-muted px-3 py-2"
                >
                  <FileIcon className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-foreground truncate" title={doc.filename}>{doc.filename}</p>
                    <p className="text-[10px] text-muted-foreground">{doc.chunks} chunks</p>
                  </div>
                  <button
                    onClick={() => handleDelete(doc.filename)}
                    disabled={deletingFile === doc.filename}
                    className="shrink-0 text-muted-foreground hover:text-red-400 disabled:opacity-40 transition-colors"
                    aria-label={`Delete ${doc.filename}`}
                  >
                    {deletingFile === doc.filename ? (
                      <SpinnerIcon className="w-4 h-4 animate-spin" />
                    ) : (
                      <TrashIcon className="w-4 h-4" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getExt(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx === -1 ? "" : filename.slice(idx).toLowerCase();
}

// ─── Icons ────────────────────────────────────────────────────────────────────

function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}
function UploadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 16 12 12 8 16" /><line x1="12" y1="12" x2="12" y2="21" />
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
    </svg>
  );
}
function FileIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}
function TrashIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v6m4-6v6" /><path d="M9 6V4h6v2" />
    </svg>
  );
}
function SpinnerIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M12 2a10 10 0 0 1 10 10" />
    </svg>
  );
}
function FolderIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  );
}

