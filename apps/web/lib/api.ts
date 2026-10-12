import { useQuery } from '@tanstack/react-query';
import type { Collection } from '../../../packages/contracts/src';
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';
/** The customer platform lives under this address and nowhere else. */
export const PORTAL = '/portal';
export const inPortal = () => typeof window !== 'undefined' && (window.location.pathname === PORTAL || window.location.pathname.startsWith(PORTAL + '/'));
/** The two sides keep separate sessions: signing in to one, or opening a customer from the builder, leaves the other as it was. */
export const sessionKey = () => inPortal() ? 'portal-token' : 'factory-token';
export function token() { return typeof window === 'undefined' ? '' : localStorage.getItem(sessionKey()) ?? ''; }
export async function api<T>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  // A FormData body is a file upload: the browser sets its own multipart content type.
  const form = typeof FormData !== 'undefined' && body instanceof FormData;
  const response = await fetch(API_URL + path, {method, headers: {...(form ? {} : {'Content-Type': 'application/json'}), Authorization: `Bearer ${token()}`}, ...(body === undefined ? {} : {body: form ? body : JSON.stringify(body)})});
  if(response.status===204)return undefined as T;
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message ?? `Request failed (${response.status})`);
  return data as T;
}
export function useResource<T>(path: string, enabled = true, poll = 0) {
  return useQuery<T, Error>({queryKey: [path], queryFn: () => api<T>(path), enabled: enabled && !!path, refetchInterval: poll || false});
}
export function useCollection<T>(path: string, enabled = true, poll = 0) {return useResource<Collection<T>>(path, enabled, poll);}
export const percent = (value: number | undefined) => value === undefined ? '—' : `${Math.round(value * 100)}%`;
export const money = (value: number = 0) => `$${value.toFixed(3)}`;
