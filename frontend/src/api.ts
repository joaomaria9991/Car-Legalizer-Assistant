import type { ProcessDocumentsResponse, ProcessListResponse, ProcessResponse, ProcessState } from "./types";

const DEFAULT_API_BASE = "http://localhost:8000";
let accessTokenProvider: (() => Promise<string | null>) | null = null;
let cachedAccessToken: string | null = null;

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  DEFAULT_API_BASE;

export function setAccessTokenProvider(provider: (() => Promise<string | null>) | null) {
  accessTokenProvider = provider;
}

export function setCachedAccessToken(token: string | null) {
  cachedAccessToken = token;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = accessTokenProvider ? await accessTokenProvider() : cachedAccessToken;
  if (token) {
    cachedAccessToken = token;
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function healthCheck(): Promise<boolean> {
  try {
    await requestJson(`${API_BASE_URL}/health`);
    return true;
  } catch {
    return false;
  }
}

export async function getProcess(processId: string): Promise<ProcessState> {
  return requestJson<ProcessState>(`${API_BASE_URL}/processes/${encodeURIComponent(processId)}`);
}

export async function listProcesses(): Promise<ProcessListResponse> {
  return requestJson<ProcessListResponse>(`${API_BASE_URL}/processes`);
}

export async function listProcessDocuments(processId: string): Promise<ProcessDocumentsResponse> {
  return requestJson<ProcessDocumentsResponse>(`${API_BASE_URL}/processes/${encodeURIComponent(processId)}/documents`);
}

export function documentFileUrl(processId: string, blobPath: string): string {
  const params = new URLSearchParams({ blob_path: blobPath });
  if (cachedAccessToken) {
    params.set("access_token", cachedAccessToken);
  }
  return `${API_BASE_URL}/processes/${encodeURIComponent(processId)}/documents/file?${params.toString()}`;
}

export async function postEvent(
  processId: string,
  event: Record<string, unknown>,
  file?: File,
): Promise<ProcessResponse> {
  const form = new FormData();
  form.append("event_json", JSON.stringify(event));
  if (file) {
    form.append("file", file);
  }

  return requestJson<ProcessResponse>(
    `${API_BASE_URL}/processes/${encodeURIComponent(processId)}/events`,
    {
      method: "POST",
      body: form,
    },
  );
}
