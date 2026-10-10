'use client';
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {QueryClient, QueryClientProvider, useQueryClient} from '@tanstack/react-query';
import {Boxes, LayoutDashboard, Bot, Plug, ShieldCheck, Settings, Plus, LogOut} from 'lucide-react';
import type {Me} from '../../../packages/contracts/src';
import {api, useResource} from '@/lib/api';
import {Button} from './ui/button';
import {ToastContext, Loading} from './shared';
import {Dashboard, NewAgent} from './workspace-pages';
import {AgentWorkspace} from './agent-pages';
import {Integrations, Approvals, RunDetail, SettingsPage} from './operations-pages';

export function FactoryApp() {const [client] = useState(() => new QueryClient({defaultOptions: {queries: {retry: 1, staleTime: 1000}}})); return <QueryClientProvider client={client}><Session/></QueryClientProvider>;}
function Session() {
  const cache=useQueryClient();
  const [ready, setReady] = useState(false), [authenticated, setAuthenticated] = useState(false), [toast, setToast] = useState('');
  const cachePath = usePathname();
  useEffect(() => {setAuthenticated(!!localStorage.getItem('factory-token')); setReady(true);}, []);
  useEffect(() => {if (!toast) return; const timer = setTimeout(() => setToast(''), 6000); return () => clearTimeout(timer);}, [toast]);
  if (!ready) return <Loading/>;
  return <ToastContext.Provider value={setToast}>{authenticated ? <Workspace path={cachePath} logout={() => {localStorage.removeItem('factory-token');cache.clear();setAuthenticated(false);}}/> : <Login onLogin={() => {cache.clear();setAuthenticated(true);}}/>} {toast && <div className="toast" role="alert">{toast}</div>}</ToastContext.Provider>;
}
function Login({onLogin}: {onLogin: () => void}) {
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [organization, setOrganization] = useState(''), [register, setRegister] = useState(false), [error, setError] = useState(''), [pending, setPending] = useState(false);
  async function login(demo = false) {setPending(true); setError(''); try {const result = await api<{token: string}>(demo ? '/auth/demo' : register ? '/auth/register' : '/auth/login', demo ? {} : register ? {email, password, organization} : {email, password}); localStorage.setItem('factory-token', result.token); onLogin();} catch(e) {setError(e instanceof Error ? e.message : 'Sign in failed');} finally {setPending(false);}}
  return <div className="login"><div className="card login-card"><div className="brand"><span className="brand-icon"><Boxes size={21}/></span>Agent Factory</div><h1>{register ? 'Create your workspace' : 'Welcome to the factory'}</h1><p className="muted small">Turn business processes into agents you can test, trust and deploy.</p><div className="separator"/>{error && <div role="alert" className="error">{error}</div>}<form onSubmit={e => {e.preventDefault(); void login();}}><div className="field"><label htmlFor="email">Email</label><input id="email" className="input" type="email" required value={email} onChange={e => setEmail(e.target.value)}/></div><div className="field"><label htmlFor="password">Password</label><input id="password" className="input" type="password" required minLength={register ? 10 : 1} value={password} onChange={e => setPassword(e.target.value)}/></div>{register && <div className="field"><label htmlFor="organization">Organization name</label><input id="organization" className="input" required value={organization} onChange={e => setOrganization(e.target.value)}/></div>}<Button className="full" disabled={pending}>{pending ? 'Connecting…' : register ? 'Create workspace' : 'Sign in'}</Button></form><Button variant="ghost" className="full" onClick={() => setRegister(!register)}>{register ? 'Already have an account? Sign in' : 'Create an account'}</Button><div className="separator"/><Button variant="secondary" className="full" disabled={pending} onClick={() => void login(true)}>Open local demo workspace</Button><p className="help">Local development only. Fictional business data and explicitly labeled deterministic execution.</p></div></div>;
}
function Workspace({path, logout}: {path: string; logout: () => void}) {
  const me = useResource<Me>('/auth/me');
  const nav = [{href:'/dashboard', label:'Overview', icon:LayoutDashboard}, {href:'/agents/new', label:'Create agent', icon:Plus}, {href:'/integrations', label:'Integrations', icon:Plug}, {href:'/approvals', label:'Approvals', icon:ShieldCheck}, {href:'/settings', label:'Settings', icon:Settings}];
  const parts = path.split('/').filter(Boolean);
  let page;
  if (parts[0] === 'agents' && parts[1] === 'new') page = <NewAgent/>;
  else if (parts[0] === 'agents' && parts[1]) page = <AgentWorkspace id={parts[1]} section={parts[2] ?? 'overview'}/>;
  else if (parts[0] === 'integrations') page = <Integrations/>;
  else if (parts[0] === 'approvals') page = <Approvals/>;
  else if (parts[0] === 'settings') page = <SettingsPage/>;
  else if (parts[0] === 'runs' && parts[1]) page = <RunDetail id={parts[1]}/>;
  else if (parts.length === 0 || parts[0] === 'dashboard') page = <Dashboard/>;
  else page = <div className="card"><h1>Page not found</h1><Link className="link" href="/dashboard">Return to dashboard</Link></div>;
  return <div className="shell"><aside className="sidebar"><Link href="/dashboard" className="brand"><span className="brand-icon"><Boxes size={21}/></span>Agent Factory</Link><div className="nav-label">Workspace</div>{nav.map(item => <Link key={item.href} className={`nav-link ${path === item.href || (item.href === '/dashboard' && path === '/') ? 'active' : ''}`} href={item.href}><item.icon size={17}/>{item.label}</Link>)}<div className="nav-label">Your factory</div><Link className={`nav-link ${parts[0] === 'agents' && parts[1] !== 'new' ? 'active' : ''}`} href="/dashboard"><Bot size={17}/>Agent library</Link><div className="sidebar-bottom"><div className="row"><span className="avatar">{me.data?.organization.name.slice(0,2).toUpperCase() ?? 'AF'}</span><div><div style={{color:'#d1d6e5'}}>{me.data?.organization.name ?? 'Workspace'}</div><div className="small muted">{me.data?.role ?? 'Connecting'}</div></div></div></div></aside><div className="workspace"><header className="topbar"><span className="crumb">Workspace <span style={{margin:'0 10px',color:'#c5c8d1'}}>/</span> {parts[0] === 'agents' ? 'Agent workspace' : parts[0] ? parts[0][0].toUpperCase()+parts[0].slice(1) : 'Overview'}</span><div className="topbar-right"><span className="mode"><span className="dot"/>{me.data?.execution_mode === 'live' ? 'Live model runtime' : 'Deterministic demo mode'}</span><span className="avatar">AF</span><Button variant="ghost" aria-label="Sign out" onClick={logout}><LogOut size={15}/></Button></div></header><main className="content">{me.error ? <div className="error">{me.error.message} <Button variant="secondary" onClick={logout}>Sign in again</Button></div> : page}</main></div></div>;
}
