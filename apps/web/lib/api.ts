import { DEV_AUTH_HEADER, inferDevAuthRole, type DevAuthRole } from "@/lib/dev-auth";

function normalizeApiBase(url: string) {
  return url.endsWith("/api") ? url : `${url.replace(/\/$/, "")}/api`;
}

function resolveServerApiBase() {
  if (process.env.API_PROXY_TARGET) {
    return normalizeApiBase(process.env.API_PROXY_TARGET);
  }

  const publicBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (publicBaseUrl && /^https?:\/\//.test(publicBaseUrl)) {
    return normalizeApiBase(publicBaseUrl);
  }

  return normalizeApiBase("http://127.0.0.1:8000");
}

const clientBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";
const serverBaseUrl = resolveServerApiBase();

function resolvedBaseUrl() {
  return typeof window === "undefined" ? serverBaseUrl : clientBaseUrl;
}

export const apiOrigin = clientBaseUrl.replace(/\/api$/, "");

function readCookie(name: string) {
  if (typeof document === "undefined") return null;
  const prefix = `${encodeURIComponent(name)}=`;
  for (const item of document.cookie.split(";")) {
    const trimmed = item.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return null;
}

function buildHeaders(init?: RequestInit, authRole?: DevAuthRole | null) {
  const headers = new Headers(init?.headers ?? {});
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (typeof window !== "undefined" && !["GET", "HEAD", "OPTIONS"].includes((init?.method ?? "GET").toUpperCase())) {
    const csrf = readCookie("forge_csrf");
    if (csrf && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRF-Token", csrf);
    }
  }
  const inferredRole = authRole ?? (typeof window !== "undefined" ? inferDevAuthRole(window.location.pathname) : null);
  if (inferredRole && !headers.has(DEV_AUTH_HEADER)) {
    headers.set(DEV_AUTH_HEADER, inferredRole);
  }
  return headers;
}

async function parseResponseBody<T>(response: Response): Promise<T | null> {
  const text = await response.text();
  if (!text.trim()) {
    return null;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const looksJson = contentType.includes("application/json") || text.trim().startsWith("{") || text.trim().startsWith("[");
  if (!looksJson) {
    throw new Error(text);
  }

  return JSON.parse(text) as T;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const requestInit = init ?? {};
    const response = await fetch(`${resolvedBaseUrl()}${path}`, {
      cache: "no-store",
      credentials: "include",
      ...requestInit,
      headers: buildHeaders(requestInit),
    });

    if (!response.ok) {
      return null;
    }

    return await parseResponseBody<T>(response);
  } catch {
    return null;
  }
}

export async function apiSend<T>(path: string, init?: RequestInit): Promise<T> {
  const requestInit = init ?? {};
  const response = await fetch(`${resolvedBaseUrl()}${path}`, {
    cache: "no-store",
    credentials: "include",
    ...requestInit,
    headers: buildHeaders(requestInit),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  const payload = await parseResponseBody<T>(response);
  return (payload ?? ({} as T)) as T;
}
