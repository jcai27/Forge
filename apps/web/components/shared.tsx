'use client';
import {createContext, useContext, useState} from 'react';
import type {ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {Activity, LoaderCircle} from 'lucide-react';
import {api} from '@/lib/api';
export const ToastContext = createContext<(message: string) => void>(() => {});
export function useAction() {
  const [pending, setPending] = useState(false);
  const toast = useContext(ToastContext);
  const cache = useQueryClient();
  async function act<T>(path: string, body?: unknown, method?: string): Promise<T | undefined> {
    setPending(true);
    try {const value = await api<T>(path, body, method); await cache.invalidateQueries(); return value;}
    catch(error) {toast(error instanceof Error ? error.message : 'Operation failed'); return undefined;}
    finally {setPending(false);}
  }
  return {act, pending, toast};
}
export function Badge({value}: {value: string}) {const text = value.replaceAll('_', ' '); const tone = /completed|connected|ready|approved|deployed|passed/i.test(value) ? 'good' : /failed|rejected|cancelled|revoked/i.test(value) ? 'bad' : /approval|paused|budget|attention|setup/i.test(value) ? 'warn' : 'neutral'; return <span className={`badge ${tone}`}>{text.toLowerCase()}</span>;}
export function Heading({title, subtitle, action}: {title: string; subtitle: string; action?: ReactNode}) {return <div className="page-heading"><div><div className="eyebrow">Operations, engineered</div><h1>{title}</h1><p className="muted small">{subtitle}</p></div>{action}</div>;}
export function Empty({title, children}: {title: string; children?: ReactNode}) {return <div className="empty"><Activity size={26}/><h3>{title}</h3><p className="small">{children}</p></div>;}
export function Loading() {return <div className="loading row"><LoaderCircle size={17} className="animate-spin"/> Loading workspace…</div>;}
export function ErrorState({error}: {error: Error | null}) {return error ? <div className="error" role="alert">{error.message}</div> : null;}
export function JsonView({value}: {value: unknown}) {return <pre className="code">{JSON.stringify(value, null, 2)}</pre>;}
export function Card({children, className=''}: {children: ReactNode; className?: string}) {return <div className={`card ${className}`}>{children}</div>;}
