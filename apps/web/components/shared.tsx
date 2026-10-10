'use client';
import {createContext, useContext, useState} from 'react';
import type {ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {Inbox, LoaderCircle} from 'lucide-react';
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
const SETTLED = /completed|connected|ready|approved|deployed|passed|verified|promoted/i, STOPPED = /failed|rejected|cancelled|revoked|error/i, WAITING = /approval|paused|budget|attention|setup|pending|proposed/i;
export function tone(value: string) {return /^(not|no|un)[ _]?/i.test(value) ? 'neutral' : STOPPED.test(value) ? 'bad' : WAITING.test(value) ? 'warn' : SETTLED.test(value) ? 'good' : 'neutral';}
/** Field and event names arrive as snake_case identifiers; show them as words. */
export function humanize(value: string) {const text = value.replaceAll('_', ' ').trim(); return text ? text[0].toUpperCase() + text.slice(1) : text;}
/** State names are stored as UPPER_SNAKE identifiers; anything else is prose and is left alone. */
export function stateName(value: string) {return /^[A-Z][A-Z_]+$/.test(value) ? humanize(value.toLowerCase()) : value;}
// The text stays lowercase in the document (it is matched exactly elsewhere); CSS capitalizes the first letter.
export function Badge({value}: {value: string}) {return <span className={`badge ${tone(value)}`}>{value.replaceAll('_', ' ').toLowerCase()}</span>;}
export function Heading({title, subtitle, action, meta}: {title: string; subtitle?: string; action?: ReactNode; meta?: ReactNode}) {return <div className="page-heading"><div><h1>{title}</h1>{subtitle && <p className="subtitle">{subtitle}</p>}{meta && <div className="page-meta">{meta}</div>}</div>{action && <div className="page-actions">{action}</div>}</div>;}
export function Kpis({items}: {items: {label: string; value: ReactNode; foot?: ReactNode; icon?: ReactNode; attention?: boolean; text?: boolean}[]}) {return <div className={`kpis ${items.length === 3 ? 'cols-3' : ''}`}>{items.map(item => <div className={`kpi ${item.attention ? 'attention' : ''}`} key={item.label}><div className="kpi-label">{item.icon}{item.label}</div><div className={`kpi-value ${item.text ? 'text' : ''}`}>{item.value}</div>{item.foot && <div className="kpi-foot">{item.foot}</div>}</div>)}</div>;}
export function Empty({title, children}: {title: string; children?: ReactNode}) {return <div className="empty"><Inbox size={22}/><h3>{title}</h3><p className="small">{children}</p></div>;}
export function Loading() {return <div className="loading row"><LoaderCircle size={17} className="animate-spin"/> Loading…</div>;}
export function ErrorState({error}: {error: Error | null}) {return error ? <div className="error" role="alert">{error.message}</div> : null;}
export function JsonView({value}: {value: unknown}) {return <pre className="code">{JSON.stringify(value, null, 2)}</pre>;}
export function Card({children, className=''}: {children: ReactNode; className?: string}) {return <div className={`card ${className}`}>{children}</div>;}
