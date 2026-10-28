"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { Document } from "@/lib/types";
import { listDocuments, uploadDocument, deleteDocument } from "@/lib/documentApi";

const ALLOWED_EXT = new Set([".pdf", ".txt", ".md", ".json", ".docx", ".csv", ".tsv", ".html", ".htm"]);

export default function DocumentBubble() {

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
      fetchDocuments();
    }, [fetchDocuments]);
  
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
  
    const isBusy = uploadSource !== null || deletingFile !== null;

    return (
      <section
        aria-label="Manage documents"
        className={`mx-auto flex w-full max-w-6xl flex-col gap-6 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-8 ${isDragOver ? "ring-2 ring-blue-400" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!isBusy) handleDragOver(event);
        }}
        onDragLeave={handleDragLeave}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragOver(false);
          if (!isBusy) handleDrop(event);
        }}
      >
        <h2 className="text-lg font-semibold text-[#1a202c]">Manage Documents</h2>

        <input
          ref={fileInputRef}
          type="file"
          accept={Array.from(ALLOWED_EXT).join(",")}
          multiple
          disabled={isBusy}
          className="hidden"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (files.length === 1) void handleUpload(files[0]);
            else if (files.length > 1) void uploadFiles(files, "files");
          }}
        />
        <input
          ref={folderInputRef}
          type="file"
          /* @ts-expect-error webkitdirectory is not in React's types */
          webkitdirectory=""
          multiple
          disabled={isBusy}
          className="hidden"
          onChange={handleFolderInputChange}
        />

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isBusy}
              className="flex items-center justify-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-3 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploadSource === "files" ? <SpinnerIcon className="h-4 w-4 shrink-0 animate-spin" /> : <UploadIcon className="h-4 w-4 shrink-0" />}
              {uploadSource === "files" ? "Uploading..." : "Upload File"}
            </button>
            <button
              type="button"
              onClick={() => folderInputRef.current?.click()}
              disabled={isBusy}
              className="flex items-center justify-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-3 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploadSource === "folder" ? <SpinnerIcon className="h-4 w-4 shrink-0 animate-spin" /> : <FolderIcon className="h-4 w-4 shrink-0" />}
              {uploadSource === "folder" ? "Uploading..." : "Upload Folder"}
            </button>
          </div>
          <p className="text-sm leading-relaxed text-gray-500">
            {isDragOver ? "Drop files or a folder here." : "Choose files or drag them here. Folder uploads include only top-level files."}
          </p>
          <p className="text-xs text-gray-500">Supported: PDF, TXT, MD, JSON, DOCX, CSV, TSV, HTML.</p>
        </div>

        {folderProgress && (
          <div className="space-y-2">
            <p role="status" className="text-sm text-blue-700">Uploading {folderProgress.current} of {folderProgress.total} files...</p>
            <progress aria-label="Upload progress" value={folderProgress.current} max={folderProgress.total} className="h-2 w-full accent-blue-500" />
          </div>
        )}
        {error && <p role="alert" className="whitespace-pre-line rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 [overflow-wrap:anywhere]">{error}</p>}
        {successMsg && <p role="status" className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 [overflow-wrap:anywhere]">{successMsg}</p>}

        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-[#2d3748]">Uploaded documents{!isLoading && ` (${documents.length})`}</h3>
          {isLoading ? (
            <p role="status" className="flex items-center gap-2 py-4 text-sm text-gray-600"><SpinnerIcon className="h-4 w-4 animate-spin" />Loading documents...</p>
          ) : documents.length === 0 ? (
            !error && <p className="rounded-lg border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">No documents yet. Upload a file or folder to get started.</p>
          ) : (
            <ul className="space-y-4">
              {documents.map((doc) => (
                <li key={doc.filename} className="flex items-center gap-3 rounded-lg border border-gray-200 p-4 sm:gap-6 sm:p-5">
                  <FileIcon className="h-5 w-5 shrink-0 text-gray-400" />
                  <div className="min-w-0 flex-1">
                    <p title={doc.filename} className="truncate font-medium text-[#1a202c]">{doc.filename}</p>
                    <p className="mt-1 text-xs text-gray-500">{doc.chunks} chunks</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => { void handleDelete(doc.filename); }}
                    disabled={isBusy}
                    aria-label={`Delete ${doc.filename}`}
                    className="flex shrink-0 items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500 disabled:cursor-not-allowed disabled:opacity-50 sm:px-4"
                  >
                    {deletingFile === doc.filename ? <SpinnerIcon className="h-4 w-4 animate-spin" /> : <TrashIcon className="h-4 w-4" />}
                    {deletingFile === doc.filename ? "Deleting..." : "Delete"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
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
