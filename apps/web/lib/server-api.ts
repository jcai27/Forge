import { cookies } from "next/headers";

import { DEV_AUTH_HEADER, type DevAuthRole } from "@/lib/dev-auth";

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

type ServerApiRequestInit = RequestInit & {
  devAuthRole?: DevAuthRole;
};

async function parseResponseBody<T>(response: Response): Promise<T | null> {
  const text = await response.text();
  if (!text.trim()) return null;
  const contentType = response.headers.get("content-type") ?? "";
  const looksJson = contentType.includes("application/json") || text.trim().startsWith("{") || text.trim().startsWith("[");
  if (!looksJson) {
    throw new Error(text);
  }
  return JSON.parse(text) as T;
}

export async function serverApiFetch<T>(path: string, init?: ServerApiRequestInit): Promise<T | null> {
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((entry) => `${encodeURIComponent(entry.name)}=${encodeURIComponent(entry.value)}`)
      .join("; ");

    const requestInit = init;
    const { devAuthRole, ...fetchInit } = requestInit ?? {};
    const headers = new Headers(fetchInit.headers ?? {});
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (cookieHeader) {
      headers.set("Cookie", cookieHeader);
    }
    if (devAuthRole && !headers.has(DEV_AUTH_HEADER)) {
      headers.set(DEV_AUTH_HEADER, devAuthRole);
    }

    const response = await fetch(`${resolveServerApiBase()}${path}`, {
      cache: "no-store",
      ...fetchInit,
      headers,
    });

    if (!response.ok) {
      return null;
    }

    return await parseResponseBody<T>(response);
  } catch {
    return null;
  }
}
