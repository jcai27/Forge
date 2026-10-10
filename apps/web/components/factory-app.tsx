'use client';
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {QueryClient, QueryClientProvider, useQueryClient} from '@tanstack/react-query';
import {Boxes, LayoutDashboard, Plug, ShieldCheck, Settings, Plus, LogOut, CircleCheck} from 'lucide-react';
import type {Me, Agent, Metrics} from '../../../packages/contracts/src';
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
  return <div className="login">
    <aside className="login-aside">
      <div className="brand"><span className="brand-icon"><Boxes size={16}/></span>Agent Factory</div>
      <div>
        <h2>Agents you can measure before you trust them.</h2>
        <p>Build an agent for a business process, test it against real cases, and release it only when the evidence holds.</p>
        <ul className="login-points">
          <li><CircleCheck size={17}/>Every version is immutable and scored on held-out cases.</li>
          <li><CircleCheck size={17}/>Production writes wait for a named approver.</li>
          <li><CircleCheck size={17}/>Credentials are encrypted and never shown to a model.</li>
        </ul>
      </div>
      <div className="login-legal">Access is limited to invited workspace members.</div>
    </aside>
    <main className="login-main"><div className="login-card">
      <h1>{register ? 'Create your workspace' : 'Sign in'}</h1>
      <p className="muted small" style={{marginBottom:24}}>{register ? 'Set up an organization and its first administrator.' : 'Use your workspace account to continue.'}</p>
      {error && <div role="alert" className="error">{error}</div>}
      <form onSubmit={e => {e.preventDefault(); void login();}}>
        <div className="field"><label htmlFor="email">Email</label><input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)}/></div>
        <div className="field"><label htmlFor="password">Password</label><input id="password" className="input" type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={register ? 10 : 1} value={password} onChange={e => setPassword(e.target.value)}/></div>
        {register && <div className="field"><label htmlFor="organization">Organization name</label><input id="organization" className="input" required value={organization} onChange={e => setOrganization(e.target.value)}/></div>}
        <Button className="full" disabled={pending}>{pending ? 'Connecting…' : register ? 'Create workspace' : 'Sign in'}</Button>
      </form>
      <Button variant="ghost" className="full" style={{marginTop:8}} onClick={() => setRegister(!register)}>{register ? 'Already have an account? Sign in' : 'Create an account'}</Button>
      <div className="or">Local development</div>
      <Button variant="secondary" className="full" disabled={pending} onClick={() => void login(true)}>Open local demo workspace</Button>
      <p className="help">Fictional business data. Runs are deterministic and labeled as demo, never as live model execution.</p>
    </div></main>
  </div>;
}
const SECTIONS: Record<string, string> = {integrations:'Integrations', approvals:'Approvals', settings:'Settings', runs:'Executions', dashboard:'Overview'};
function initials(value: string) {return value.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() || '–';}
function Workspace({path, logout}: {path: string; logout: () => void}) {
  const me = useResource<Me>('/auth/me');
  const parts = path.split('/').filter(Boolean);
  const agentId = parts[0] === 'agents' && parts[1] && parts[1] !== 'new' ? parts[1] : '';
  const agent = useResource<Agent>(`/agents/${agentId}`, !!agentId), metrics = useResource<Metrics>('/metrics', false); // reads what the overview already fetched; a request of its own here exceeds the API request budget
  const waiting = metrics.data?.pending_approvals ?? 0, live = me.data?.execution_mode === 'live';
  const groups = [
    {label:'Build', items:[{href:'/dashboard', label:'Overview', icon:LayoutDashboard, active:parts.length === 0 || parts[0] === 'dashboard' || !!agentId || parts[0] === 'runs'}, {href:'/agents/new', label:'Create agent', icon:Plus, active:path === '/agents/new'}]},
    {label:'Operate', items:[{href:'/approvals', label:'Approvals', icon:ShieldCheck, active:parts[0] === 'approvals', count:waiting}, {href:'/integrations', label:'Integrations', icon:Plug, active:parts[0] === 'integrations'}]},
    {label:'Administration', items:[{href:'/settings', label:'Settings', icon:Settings, active:parts[0] === 'settings'}]},
  ];
  let page;
  if (parts[0] === 'agents' && parts[1] === 'new') page = <NewAgent/>;
  else if (agentId) page = <AgentWorkspace id={agentId} section={parts[2] ?? 'overview'}/>;
  else if (parts[0] === 'integrations') page = <Integrations/>;
  else if (parts[0] === 'approvals') page = <Approvals/>;
  else if (parts[0] === 'settings') page = <SettingsPage/>;
  else if (parts[0] === 'runs' && parts[1]) page = <RunDetail id={parts[1]}/>;
  else if (parts.length === 0 || parts[0] === 'dashboard') page = <Dashboard/>;
  else page = <div className="card"><h1>Page not found</h1><p className="muted small" style={{margin:'8px 0 16px'}}>The address does not match a page in this workspace.</p><Link className="link" href="/dashboard">Return to overview</Link></div>;
  // The current page is plain text, never a link, so navigation links keep unique names.
  const trail: {label: string; href?: string}[] = agentId ? [{label:'Agents', href:'/dashboard'}, {label:agent.data?.name ?? 'Agent', href:parts[2] ? `/agents/${agentId}` : undefined}, ...(parts[2] ? [{label:parts[2][0].toUpperCase() + parts[2].slice(1)}] : [])]
    : parts[0] === 'agents' ? [{label:'Agents', href:'/dashboard'}, {label:'New agent'}]
    : parts[0] === 'runs' ? [{label:'Executions', href:'/dashboard'}, {label:(parts[1] ?? '').slice(0, 8)}]
    : [{label:SECTIONS[parts[0] ?? 'dashboard'] ?? 'Not found'}];
  const organization = me.data?.organization.name ?? 'Workspace', email = me.data?.user.email ?? '';
  return <div className="shell">
    <aside className="sidebar">
      <Link href="/dashboard" className="brand"><span className="brand-icon"><Boxes size={16}/></span>Agent Factory</Link>
      <nav className="nav" aria-label="Primary">{groups.map(group => <div key={group.label} style={{display:'contents'}}><div className="nav-label">{group.label}</div>{group.items.map(item => <Link key={item.href} className={`nav-link ${item.active ? 'active' : ''}`} aria-current={item.active ? 'page' : undefined} href={item.href}><item.icon size={16}/>{item.label}{'count' in item && !!item.count && <span className="nav-count" aria-hidden="true" title={`${item.count} waiting for a decision`}>{item.count}</span>}</Link>)}</div>)}</nav>
      <div className="sidebar-bottom"><span className="avatar">{initials(organization)}</span><div style={{minWidth:0}}><div className="org-name">{organization}</div><div className="org-role">{me.data?.role ?? 'Connecting'}</div></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <nav className="breadcrumbs" aria-label="Breadcrumb"><span className="root">{organization}</span>{trail.map((crumb, index) => <span key={index} style={{display:'contents'}}><span className={index ? 'sep' : 'sep root'}>/</span>{crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : <span className="here">{crumb.label}</span>}</span>)}</nav>
        <div className="topbar-right">
          <span className={`env ${live ? 'live' : ''}`} title={live ? `Agents run on ${me.data?.model}` : 'Deterministic tool dispatch. No model calls and no model charges.'}>{live ? 'Live model runtime' : 'Demo mode'}</span>
          <span className="userchip"><span className="avatar light">{initials(email)}</span><span className="who">{email}</span></span>
          <Button variant="ghost" className="icon" aria-label="Sign out" title="Sign out" onClick={logout}><LogOut size={15}/></Button>
        </div>
      </header>
      <main className="content">{me.error ? <div className="error">{me.error.message} <Button variant="secondary" onClick={logout}>Sign in again</Button></div> : page}</main>
    </div>
  </div>;
}
