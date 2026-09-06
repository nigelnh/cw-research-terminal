import { useEffect, useRef, useState } from "react";
import { config } from "@/config";
import { getAccessToken } from "@/data/backend/backend_client";

export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;
export const ATTACHMENT_ACCEPT = ".pdf,.txt,.md,.csv,.tsv,.json,.xlsx,.docx";
const extensions = new Set(ATTACHMENT_ACCEPT.split(","));
const localPreviewUrl = import.meta.env.DEV ? import.meta.env.VITE_DOCUMENT_PREVIEW_URL : undefined;
const endpoint = `${(localPreviewUrl || config.apiUrl || "").replace(/\/$/, "")}/api/ai/files/extract`;

export interface FilePreview {
  name: string;
  characters: number;
  warnings: string[];
  sections: { location: string; text: string }[];
}

export function attachmentError(files: readonly File[]): string | null {
  if (files.length > 2) return "Attach up to 2 files.";
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_ATTACHMENT_BYTES) return "Files must total 20 MB or less.";
  if (new Set(files.map(file => file.name)).size !== files.length) return "This filename is already attached. Rename it or remove the earlier file.";
  for (const file of files) {
    if (!extensions.has(`.${file.name.split(".").pop()?.toLowerCase()}`)) return "Use PDF, TXT, MD, CSV, TSV, JSON, XLSX or DOCX files.";
    if (!file.size) return `${file.name}: the file is empty.`;
  }
  return null;
}

/** File bytes and extracted text stay in memory and never enter the AI chat request. */
export function useFileAttachments(conversationId: string | null | undefined) {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<FilePreview[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const request = useRef<AbortController | null>(null);
  const currentFiles = useRef<File[]>([]);

  useEffect(() => {
    request.current?.abort();
    request.current = null;
    currentFiles.current = [];
    setFiles([]);
    setPreviews([]);
    setError(null);
    setReading(false);
    return () => { request.current?.abort(); request.current = null; };
  }, [conversationId]);

  const read = async (next: File[]) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    currentFiles.current = next;
    setFiles(next);
    setPreviews([]);
    setError(null);
    setReading(next.length > 0);
    if (!next.length) return;
    try {
      const body = new FormData();
      next.forEach(file => body.append("files", file));
      // Same AI rate-limit tier as /api/ai/chat - carry the bearer token when signed in
      // so the upload counts against the caller's account, not the per-IP guest bucket.
      const token = await getAccessToken();
      const response = await fetch(endpoint, {
        method: "POST",
        body,
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal: controller.signal,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Could not read these files. Please try again.");
      if (!Array.isArray(result.files)) throw new Error("The file preview service returned an invalid response.");
      if (request.current === controller) setPreviews(result.files);
    } catch (err) {
      if (request.current === controller && !controller.signal.aborted) setError(err instanceof TypeError ? "Could not reach the file preview service." : err instanceof Error ? err.message : "Could not read these files.");
    } finally {
      if (request.current === controller) setReading(false);
    }
  };

  return {
    files, previews, error, reading,
    add: (selected: File[]) => {
      const next = [...currentFiles.current, ...selected];
      const problem = attachmentError(next);
      if (problem) { setError(problem); return; }
      void read(next);
    },
    remove: (name: string) => { void read(currentFiles.current.filter(file => file.name !== name)); },
    retry: () => { void read(currentFiles.current); },
  };
}
