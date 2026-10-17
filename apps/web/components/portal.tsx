'use client';
import {Fragment, useEffect, useRef, useState} from 'react';
import Link from 'next/link';
import {ArrowLeft, ArrowRight, Building2, LayoutDashboard, LoaderCircle, Banknote, Bot, CalendarHeart, ClipboardCheck, Bike, FlaskConical, Landmark, ShoppingCart, Users, Utensils, Warehouse, Check, DollarSign, Download, Package, Tags, TrendingUp, Truck, FileSpreadsheet, LogOut, Mail, Pencil, ReceiptText, Trash2, TriangleAlert, Upload} from 'lucide-react';
import {API_URL, PORTAL, token, useResource} from '@/lib/api';
import {Button} from './ui/button';
import {Badge, Card, Empty, ErrorState, Heading, Loading, humanize, useAction} from './shared';
import {StoredPage} from './stored-page';
import {AreaPage, AgentsIndex} from './portal-areas';

type Row = Record<string, unknown>;
type Fields = {single: string[]; tables: Record<string, string[]>};
type Operation = {id: string; name: string; enabled: boolean; kind: string; reads: string | null; area: string | null; documents: number; fields: Fields};
type PortalMe = {email: string; areas: {area: string; title: string}[]; sample: boolean; workspace: {id: string; name: string; kind: string}; role: string; can_work: boolean; operations: Operation[]};
type Stage = 'review' | 'ready' | 'approved' | 'exported';
type Exception = {kind: string; message: string; document_id?: string; lines?: number[]};
type DocumentSummary = {id: string; name: string; source: string; sender: string; status: string; stage: Stage | 'new'; exceptions: number; error: string | null; received_at: string; reviewed: boolean; corrected: boolean; pages: number; fields: Row; rows: Record<string, number>};
type DocumentDetail = DocumentSummary & {page_ids: string[]; answer: Row | null; agent_answer: Row | null; reviewed_at: string | null; deliveries: Record<string, string>; exception_list: Exception[]; approved_at: string | null; approved_automatically: boolean; export_id: string | null};
type Rise = {document_id: string; date: string; supplier: string; customer: string; code: string | null; description: string | null; last_price: number; last_date: string; price: number; rise_percent: number; quantity: number; extra_cents: number};
type Insights = {applies: boolean; documents: number; price_rises: Rise[]; extra_cents: number; spend: {supplier: string; documents: number; total_cents: number}[]; threshold_percent: number; price_gaps: Gap[]; stages: Record<Stage, number>; failed: number};
type Settings = {auto_approve_clean: boolean; terms_days: number; accounts: {code: string; name: string}[]; default_account: string; supplier_accounts: Record<string, string>; tax_code: string; date_format: string; date_formats: string[]; suppliers: string[]; formats: Record<string, string>};
type ExportBatch = {id: string; format: string; format_name: string; documents: number; created_at: string};
type Exports = {items: ExportBatch[]; waiting: number; uncoded_suppliers: string[]};
type Reconciliation = {supplier: string | null; rows: {invoice_number: string; invoice_date: string | null; amount: number | null; status: 'matched' | 'amount_differs' | 'not_received'; document_id?: string; our_amount?: number | null}[]; not_on_statement: {document_id: string; invoice_number: string; invoice_date: string; our_amount: number | null}[]; counts: Record<string, number>; statement_total: number};
type Channel = {id: string; kind: 'mailbox' | 'inbound' | 'webhook'; name: string; enabled: boolean; config: Record<string, string>; last_checked_at: string | null; last_error: string | null; has_secret: boolean; key?: string; address?: string};

const SOURCES: Record<string, string> = {upload: 'Uploaded', mailbox: 'Mailbox', inbound: 'Sent in'};
const STAGES: Record<string, string> = {review: 'needs a person', ready: 'ready', approved: 'approved', exported: 'sent to books', new: 'processing'};
/** Where a document stands, in the customer's words. */
const standing = (item: {status: string; stage: string}) => item.status === 'processed' ? STAGES[item.stage] ?? item.stage : item.status;
async function saveFile(path: string, name: string) {
  const response = await fetch(API_URL + path, {headers: {Authorization: `Bearer ${token()}`}});
  if (!response.ok) throw new Error('The file could not be fetched.');
  const address = URL.createObjectURL(await response.blob()), link = document.createElement('a');
  link.href = address; link.download = name; link.click(); URL.revokeObjectURL(address);
}
const shown = (value: unknown) => value === undefined || value === null || value === '' ? '—' : typeof value === 'boolean' ? value ? 'Yes' : 'No' : String(value);
/** Amounts recorded in cents read as money; everything else as it is. */
const display = (field: string, value: unknown) => field.endsWith('_cents') && typeof value === 'number' ? `$${(value / 100).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : shown(value);
const label = (field: string) => humanize(field.replace(/_cents$/, ''));
const dollars = (cents: number) => `$${(cents / 100).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
function initials(value: string) {return value.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() || '–';}

/** The tabs an agent's page has. A statement reader has no prices or books of its own. */
const TABS: Record<string, {value: string; label: string}[]> = {
  invoice: [{value: 'documents', label: 'Documents'}, {value: 'results', label: 'Results'}, {value: 'prices', label: 'Prices'}, {value: 'books', label: 'Books'}, {value: 'channels', label: 'Channels'}],
  statement: [{value: 'documents', label: 'Documents'}, {value: 'channels', label: 'Channels'}],
};
const tabsOf = (operation: Operation) => TABS[operation.kind] ?? TABS.statement;
const DASHBOARD = `${PORTAL}/dashboard`;
const AREA_ICONS: Record<string, typeof ReceiptText> = {sales: Utensils, purchasing: ShoppingCart, inventory: Warehouse, labour: Users, cash: Banknote, delivery: Bike, catering: CalendarHeart, accounting: Landmark, compliance: ClipboardCheck};
const NAV_STAGES: {title: string; areas: string[]; kinds: string[]}[] = [
  {title: 'Suppliers and stock', areas: ['purchasing', 'inventory'], kinds: ['invoice']},
  {title: 'People and premises', areas: ['labour', 'compliance'], kinds: []},
  {title: 'Sales and takings', areas: ['sales', 'delivery', 'cash'], kinds: []},
  {title: 'Finance', areas: ['accounting'], kinds: ['statement']},
  {title: 'Customers', areas: ['catering'], kinds: []},
];
const home = (operation: Operation, tab = 'documents') => `${PORTAL}/agents/${operation.id}${tab === 'documents' ? '' : `/${tab}`}`;
const open = (id: string) => `${PORTAL}/documents/${id}`;

/** The customer's side of the product: a dashboard of the agents at work for them, and a page for each agent. */
export function Portal({path, logout}: {path: string; logout: () => void}) {
  const me = useResource<PortalMe>('/portal/me');
  const parts = path.split('/').filter(Boolean);
  if (me.isLoading) return <Loading/>;
  if (!me.data) return <div style={{padding:32}}><ErrorState error={me.error}/><Button variant="secondary" onClick={logout}>Sign out</Button></div>;
  const all = me.data.operations, canWork = me.data.can_work, statements = all.find(item => item.kind === 'statement');
  // This place is for a customer's workspace only. Any other session is turned away, not shown an empty platform.
  if (me.data.workspace.kind !== 'customer') return <div className="login"><main className="login-main"><div className="login-card"><h1>No customer workspace</h1><p className="muted small" style={{margin:'8px 0 20px'}}>This account is not signed in to a customer workspace.</p><Button className="full" onClick={logout}>Sign in with another account</Button></div></main></div>;
  const operation = parts[0] === 'agents' ? all.find(item => item.id === parts[1]) : undefined;
  const tab = operation ? tabsOf(operation).find(item => item.value === (parts[2] ?? 'documents')) : undefined;
  const areas = me.data.areas.filter(item => item.area !== 'overview'), area = parts[0] === 'areas' ? areas.find(item => item.area === parts[1]) : undefined;
  // Follow the work from supplier paperwork to customer work, regardless of installation order.
  const navigation = NAV_STAGES.map(stage => ({
    title: stage.title,
    links: [
      ...all.filter(item => stage.kinds.includes(item.kind) || (!areas.length && stage.areas.includes(item.area ?? '')))
        .sort((a, b) => stage.areas.indexOf(a.area ?? '') - stage.areas.indexOf(b.area ?? ''))
        .map(item => ({key: item.id, title: item.name, href: home(item), Icon: AREA_ICONS[item.area ?? ''] ?? (item.kind === 'statement' ? FileSpreadsheet : ReceiptText), active: item.id === operation?.id})),
      ...stage.areas.flatMap(key => areas.filter(item => item.area === key))
        .map(item => ({key: item.area, title: item.title, href: `${PORTAL}/areas/${item.area}`, Icon: AREA_ICONS[item.area] ?? ReceiptText, active: item.area === area?.area})),
    ],
  }));
  const otherAreas = areas.filter(item => !NAV_STAGES.some(stage => stage.areas.includes(item.area)));
  if (otherAreas.length) navigation.push({title: 'Other operations', links: otherAreas.map(item => ({key: item.area, title: item.title, href: `${PORTAL}/areas/${item.area}`, Icon: AREA_ICONS[item.area] ?? ReceiptText, active: item.area === area?.area}))});
  const otherAgents = !areas.length ? all.filter(item => !NAV_STAGES.some(stage => stage.kinds.includes(item.kind) || stage.areas.includes(item.area ?? ''))) : [];
  let page, here = 'Dashboard';
  if (parts[0] === 'documents' && parts[1]) {page = <DocumentPage id={parts[1]} operations={all} canWork={canWork}/>; here = 'Document';}
  else if (operation && tab) {
    here = tab.label;
    page = <>
      <nav className="tabs no-print" aria-label={operation.name}>{tabsOf(operation).map(item => <Link key={item.value} className={`tab ${item.value === tab.value ? 'active' : ''}`} aria-current={item.value === tab.value ? 'page' : undefined} href={home(operation, item.value)}>{item.label}</Link>)}</nav>
      {tab.value === 'results' ? <Results operation={operation} statements={statements}/> : tab.value === 'prices' ? <Prices operation={operation}/> : tab.value === 'books' ? <Books operation={operation} canWork={canWork}/> : tab.value === 'channels' ? <Channels operation={operation} canWork={canWork}/> : <InboxPage operation={operation} canWork={canWork} statement={operation.kind === 'statement'}/>}
    </>;
  }
  else if (area) {here = area.title; page = <AreaPage key={area.area} area={area.area}/>;}
  else if (parts[0] === 'agents' && !parts[1] && areas.length) {here = 'Agents'; page = <AgentsIndex operations={all} areas={areas}/>;}
  else if (parts[0] === 'agents' || parts[0] === 'areas') page = <Card><Empty title="This page is not here">It may have been removed from your workspace. <Link className="link" href={DASHBOARD}>Back to the dashboard</Link></Empty></Card>;
  // A workspace with operations records opens on all of them together; one with only documents, on what its agents bought.
  else page = areas.length ? <AreaPage key="overview" area="overview"/> : <Dashboard operations={all}/>;
  return <div className="shell portal">
    <aside className="sidebar">
      <Link href={DASHBOARD} className="brand"><span className="brand-icon"><Building2 size={16}/></span>{me.data.workspace.name}</Link>
      <nav className="nav" aria-label="Primary">
        <Link className={`nav-link ${here === 'Dashboard' ? 'active' : ''}`} aria-current={here === 'Dashboard' ? 'page' : undefined} href={DASHBOARD}><LayoutDashboard size={16}/>Dashboard</Link>
        {navigation.filter(stage => stage.links.length > 0).map(stage => <Fragment key={stage.title}><div className="nav-label">{stage.title}</div>{stage.links.map(({key, title, href, Icon, active}) => <Link key={key} className={`nav-link ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined} href={href}><Icon size={16}/>{title}</Link>)}</Fragment>)}
        {(areas.length > 0 || otherAgents.length > 0) && <div className="nav-label">Workspace</div>}
        {areas.length > 0 && <Link className={`nav-link ${here === 'Agents' ? 'active' : ''}`} aria-current={here === 'Agents' ? 'page' : undefined} href={`${PORTAL}/agents`}><Bot size={16}/>Agents</Link>}
        {otherAgents.map(item => {const active = item.id === operation?.id; return <Link key={item.id} className={`nav-link ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined} href={home(item)}><ReceiptText size={16}/>{item.name}</Link>;})}
        {!all.length && !areas.length && <div className="muted small" style={{padding:'4px 10px'}}>None yet</div>}
      </nav>
      <div className="sidebar-bottom"><span className="avatar">{initials(me.data.workspace.name)}</span><div style={{minWidth:0}}><div className="org-name">{me.data.workspace.name}</div><div className="org-role">Operations platform</div></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <nav className="breadcrumbs" aria-label="Breadcrumb"><span className="root">{me.data.workspace.name}</span>{operation && <><span className="sep root">/</span><span className="root">{operation.name}</span></>}<span className="sep root">/</span><span className="here">{here}</span></nav>
        <div className="topbar-right">
          {me.data.sample && <span className="sample-pill" title="This workspace holds generated records, not a real business's."><FlaskConical size={13}/>Sample data</span>}
          <span className="userchip"><span className="avatar light">{initials(me.data.email)}</span><span className="who">{me.data.email}</span></span>
          <Button variant="ghost" className="icon" aria-label="Sign out" title="Sign out" onClick={logout}><LogOut size={15}/></Button>
        </div>
      </header>
      <main className="content"><div className="content-inner">{page}</div></main>
    </div>
  </div>;
}

/** The customer platform's own way in: sign in, or join with the invitation code the provider sent. Nothing here builds agents. */
export function PortalLogin({onLogin}: {onLogin: () => void}) {
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [code, setCode] = useState(''), [joining, setJoining] = useState(false), [error, setError] = useState(''), [pending, setPending] = useState(false);
  const post = async (path: string, body: unknown, bearer = '') => {
    const response = await fetch(API_URL + path, {method: 'POST', headers: {'Content-Type': 'application/json', ...(bearer ? {Authorization: `Bearer ${bearer}`} : {})}, body: JSON.stringify(body)}), data = await response.json();
    if (!response.ok) throw new Error(data.error?.message ?? 'Sign in failed');
    return data as {token: string};
  };
  async function submit() {
    setPending(true); setError('');
    try {
      let session;
      if (joining) {
        // An invitation is tied to an email. Someone new gets an account first; someone who has one signs in to it.
        const account = await post('/auth/register', {email, password, organization: 'Personal'}).catch(() => post('/auth/login', {email, password}));
        session = await post('/organization-invitations/accept', {token: code.trim()}, account.token);
      } else session = await post('/auth/login', {email, password});
      localStorage.setItem('portal-token', session.token); onLogin();
    } catch (problem) {setError(problem instanceof Error ? problem.message : 'Sign in failed');} finally {setPending(false);}
  }
  return <div className="login portal-login">
    <aside className="login-aside">
      <div className="brand"><span className="brand-icon"><Building2 size={16}/></span>Operations platform</div>
      <div><h2>Your documents, read and checked for you.</h2><p>See what each agent has handled, what it caught, and what is waiting for you.</p></div>
      <div className="login-legal">Access is by invitation from your provider.</div>
    </aside>
    <main className="login-main"><div className="login-card">
      <h1>{joining ? 'Join your workspace' : 'Sign in'}</h1>
      <p className="muted small" style={{marginBottom:24}}>{joining ? 'Use the email your invitation was sent to, choose a password, and enter the code.' : 'Use the account your workspace invitation was accepted with.'}</p>
      {error && <div role="alert" className="error">{error}</div>}
      <form onSubmit={event => {event.preventDefault(); void submit();}}>
        <div className="field"><label htmlFor="portal-email">{joining ? 'Email' : 'Email or username'}</label><input id="portal-email" className="input" type={joining ? 'email' : 'text'} autoComplete={joining ? 'email' : 'username'} required value={email} onChange={event => setEmail(event.target.value)}/></div>
        <div className="field"><label htmlFor="portal-password">Password</label><input id="portal-password" className="input" type="password" autoComplete={joining ? 'new-password' : 'current-password'} required minLength={joining ? 10 : 1} value={password} onChange={event => setPassword(event.target.value)}/></div>
        {joining && <div className="field"><label htmlFor="portal-code">Invitation code</label><input id="portal-code" className="input" type="password" required minLength={32} maxLength={128} autoComplete="off" value={code} onChange={event => setCode(event.target.value)}/></div>}
        <Button className="full" disabled={pending}>{pending ? 'Connecting…' : joining ? 'Join workspace' : 'Sign in'}</Button>
      </form>
      <Button variant="ghost" className="full" style={{marginTop:8}} onClick={() => {setJoining(!joining); setError('');}}>{joining ? 'Already joined? Sign in' : 'I have an invitation code'}</Button>
    </div></main>
  </div>;
}

type Analytics = {places: string[]; place: string | null; invoices: number; spend_cents: number; lines: number; quantity: number; items: number; from: string | null; to: string | null; days: number; delivery_days: number; bucket: 'day' | 'week';
  series: {start: string; total_cents: number; invoices: number; quantity: number}[]; by_place: Slice[]; by_supplier: Slice[]; top_items: Good[]; most_received: Good[];
  price_rises: number; price_rise_cents: number; movers: OverviewData['movers']; threshold_percent: number;
  agents: {id: string; name: string; kind: Operation['kind']; enabled: boolean; documents: number; review: number; ready: number; failed: number}[]};
type Slice = {name: string; total_cents: number; invoices: number; quantity: number};
type Good = {code: string | null; description: string | null; supplier: string; quantity: number; total_cents: number; times: number; places: number; low_price: number | null; high_price: number | null; last_price: number | null};
const count = (value: number) => value.toLocaleString(undefined, {maximumFractionDigits: 1});
const short = (day: string) => new Date(day + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'});

/** Upright bars over time, to one scale: what came in on each day, or in each week of a longer run. */
function Columns({series, measure, bucket}: {series: Analytics['series']; measure: 'total_cents' | 'quantity'; bucket: 'day' | 'week'}) {
  const most = Math.max(1, ...series.map(row => row[measure])), say = (value: number) => measure === 'total_cents' ? dollars(value) : `${count(value)} cases and pieces`;
  // A label under every bar is unreadable past a couple of weeks: every nth, and always the first.
  const every = Math.ceil(series.length / 10);
  return <div role="img" aria-label={`${measure === 'total_cents' ? 'Purchases' : 'Quantity received'} by ${bucket}, highest ${say(most)}`}>
    <div className="muted small" style={{textAlign:'right',marginBottom:6}}><span style={{display:'inline-block',width:9,height:9,borderRadius:3,background:'#e0a100',marginRight:6}}/>busiest {bucket}: {say(most)}</div>
    <div className="columns" style={{gap:series.length > 40 ? 2 : 8,padding:'0 4px'}}>{series.map(row => <div key={row.start} className={`column ${row[measure] === most ? 'peak' : ''}`}><span style={{height:`${row[measure] / most * 100}%`,minHeight:row[measure] > 0 ? 3 : 0}}/><em><b>{bucket === 'week' ? 'Week of ' : ''}{short(row.start)}</b><br/>{say(row[measure])} · {row.invoices} invoice{row.invoices === 1 ? '' : 's'}</em></div>)}</div>
    <div style={{display:'flex',gap:series.length > 40 ? 2 : 8,marginTop:8,padding:'0 4px'}}>{series.map((row, index) => <div key={row.start} className="muted" style={{flex:1,minWidth:2,fontSize:11.5,textAlign:'center',whiteSpace:'nowrap',overflow:'visible'}}>{index % every === 0 ? short(row.start) : ''}</div>)}</div>
  </div>;
}

/** Ranked bars to one scale: who the money went to, largest first. */
function Ranked({rows}: {rows: Slice[]}) {
  const most = Math.max(1, ...rows.map(row => row.total_cents));
  return <div>{rows.map((row, index) => <div key={row.name} className="rank-row"><span className="rank">{index + 1}</span><span className="small" title={row.name} style={{whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',fontWeight:500}}>{row.name}</span><span className="track"><span style={{width:`${Math.max(1.5, row.total_cents / most * 100)}%`}}/></span><span className="small" style={{fontWeight:600}}>{dollars(row.total_cents)}</span></div>)}</div>;
}

/** The first page: what was bought. How much came in, when, where it went, what the money went on and which prices moved. */
function Dashboard({operations}: {operations: Operation[]}) {
  const [place, setPlace] = useState(''), [measure, setMeasure] = useState<'total_cents' | 'quantity'>('total_cents'), [order, setOrder] = useState<'top_items' | 'most_received'>('top_items');
  const analytics = useResource<Analytics>(`/portal/analytics${place ? `?place=${encodeURIComponent(place)}` : ''}`, operations.length > 0, 30000);
  if (!operations.length) return <><Heading title="Dashboard" subtitle="What you buy, as your invoices record it."/><Card><Empty title="Nothing is set up yet">Your provider has not put an agent to work in this workspace yet. Documents can be received once they have.</Empty></Card></>;
  const data = analytics.data;
  if (!data) return analytics.isLoading ? <Loading/> : <ErrorState error={analytics.error}/>;
  const agent = (id: string) => operations.find(item => item.id === id), invoiceAgent = operations.find(item => item.kind === 'invoice');
  const waiting = data.agents.filter(item => item.review + item.failed > 0), goods = data[order];
  const span = data.from && data.to ? `${short(data.from)} to ${new Date(data.to + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'})}` : '';
  const pick = <select aria-label="Location" className="input" style={{minWidth:220}} value={place} onChange={event => setPlace(event.target.value)}><option value="">All locations</option>{data.places.map(name => <option key={name} value={name}>{name}</option>)}</select>;
  const toggle = <T extends string>(value: T, set: (next: T) => void, options: [T, string][], name: string) => <div className="segmented" role="group" aria-label={name}>{options.map(([option, text]) => <button type="button" key={option} aria-pressed={value === option} onClick={() => set(option)}>{text}</button>)}</div>;
  return <>
    <section className="hero">
      <div className="hero-top"><div><h1>Dashboard</h1><p className="hero-sub">{data.invoices ? `What came in${data.place ? ` at ${data.place}` : ' across all locations'}, from invoices dated ${span}.` : 'What you buy, as your invoices record it.'}</p></div>{data.places.length > 1 && pick}</div>
      {data.invoices > 0 && <div className="hero-figure"><span className="amount">{dollars(data.spend_cents)}</span><span className="caption">purchased in {data.days} days</span><span className="hero-chip"><TrendingUp size={13}/>{dollars(Math.round(data.spend_cents / Math.max(1, data.days) * 7))} a week</span><span className="hero-chip">{data.by_place.length} location{data.by_place.length === 1 ? '' : 's'}</span></div>}
    </section>
    {waiting.map(item => {const operation = agent(item.id); return operation && <div key={item.id} className="notice" style={{marginBottom:16}} role="status"><TriangleAlert size={15} style={{verticalAlign:'-2px',marginRight:8}}/>{item.name}: {[item.review ? `${item.review} need${item.review === 1 ? 's' : ''} a person` : '', item.failed ? `${item.failed} could not be read` : ''].filter(Boolean).join(', ')}. <Link className="link" href={home(operation)}>Open</Link></div>;})}
    {!data.invoices ? <Card><Empty title="No invoices yet">Once invoices arrive, this page shows what came in: how much, when, to which location, and which items the money went on. {invoiceAgent && <Link className="link" href={home(invoiceAgent)}>Upload some</Link>}</Empty></Card> : <>
      <div className="tiles">{[
        {label:'Deliveries invoiced', value:count(data.invoices), sub:`on ${data.delivery_days} of ${data.days} days`, icon:Truck, tint:'#0b7a6b', soft:'#e4f5f1'},
        {label:'Average invoice', value:dollars(Math.round(data.spend_cents / data.invoices)), sub:`${Math.round(data.lines / data.invoices)} lines each on average`, icon:DollarSign, tint:'#1f4fd1', soft:'#edf2fe'},
        {label:'Cases and pieces received', value:count(data.quantity), sub:`${count(data.lines)} invoice lines`, icon:Package, tint:'#a8500a', soft:'#fff3e0'},
        {label:'Different items bought', value:count(data.items), sub:`${data.price_rises} price rise${data.price_rises === 1 ? '' : 's'} over ${data.threshold_percent}%`, icon:Tags, tint:'#7a3fc4', soft:'#f3ecfd'},
      ].map(stat => <div className="tile" key={stat.label}><span className="tile-icon" style={{'--tint': stat.tint, '--tint-soft': stat.soft} as React.CSSProperties}><stat.icon size={19}/></span><div style={{minWidth:0}}><div className="tile-label">{stat.label}</div><div className="tile-value">{stat.value}</div><div className="tile-sub">{stat.sub}</div></div></div>)}</div>
      <Card><div className="row between wrap" style={{marginBottom:12,gap:12}}><h2>What came in, by {data.bucket}</h2>{toggle(measure, setMeasure, [['total_cents', 'Dollars'], ['quantity', 'Quantity']], 'Measure')}</div><Columns series={data.series} measure={measure} bucket={data.bucket}/></Card>
      <div className="grid grid-2" style={{alignItems:'start',margin:'24px 0'}}>
        <Card><h2 style={{marginBottom:4}}>By location</h2><p className="muted small" style={{marginBottom:12}}>Purchases invoiced to each location.</p><Ranked rows={data.by_place.slice(0, 12)}/></Card>
        <Card><h2 style={{marginBottom:4}}>By supplier</h2><p className="muted small" style={{marginBottom:12}}>{data.by_supplier.length === 1 ? 'Every invoice so far is from one supplier.' : 'Purchases from each supplier.'}</p><Ranked rows={data.by_supplier.slice(0, 12)}/>
          <table className="table" style={{marginTop:12}}><thead><tr><th>Supplier</th><th className="num">Invoices</th><th className="num">Received</th><th className="num">Average invoice</th></tr></thead><tbody>{data.by_supplier.slice(0, 6).map(row => <tr key={row.name}><td>{row.name}</td><td className="num">{row.invoices}</td><td className="num">{count(row.quantity)}</td><td className="num">{dollars(Math.round(row.total_cents / row.invoices))}</td></tr>)}</tbody></table></Card>
      </div>
      <Card className="flush table-wrap"><div className="row between wrap" style={{padding:'16px 20px 8px',gap:12}}><div><h2>What you bought</h2><p className="muted small">{order === 'top_items' ? 'The items the most money went on.' : 'The items that came in in the greatest quantity.'} {data.items} different items in all.</p></div>{toggle(order, setOrder, [['top_items', 'By dollars'], ['most_received', 'By quantity']], 'Order')}</div>
        <table className="table"><thead><tr><th>Item</th><th className="num">Received</th><th className="num">Times bought</th><th className="num">Locations</th><th className="num">Price paid</th><th className="num">Spent</th><th className="num">Share</th></tr></thead><tbody>{goods.map((item, index) => <tr key={index}><td>{item.description}<div className="cell-sub">{[item.code, item.supplier].filter(Boolean).join(' · ')}</div></td><td className="num">{count(item.quantity)}</td><td className="num">{item.times}</td><td className="num">{item.places}</td><td className="num" style={{whiteSpace:'nowrap'}}>{item.low_price === null ? '—' : item.low_price === item.high_price ? item.low_price.toFixed(2) : `${item.low_price.toFixed(2)} – ${item.high_price?.toFixed(2)}`}</td><td className="num"><b>{dollars(item.total_cents)}</b></td><td className="num">{data.spend_cents ? <span className="share">{(item.total_cents / data.spend_cents * 100).toFixed(1)}%<span><i style={{width:`${Math.min(100, item.total_cents / Math.max(1, goods[0]?.total_cents ?? 1) * 100)}%`}}/></span></span> : '—'}</td></tr>)}</tbody></table></Card>
      <div style={{height:24}}/>
      <Card className="flush table-wrap"><div style={{padding:'16px 20px 4px'}}><h2>Prices that moved</h2><p className="muted small">Items that rose more than {data.threshold_percent}% against the last price the same location paid, by what the rise cost on the invoices where it rose: {dollars(data.price_rise_cents)} in all.</p></div>{data.movers.length ? <table className="table"><thead><tr><th>Item</th><th>Supplier</th><th className="num">From</th><th className="num">To</th><th className="num">Up</th><th className="num">Times</th><th className="num">Cost</th></tr></thead><tbody>{data.movers.map((mover, index) => <tr key={index}><td>{mover.description}{mover.code && <div className="cell-sub">{mover.code}</div>}</td><td>{mover.supplier}</td><td className="num">{mover.from.toFixed(2)}</td><td className="num"><b>{mover.to.toFixed(2)}</b></td><td className="num"><span className="up-pill"><TrendingUp size={12}/>{mover.from > 0 ? ((mover.to / mover.from - 1) * 100).toFixed(0) : '—'}%</span></td><td className="num">{mover.times}</td><td className="num">{dollars(mover.extra_cents)}</td></tr>)}</tbody></table> : <div style={{padding:'8px 20px 20px'}} className="muted small">No item rose by more than {data.threshold_percent}% between two invoices.</div>}{invoiceAgent && <div style={{padding:'0 20px 16px'}}><Link className="link" href={home(invoiceAgent, 'prices')}>See every price rise</Link></div>}</Card>
    </>}
    <div className="section-title"><h2>Your agents</h2></div>
    <Card className="flush table-wrap"><table className="table"><thead><tr><th>Agent</th><th>State</th><th className="num">Documents read</th><th className="num">Waiting for you</th><th className="num">Ready to approve</th><th/></tr></thead><tbody>{data.agents.map(item => {const operation = agent(item.id); return <tr key={item.id}><td><b>{item.name}</b><div className="cell-sub">{item.kind === 'statement' ? 'Checks supplier statements against your invoices' : 'Reads supplier invoices line by line and checks them'}</div></td><td><Badge value={item.enabled ? 'working' : 'paused'}/></td><td className="num">{item.documents}</td><td className={`num ${item.review + item.failed ? 'fail' : ''}`}>{item.review + item.failed}</td><td className="num">{item.kind === 'invoice' ? item.ready : '—'}</td><td>{operation && <Link className="link" href={home(operation)} aria-label={`Open ${item.name}`} style={{display:'inline-flex',alignItems:'center',gap:6}}>Open<ArrowRight size={14}/></Link>}</td></tr>;})}</tbody></table></Card>
  </>;
}

type OverviewData = {operation: string; invoices: number; lines: number; pages: number; clean: number; flagged: number; corrected: number; failed: number; stages: Record<Stage, number>; caught: Record<string, number>; from: string | null; to: string | null; billed_cents: number; by_place: {name: string; total_cents: number}[]; by_week: {week: string; total_cents: number}[]; by_supplier: {supplier: string; documents: number; total_cents: number}[]; price_rises: number; extra_cents: number; movers: {description: string | null; code: string | null; supplier: string; times: number; extra_cents: number; from: number; to: number}[]; threshold_percent: number; statements: {count: number; matched: number; not_received: number; not_received_cents: number; amount_differs: number; not_on_statement: number}; found: {kind: string; cents: number; count: number}[]; found_cents: number; days: number; price_gaps: Gap[]; price_gap_count: number};
type Gap = {lines: number; day: string; supplier: string; code: string | null; description: string | null; customer: string; price: number; lowest_price: number; lowest_at: string; above_percent: number; extra_cents: number; document_id: string};
const FOUND: Record<string, (count: number) => string> = {
  statement_overbilled: count => `${count} invoice${count === 1 ? '' : 's'} a supplier has for more than the invoice you hold`,
  duplicates: count => `${count} invoice${count === 1 ? '' : 's'} that arrived twice`,
  price_gaps: count => `${count} time${count === 1 ? '' : 's'} one location paid more than another for the same item on the same day`,
  price_rises: count => `${count} price rise${count === 1 ? '' : 's'} against the last price you paid`,
};
const CAUGHT: Record<string, string> = {lines_do_not_add_up: 'had a total that did not match its lines and tax', duplicate: 'had been received before', price_looks_misread: 'had a price far from the last one paid', missing_field: 'had a field that could not be read', unreadable_line: 'had a line that could not be read', line_arithmetic: 'had a line whose quantity and price did not make its amount', bad_date: 'had a date that could not be right', no_lines: 'had no lines'};

/** Horizontal bars to one scale, for where the money went. */
function Bars({rows}: {rows: {name: string; total_cents: number}[]}) {
  const most = Math.max(1, ...rows.map(row => row.total_cents));
  return <div className="stack" style={{gap:8}}>{rows.map(row => <div key={row.name} style={{display:'grid',gridTemplateColumns:'minmax(0, 190px) minmax(0, 1fr) auto',gap:12,alignItems:'center'}}><span className="small" title={row.name} style={{whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{row.name}</span><span style={{height:10,borderRadius:3,background:'var(--line)'}}><span style={{display:'block',height:10,borderRadius:3,width:`${Math.max(1, row.total_cents / most * 100)}%`,background:'var(--accent)'}}/></span><span className="small" style={{fontVariantNumeric:'tabular-nums'}}>{dollars(row.total_cents)}</span></div>)}</div>;
}

function GapTable({gaps}: {gaps: Gap[]}) {
  return <table className="table"><thead><tr><th>Date</th><th>Item</th><th>Paid more</th><th className="num">Price</th><th>Paid least</th><th className="num">Price</th><th className="num">Above</th><th className="num">Cost you</th><th className="no-print"/></tr></thead><tbody>{gaps.map((gap, index) => <tr key={index}><td style={{whiteSpace:'nowrap'}}>{new Date(gap.day + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}</td><td>{gap.description}{gap.code && <div className="cell-sub">{gap.code} · {gap.supplier}{gap.lines > 1 ? ` · on ${gap.lines} lines` : ''}</div>}</td><td>{gap.customer}</td><td className="num"><b>{gap.price.toFixed(2)}</b></td><td>{gap.lowest_at}</td><td className="num">{gap.lowest_price.toFixed(2)}</td><td className="num fail">{gap.above_percent}%</td><td className="num">{dollars(gap.extra_cents)}</td><td className="no-print"><Link className="link" href={open(gap.document_id)}>Open</Link></td></tr>)}</tbody></table>;
}

/** What one invoice agent's work has added up to: what was handled, what it caught, and where the money went. */
function Results({operation, statements}: {operation: Operation; statements?: Operation}) {
  const overview = useResource<OverviewData>(`/portal/operations/${operation.id}/overview`, true, 15000);
  const [minutes, setMinutes] = useState(5), [wage, setWage] = useState(20);
  useEffect(() => {try {const kept = Number(localStorage.getItem('portal-minutes')), paid = Number(localStorage.getItem('portal-wage')); if (kept > 0) setMinutes(kept); if (paid > 0) setWage(paid);} catch {}}, []);
  if (overview.isLoading) return <Loading/>;
  if (!overview.data) return <ErrorState error={overview.error}/>;
  const data = overview.data, hours = data.invoices * minutes / 60, noOne = data.invoices ? Math.round(data.clean / data.invoices * 100) : 0;
  const span = data.from && data.to ? `${new Date(data.from + 'T12:00:00').toLocaleDateString(undefined, {month: 'long', day: 'numeric'})} to ${new Date(data.to + 'T12:00:00').toLocaleDateString(undefined, {month: 'long', day: 'numeric', year: 'numeric'})}` : '';
  const caught = Object.entries(data.caught).sort((a, b) => b[1] - a[1]), found = data.statements.not_received + data.statements.amount_differs + data.statements.not_on_statement;
  const monthlyHours = data.days >= 7 ? hours * 30 / data.days : hours;
  if (!data.invoices) return <><Heading title="Results" subtitle="What has been handled for you."/><Card><Empty title="Nothing to report yet">Once invoices arrive, this page shows how many were handled, what was caught, and where prices and money moved. Upload some under Documents, or connect a mailbox under Channels.</Empty></Card></>;
  return <div className="report">
    <Heading title="Results" subtitle={`${data.operation}${span ? `, invoices dated ${span}` : ''}.`} action={<Button variant="secondary" className="no-print" onClick={() => window.print()}><Download size={15}/>Print or save as PDF</Button>}/>
    <Card><p style={{fontSize:18,lineHeight:1.5,margin:0,maxWidth:'70ch'}}><b>{data.invoices} invoices</b> were read and <b>{data.lines.toLocaleString()} lines</b> entered for you, from {data.pages} pages. <b>{data.clean} needed no one</b> ({noOne}%): their lines and tax added up to the total, their prices were in line, and they had not been seen before. {data.flagged ? <><b>{data.flagged} {data.flagged === 1 ? 'was' : 'were'} set aside</b> for a person to look at.</> : 'None had to be set aside.'}</p></Card>
    <div style={{height:24}}/>
    <div className="grid grid-2" style={{alignItems:'start'}}>
      <Card><h2>Typing you did not do</h2>
        <p className="muted small" style={{margin:'6px 0 12px'}}>Entering an invoice by hand means keying every line. Put in how long one takes you; the count is ours, the minutes are yours.</p>
        <div className="row" style={{gap:12,alignItems:'center',flexWrap:'wrap'}}><label htmlFor="minutes" className="small">Minutes to enter one invoice by hand</label><input id="minutes" className="input no-print" type="number" min={1} max={120} style={{width:80}} value={minutes} onChange={event => {const value = Math.max(1, Number(event.target.value) || 1); setMinutes(value); try {localStorage.setItem('portal-minutes', String(value));} catch {}}}/></div>
        <div className="row" style={{gap:12,alignItems:'center',flexWrap:'wrap',marginTop:8}}><label htmlFor="wage" className="small">What an hour of that work costs you ($)</label><input id="wage" className="input no-print" type="number" min={1} max={500} style={{width:80}} value={wage} onChange={event => {const value = Math.max(1, Number(event.target.value) || 1); setWage(value); try {localStorage.setItem('portal-wage', String(value));} catch {}}}/></div>
        <div className="stat" style={{fontSize:28,marginTop:12}}>{hours < 10 ? hours.toFixed(1) : Math.round(hours)} hours · ${Math.round(hours * wage).toLocaleString()}</div>
        <p className="muted small">{data.invoices} invoices at {minutes} minutes each, at ${wage} an hour. An average invoice here has {Math.round(data.lines / data.invoices)} lines.{data.days >= 7 && <> Over a month at this volume: about {Math.round(monthlyHours)} hours, ${Math.round(monthlyHours * wage).toLocaleString()}.</>}</p>
      </Card>
      <Card><h2>What was caught</h2>
        {caught.length ? <ul style={{margin:'10px 0 0',paddingLeft:20}} className="stack">{caught.map(([kind, count]) => <li key={kind}><b>{count}</b> {count === 1 ? 'invoice' : 'invoices'} {CAUGHT[kind] ?? kind.replaceAll('_', ' ')}</li>)}</ul> : <p className="muted small" style={{marginTop:10}}>Nothing was flagged: no totals that did not add up, no duplicates, no prices out of line.</p>}
        {data.corrected > 0 && <p className="muted small" style={{marginTop:10}}>A person corrected {data.corrected} of them.</p>}
        {data.failed > 0 && <p className="muted small" style={{marginTop:10}}>{data.failed} could not be read at all.</p>}
        <Link className="link no-print" href={home(operation)} style={{display:'inline-block',marginTop:12}}>Open the documents</Link>
      </Card>
    </div>
    <div style={{height:24}}/>
    <Card><div className="row between wrap" style={{alignItems:'flex-start',gap:24}}>
      <div style={{minWidth:220}}><span className="muted small">Worth taking up with your suppliers</span><div className="stat" style={{fontSize:26,lineHeight:1.15}}>{dollars(data.found_cents)}</div><p className="muted small" style={{marginTop:4}}>in {data.days} day{data.days === 1 ? '' : 's'} of invoices, {dollars(data.billed_cents)} billed.</p></div>
      <div style={{flex:1,minWidth:280}}>{data.found.length ? <table className="table"><tbody>{data.found.map(row => <tr key={row.kind}><td>{FOUND[row.kind]?.(row.count) ?? row.kind}</td><td className="num"><b>{dollars(row.cents)}</b></td></tr>)}</tbody></table> : <p className="muted small">Nothing was found that is worth money: no statement amounts above your invoices, no duplicates, no prices out of line.</p>}</div>
    </div><p className="help" style={{marginTop:12}}>These are amounts to raise with a supplier or put right, not money already returned. A price rise is what you paid above the last price on the invoice where it rose; a supplier may have good reason for it.</p><Link className="link no-print" href={home(operation, 'prices')} style={{display:'inline-block',marginTop:8}}>See every price behind these figures</Link></Card>
    <div className="grid grid-4" style={{margin:'24px 0'}}>{[{label:'Billed in total', value:dollars(data.billed_cents)}, {label:`Price rises over ${data.threshold_percent}%`, value:String(data.price_rises)}, {label:'Same item, different price', value:String(data.price_gap_count)}, {label:'Statement differences', value:data.statements.count ? String(found) : '—'}].map(stat => <Card key={stat.label}><span className="muted small">{stat.label}</span><div className="stat" style={{fontSize:24}}>{stat.value}</div></Card>)}</div>
    <div className="grid grid-2" style={{alignItems:'start'}}>
      <Card><h2 style={{marginBottom:12}}>Billed by location</h2><Bars rows={data.by_place.slice(0, 12)}/></Card>
      <Card><h2 style={{marginBottom:12}}>Billed by week</h2><Bars rows={data.by_week.map(row => ({name: `Week of ${new Date(row.week + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}`, total_cents: row.total_cents}))}/>
        {data.by_supplier.length > 1 && <><h3 style={{margin:'20px 0 12px'}}>By supplier</h3><Bars rows={data.by_supplier.map(row => ({name: row.supplier, total_cents: row.total_cents}))}/></>}</Card>
    </div>
    {data.statements.count > 0 && <><div style={{height:24}}/><Card><h2>Supplier statements</h2><p style={{margin:'8px 0 0',maxWidth:'70ch'}}>{data.statements.count === 1 ? 'One statement was' : `${data.statements.count} statements were`} checked against your invoices. <b>{data.statements.matched}</b> invoices agreed. {found ? <><b>{data.statements.not_received}</b> the supplier lists that {data.statements.not_received === 1 ? 'is' : 'are'} not on file here{data.statements.not_received > 0 && <> ({dollars(data.statements.not_received_cents)}: ask for a copy before paying)</>}, <b>{data.statements.amount_differs}</b> where the amounts differ, and <b>{data.statements.not_on_statement}</b> you hold that the supplier does not list.</> : 'Nothing was out of place.'}</p>{statements && <Link className="link no-print" href={home(statements)} style={{display:'inline-block',marginTop:12}}>Open {statements.name}</Link>}</Card></>}
  </div>;
}

function InboxPage({operation, canWork, statement = false}: {operation: Operation; canWork: boolean; statement?: boolean}) {
  const [stage, setStage] = useState<Stage | 'all' | 'failed'>('all');
  const filter = stage === 'all' ? '' : stage === 'failed' ? '&status=failed' : `&stage=${stage}`;
  const documents = useResource<{items: DocumentSummary[]; total: number}>(`/portal/operations/${operation.id}/documents?limit=200${filter}`, true, 5000);
  const insights = useResource<Insights>(`/portal/operations/${operation.id}/insights`, true, 5000);
  const {act, pending, toast} = useAction(), [progress, setProgress] = useState(''), input = useRef<HTMLInputElement>(null);
  async function upload(files: FileList | null) {
    const list = Array.from(files ?? []);
    let done = 0, failed = 0, repeats = 0;
    for (const file of list) {
      setProgress(`Reading ${done + 1} of ${list.length}: ${file.name}`);
      const body = new FormData(); body.append('file', file);
      const made = await act<DocumentDetail & {duplicate: boolean}>(`/portal/operations/${operation.id}/documents`, body);
      if (!made || made.status === 'failed') failed += 1; else if (made.duplicate) repeats += 1;
      done += 1;
    }
    setProgress('');
    if (list.length) toast(`${done - failed - repeats} read${repeats ? `, ${repeats} already here` : ''}${failed ? `, ${failed} could not be read` : ''}.`);
    if (input.current) input.current.value = '';
  }
  const items = documents.data?.items ?? [], columns = operation.fields.single.slice(0, 5), table = Object.keys(operation.fields.tables)[0];
  const stages = insights.data?.stages ?? {review: 0, ready: 0, approved: 0, exported: 0}, failed = insights.data?.failed ?? 0;
  // An operations agent's documents are recorded as they are read; only the doubtful ones wait.
  const record = operation.area !== null;
  const tabs: {value: Stage | 'all' | 'failed'; label: string; count?: number}[] = statement
    ? [{value: 'all', label: 'All'}, {value: 'failed', label: 'Could not be read', count: failed}]
    : record ? [{value: 'all', label: 'All'}, {value: 'review', label: 'Needs a person', count: stages.review}, {value: 'ready', label: 'Recorded', count: stages.ready + stages.approved}, {value: 'failed', label: 'Could not be read', count: failed}]
    : [{value: 'all', label: 'All'}, {value: 'review', label: 'Needs a person', count: stages.review}, {value: 'ready', label: 'Ready to approve', count: stages.ready}, {value: 'approved', label: 'Approved', count: stages.approved}, {value: 'exported', label: 'Sent to books', count: stages.exported}, {value: 'failed', label: 'Could not be read', count: failed}];
  return <>
    <Heading title={operation.name} subtitle={statement ? 'Statements from your suppliers, checked against the invoices you have received.' : record ? `${operation.reads}: read as they arrive, checked, and recorded. Anything doubtful waits for you.` : 'Documents as they arrive, what was read from each, and what needs you.'} action={canWork ? <div className="control-group">{!statement && !record && stages.ready > 0 && <Button variant="secondary" disabled={pending} onClick={async () => {const result = await act<{approved: number}>(`/portal/operations/${operation.id}/approve-ready`, {}); if (result) toast(`${result.approved} approved.`);}}><Check size={15}/>Approve the {stages.ready} ready</Button>}<input ref={input} id="portal-upload" type="file" multiple accept=".pdf,.png,.jpg,.jpeg" hidden onChange={event => void upload(event.target.files)}/><Button disabled={!!progress || !operation.enabled} onClick={() => input.current?.click()}><Upload size={15}/>{progress ? 'Reading…' : statement ? 'Upload a statement' : 'Upload documents'}</Button></div> : undefined}/>
    {!operation.enabled && <div className="notice" style={{marginBottom:16}}>This work is paused by your provider. Nothing new is being read.</div>}
    {progress && <div className="reading" role="status"><LoaderCircle size={18} className="animate-spin" style={{color:'var(--accent)',flex:'none'}}/><span><b>{progress}</b><br/><span className="muted small">Each page is read, every line is entered, then the checks run. A page takes about ten to twenty seconds.</span></span><span className="bar"/></div>}
    <ErrorState error={documents.error}/>
    <div className="control-group" role="tablist" aria-label="Where documents stand" style={{marginBottom:16,flexWrap:'wrap'}}>{tabs.map(tab => <Button key={tab.value} role="tab" aria-selected={stage === tab.value} variant={stage === tab.value ? 'default' : 'secondary'} onClick={() => setStage(tab.value)}>{tab.label}{tab.count !== undefined && <span style={{marginLeft:6,opacity:.75}}>{tab.count}</span>}</Button>)}</div>
    <Card className="flush table-wrap">{items.length ? <table className="table"><thead><tr><th>Received</th><th>Document</th>{columns.map(column => <th key={column}>{label(column)}</th>)}{table && <th className="num">{statement ? 'Invoices listed' : humanize(table)}</th>}<th>Status</th></tr></thead><tbody>{items.map(item => <tr key={item.id}>
      <td className="muted" style={{whiteSpace:'nowrap'}}>{new Date(item.received_at).toLocaleDateString()}<div className="cell-sub">{SOURCES[item.source] ?? item.source}{item.sender ? ` · ${item.sender}` : ''}</div></td>
      <td><Link className="link" href={open(item.id)}><b>{item.name}</b></Link>{item.error && <div className="cell-sub">{item.error}</div>}</td>
      {columns.map(column => <td key={column}>{display(column, item.fields[column])}</td>)}
      {table && <td className="num">{item.rows[table] ?? '—'}</td>}
      <td style={{whiteSpace:'nowrap'}}>{statement ? <Badge value={item.status === 'processed' ? 'read' : item.status}/> : <><Badge value={record && item.status === 'processed' && item.stage !== 'review' ? 'recorded' : standing(item)}/>{item.exceptions > 0 && item.stage === 'review' && <div className="cell-sub">{item.exceptions} to check</div>}{item.corrected && <div className="cell-sub">corrected</div>}</>}</td>
    </tr>)}</tbody></table> : documents.isLoading ? <Loading/> : <Empty title={stage === 'all' ? 'No documents yet' : 'Nothing here'}>{stage === 'all' ? 'Upload a PDF or a photo, or connect a mailbox under Channels and they will arrive here.' : 'No documents stand at this point.'}</Empty>}</Card>
  </>;
}

function coerce(text: string, original: unknown) {
  if (typeof original === 'number') {const number = Number(text.replace(/[$,]/g, '')); return Number.isFinite(number) && text.trim() !== '' ? number : original;}
  if (typeof original === 'boolean') return /^(true|yes|y|1)$/i.test(text.trim());
  return text;
}

function DocumentPage({id, operations, canWork}: {id: string; operations: Operation[]; canWork: boolean}) {
  const document = useResource<DocumentDetail & {operation_id: string}>(`/portal/documents/${id}`, true, 4000);
  const {act, pending, toast} = useAction(), [draft, setDraft] = useState<Row | null>(null);
  if (document.isLoading) return <Loading/>;
  if (!document.data) return <><ErrorState error={document.error}/><Link className="link" href={DASHBOARD}>Back to the dashboard</Link></>;
  const data = document.data, operation = operations.find(item => item.id === data.operation_id) ?? operations[0], statement = operation?.kind === 'statement';
  const current = draft ?? data.answer ?? {}, agent = data.agent_answer ?? {};
  const single = Object.keys(current).filter(field => !Array.isArray(current[field])), tables = Object.keys(current).filter(field => Array.isArray(current[field]));
  const editing = draft !== null, sent = data.stage === 'exported', record = !!operation?.area;
  // The lines the checks point at, numbered from one as the messages number them.
  const flagged = new Set(data.stage === 'review' ? data.exception_list.flatMap(item => item.lines ?? []) : []), first = Math.min(...flagged);
  const setField = (field: string, text: string) => setDraft({...current, [field]: coerce(text, (data.answer ?? {})[field])});
  const setCell = (table: string, index: number, column: string, text: string) => setDraft({...current, [table]: (current[table] as Row[]).map((row, position) => position === index ? {...row, [column]: coerce(text, ((data.answer ?? {})[table] as Row[])[index]?.[column])} : row)});
  async function save(corrected: Row | null) {const saved = await act<DocumentDetail>(`/portal/documents/${id}/review`, corrected ? {corrected, approve: true} : {approve: true}); if (saved) {setDraft(null); toast(corrected ? 'Correction saved and approved.' : 'Approved.');}}
  return <>
    <Heading title={data.name} subtitle={`${SOURCES[data.source] ?? data.source}${data.sender ? ` from ${data.sender}` : ''} · received ${new Date(data.received_at).toLocaleString()}`} action={<Badge value={statement ? data.status === 'processed' ? 'read' : data.status : operation?.area && data.status === 'processed' && data.stage !== 'review' ? 'recorded' : standing(data)}/>}/>
    <Link className="link" href={operation ? home(operation) : DASHBOARD} style={{display:'inline-flex',alignItems:'center',gap:6,marginBottom:16}}><ArrowLeft size={14}/>{operation?.name ?? 'Dashboard'}</Link>
    {data.status === 'failed' && <div className="error" role="alert">This document could not be read. {data.error}</div>}
    {data.status === 'processing' && <div className="notice" role="status">Reading this document…</div>}
    {data.exception_list.length > 0 && <div className="notice" style={{marginBottom:16}} role="status"><div className="row" style={{gap:8,alignItems:'center',marginBottom:6}}><TriangleAlert size={16}/><b>{data.stage === 'review' ? record ? 'This needs a person before it is recorded' : 'This needs a person before it is approved' : 'The checks raised these; a person approved it anyway'}</b></div><ul style={{margin:0,paddingLeft:22}}>{data.exception_list.map((item, index) => <li key={index}>{item.message}{item.document_id && <> <Link className="link" href={open(item.document_id)}>Open it</Link></>}</li>)}</ul></div>}
    {record && data.status === 'processed' && data.stage !== 'review' && <Recorded id={id} stamp={data.reviewed_at ?? ''}/>}
    {data.status === 'processed' && !statement && !record && data.exception_list.length === 0 && data.stage !== 'review' && <p className="muted small" style={{marginBottom:12}}>{data.stage === 'ready' ? 'The checks found nothing wrong: the lines add up to the total, the prices are in line with the last ones paid, and this invoice has not been seen before.' : data.approved_automatically ? 'Approved automatically: the checks found nothing wrong.' : sent ? 'Sent to the books.' : 'Approved by a person.'}</p>}
    {statement && data.status === 'processed' && <StatementCheck id={id}/>}
    <Card><div style={{display:'grid',gridTemplateColumns:'minmax(0, 5fr) minmax(0, 7fr)',gap:24,alignItems:'start'}}>
      <div className="stack">{data.page_ids.length > 0 && <p className="muted small no-print" style={{margin:0}}>{data.page_ids.length === 1 ? 'The page as it arrived.' : `The ${data.page_ids.length} pages as they arrived.`} Click a page to enlarge it.</p>}{data.page_ids.length ? data.page_ids.map((hash, index) => <StoredPage key={hash} path={`/portal/pages/${hash}`} label={`${data.name} page ${index + 1}`}/>) : <p className="muted small">No page image was kept for this document.</p>}</div>
      <div style={{position:'sticky',top:16,minWidth:0}}>
        <div className="row between wrap" style={{marginBottom:8}}><h2>What was read</h2>{canWork && data.status === 'processed' && !sent && !statement && <div className="control-group">{editing ? <><Button variant="secondary" disabled={pending} onClick={() => setDraft(null)}>Cancel</Button><Button disabled={pending} onClick={() => void save(draft)}><Check size={14}/>Save and approve</Button></> : <><Button variant="secondary" disabled={pending} onClick={() => setDraft({...(data.answer ?? {})})}><Pencil size={14}/>Correct</Button>{data.stage !== 'approved' && !(record && data.stage === 'ready') && <Button disabled={pending} onClick={() => void save(null)}><Check size={14}/>{record ? 'Record anyway' : 'Approve'}</Button>}</>}</div>}</div>
        {data.corrected && !editing && <p className="muted small" style={{marginBottom:8}}>A person corrected this. Where the reading was different, it is shown underneath.</p>}
        {single.length > 0 && <div className="table-wrap"><table className="table"><tbody>{single.map(field => <tr key={field}><th style={{width:'38%'}}>{label(field)}</th><td>{editing ? <input aria-label={label(field)} className="input" value={shown(current[field]) === '—' ? '' : String(current[field])} onChange={event => setField(field, event.target.value)}/> : <><b>{display(field, current[field])}</b>{data.corrected && shown(agent[field]) !== shown(current[field]) && <div className="cell-sub">read as {display(field, agent[field])}</div>}</>}</td></tr>)}</tbody></table></div>}
        {tables.map(table => {const rows = current[table] as Row[], columns = operation?.fields.tables[table] ?? Array.from(new Set(rows.flatMap(row => Object.keys(row)))); return <div key={table} style={{marginTop:20}}>
          <h3 style={{marginBottom:8}}>{humanize(table)} · {rows.length} {rows.length === 1 ? 'line' : 'lines'}</h3>
          <div className="table-wrap" style={{maxHeight:620,overflow:'auto'}}><table className="table" style={{fontSize:12.5}}><thead><tr>{columns.map(column => <th key={column} style={{padding:'6px 8px',whiteSpace:'nowrap'}}>{humanize(column)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className={flagged.has(index + 1) ? 'flagged' : undefined} ref={index + 1 === first ? node => node?.scrollIntoView({block: 'center'}) : undefined}>{columns.map(column => <td key={column} title={shown(row[column])} style={{padding:'5px 8px',whiteSpace:'nowrap',maxWidth:column === 'description' ? 360 : 230,overflow:'hidden',textOverflow:'ellipsis'}}>{editing ? <input aria-label={`${humanize(column)} line ${index + 1}`} className="input" style={{height:28,fontSize:12.5,minWidth:column === 'description' ? 180 : 70}} value={shown(row[column]) === '—' ? '' : String(row[column])} onChange={event => setCell(table, index, column, event.target.value)}/> : shown(row[column])}</td>)}</tr>)}</tbody></table></div>
        </div>;})}
      </div>
    </div></Card>
  </>;
}

type Recording = {items: {area: string; area_title: string; kind: string; day: string; location: string; data: Record<string, unknown>}[]};
type QuoteLines = {lines: {item: string; portions: number; price: number; amount: number}[]; discount: number; discount_percent: number; servers: number; staff: number; total: number; deposit: number; per_guest: number};
/** What became of an operations document: the records it was written into, and for an enquiry the quote worked out from it. */
function Recorded({id, stamp}: {id: string; stamp: string}) {
  const made = useResource<Recording>(`/portal/documents/${id}/records?${stamp}`);
  const items = made.data?.items ?? [];
  if (!items.length) return null;
  const first = items[0], quote = first.data.quote as QuoteLines | undefined;
  return <div style={{marginBottom:20}}><Card>
    <div className="row between wrap"><div><h2>{quote ? 'The quote' : 'Recorded'}</h2><p className="muted small">{quote ? 'Priced in code from the menu, the guest count and the staff the event needs. The agent read the enquiry; it did not choose the price.' : `The checks found nothing wrong, so ${items.length === 1 ? 'this was' : `these ${items.length} records were`} written to ${first.area_title} as it was read.`}</p></div><Link className="link" href={`${PORTAL}/areas/${first.area}`} style={{display:'inline-flex',alignItems:'center',gap:4}}>{first.area_title}<ArrowRight size={13}/></Link></div>
    {quote && <div className="grid grid-2" style={{marginTop:12,alignItems:'start'}}>
      <div className="table-wrap"><table className="table"><thead><tr><th>Item</th><th className="num">Portions</th><th className="num">Each</th><th className="num">Amount</th></tr></thead><tbody>
        {quote.lines.map(line => <tr key={line.item}><td>{line.item}</td><td className="num">{line.portions}</td><td className="num">{dollars(line.price)}</td><td className="num">{dollars(line.amount)}</td></tr>)}
        {quote.discount > 0 && <tr><td colSpan={3}>Less {quote.discount_percent}% for the size of the party</td><td className="num">−{dollars(quote.discount)}</td></tr>}
        <tr><td colSpan={3}>{quote.servers} server{quote.servers === 1 ? '' : 's'} for the event</td><td className="num">{dollars(quote.staff)}</td></tr>
        <tr className="strong"><td colSpan={3}>Quote</td><td className="num">{dollars(quote.total)}</td></tr>
      </tbody></table></div>
      <div className="agent-stats" style={{gridTemplateColumns:'repeat(2, minmax(0, 1fr))'}}><div><span>Per guest</span><b>{dollars(quote.per_guest)}</b></div><div><span>Deposit to confirm</span><b>{dollars(quote.deposit)}</b></div></div>
    </div>}
  </Card></div>;
}

const MATCH: Record<string, string> = {matched: 'agrees', amount_differs: 'amount differs', not_received: 'not on file'};
/** A supplier's statement set against the invoices on file: what agrees, what differs, what never arrived. */
function StatementCheck({id}: {id: string}) {
  const check = useResource<Reconciliation>(`/portal/documents/${id}/reconciliation`, true, 15000);
  if (!check.data) return check.isLoading ? <Loading/> : <ErrorState error={check.error}/>;
  const data = check.data, counts = data.counts, money = (value: number | null | undefined) => value === null || value === undefined ? '—' : `$${value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  return <div style={{marginBottom:24}}><Card>
    <h2>Checked against your invoices</h2>
    <p className="muted small" style={{marginBottom:12}}>Each invoice the statement lists, matched by number to the invoices on file here{data.supplier ? ` from ${data.supplier}` : ''}. One that is not on file has usually not been sent in yet: ask the supplier for a copy before paying it.</p>
    <div className="grid grid-4" style={{marginBottom:16}}>{[{label:'Agree', value:counts.matched}, {label:'Amount differs', value:counts.amount_differs}, {label:'Listed, not on file', value:counts.not_received}, {label:'Received, not listed', value:counts.not_on_statement}].map(stat => <div key={stat.label}><span className="muted small">{stat.label}</span><div className="stat" style={{fontSize:22}}>{stat.value}</div></div>)}</div>
    <div className="table-wrap" style={{maxHeight:420,overflow:'auto'}}><table className="table"><thead><tr><th>Invoice</th><th>Date</th><th className="num">Statement says</th><th className="num">Your invoice says</th><th>Result</th><th/></tr></thead><tbody>
      {data.rows.filter(row => row.status !== 'matched').concat(data.rows.filter(row => row.status === 'matched')).map((row, index) => <tr key={index}><td><b>{row.invoice_number}</b></td><td>{row.invoice_date ?? '—'}</td><td className="num">{money(row.amount)}</td><td className="num">{row.status === 'not_received' ? '—' : money(row.our_amount)}</td><td className={row.status === 'matched' ? 'check' : 'fail'}>{MATCH[row.status]}</td><td>{row.document_id && <Link className="link" href={open(row.document_id)}>Open</Link>}</td></tr>)}
      {data.not_on_statement.map(row => <tr key={row.document_id}><td><b>{row.invoice_number}</b></td><td>{row.invoice_date}</td><td className="num">—</td><td className="num">{money(row.our_amount)}</td><td className="fail">not on the statement</td><td><Link className="link" href={open(row.document_id)}>Open</Link></td></tr>)}
    </tbody></table></div>
  </Card></div>;
}

function Prices({operation}: {operation: Operation}) {
  const insights = useResource<Insights>(`/portal/operations/${operation.id}/insights`, true, 15000);
  const [saving, setSaving] = useState(false), {toast} = useAction();
  async function exportCsv() {setSaving(true); try {await saveFile(`/portal/operations/${operation.id}/export.csv`, `${operation.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.csv`);} catch (error) {toast(error instanceof Error ? error.message : 'The file could not be fetched.');} finally {setSaving(false);}}
  if (insights.isLoading) return <Loading/>;
  const data = insights.data, rises = data?.price_rises ?? [], spend = data?.spend ?? [];
  return <>
    <Heading title="Price watch" subtitle={`Every line of every invoice, compared with the last price paid for the same item. A price more than ${data?.threshold_percent ?? 5}% higher is listed here. A price that looks misread is not: it waits under Documents for a person.`} action={<Button variant="secondary" disabled={saving} onClick={() => void exportCsv()}><Download size={15}/>Export every line (CSV)</Button>}/>
    <ErrorState error={insights.error}/>
    {!data?.applies ? <Card><Empty title="Nothing to compare yet">Price watch works on documents with priced lines, such as invoices. It fills in once two or more have been read.</Empty></Card> : <>
      <div className="grid grid-4" style={{marginBottom:24}}>{[{label:'Invoices compared', value:String(data.documents)}, {label:'Price rises found', value:String(rises.length)}, {label:'Paid above the last price', value:dollars(data.extra_cents)}, {label:'Total billed', value:dollars(spend.reduce((sum, row) => sum + row.total_cents, 0))}].map(stat => <Card key={stat.label}><span className="muted small">{stat.label}</span><div className="stat" style={{fontSize:24}}>{stat.value}</div></Card>)}</div>
      <Card className="flush table-wrap"><div style={{padding:'16px 20px 4px'}}><h2>Prices that went up</h2></div>{rises.length ? <table className="table"><thead><tr><th>Date</th><th>Supplier</th><th>Location</th><th>Item</th><th className="num">Was</th><th className="num">Now</th><th className="num">Up</th><th className="num">Cost you</th><th/></tr></thead><tbody>{rises.map((rise, index) => <tr key={index}><td style={{whiteSpace:'nowrap'}}>{rise.date}</td><td>{rise.supplier}</td><td>{rise.customer}</td><td>{rise.description}{rise.code && <div className="cell-sub">{rise.code}</div>}</td><td className="num">{rise.last_price.toFixed(2)}<div className="cell-sub">{rise.last_date}</div></td><td className="num"><b>{rise.price.toFixed(2)}</b></td><td className="num fail">{rise.rise_percent}%</td><td className="num">{dollars(rise.extra_cents)}</td><td><Link className="link" href={open(rise.document_id)}>Open</Link></td></tr>)}</tbody></table> : <div style={{padding:'8px 20px 20px'}} className="muted small">No item has gone up by more than {data.threshold_percent}% between two invoices.</div>}</Card>
      {(data.price_gaps?.length ?? 0) > 0 && <><div style={{height:24}}/><Card className="flush table-wrap"><div style={{padding:'16px 20px 4px'}}><h2>Same item, different price</h2><p className="muted small">On the same day, from the same supplier, one location paid more than another for the same item. {data.price_gaps.length} in all, costing {dollars(data.price_gaps.reduce((sum, gap) => sum + gap.extra_cents, 0))} above the lowest price paid.</p></div><GapTable gaps={data.price_gaps}/></Card></>}
      <div style={{height:24}}/>
      <Card className="flush table-wrap"><div style={{padding:'16px 20px 4px'}}><h2>Billed by supplier</h2></div><table className="table"><thead><tr><th>Supplier</th><th className="num">Invoices</th><th className="num">Total billed</th></tr></thead><tbody>{spend.map(row => <tr key={row.supplier}><td>{row.supplier || '—'}</td><td className="num">{row.documents}</td><td className="num">{dollars(row.total_cents)}</td></tr>)}</tbody></table></Card>
    </>}
  </>;
}

/** Getting approved invoices into the accounting system: which account each supplier is coded to, and the files. */
function Books({operation, canWork}: {operation: Operation; canWork: boolean}) {
  const settings = useResource<Settings>(`/portal/operations/${operation.id}/settings`), exports = useResource<Exports>(`/portal/operations/${operation.id}/exports`, true, 8000);
  const {act, pending, toast} = useAction(), [draft, setDraft] = useState<Settings | null>(null), [chart, setChart] = useState<string | null>(null), [format, setFormat] = useState('xero');
  if (settings.isLoading || !settings.data) return settings.isLoading ? <Loading/> : <ErrorState error={settings.error}/>;
  const current = draft ?? settings.data, change = (patch: Partial<Settings>) => setDraft({...current, ...patch});
  const chartText = chart ?? current.accounts.map(account => `${account.code}, ${account.name}`).join('\n');
  const parsed = chartText.split('\n').map(line => line.trim()).filter(Boolean).map(line => {const [code, ...rest] = line.split(','); return {code: code.trim(), name: rest.join(',').trim()};}).filter(account => account.code);
  const options = parsed.length ? parsed : current.accounts;
  async function save() {
    const body = {auto_approve_clean: current.auto_approve_clean, terms_days: current.terms_days, accounts: parsed, default_account: current.default_account, supplier_accounts: Object.fromEntries(Object.entries(current.supplier_accounts).filter(([, code]) => code)), tax_code: current.tax_code, date_format: current.date_format};
    if (await act(`/portal/operations/${operation.id}/settings`, body, 'PUT')) {setDraft(null); setChart(null); toast('Saved.');}
  }
  async function send() {
    const batch = await act<ExportBatch>(`/portal/operations/${operation.id}/exports`, {format});
    if (!batch) return;
    toast(`${batch.documents} sent to the books.`);
    try {await saveFile(`/portal/exports/${batch.id}/file`, `bills-${batch.created_at.slice(0, 10)}-${batch.format}.csv`);} catch {toast('The file is ready; fetch it from the list below.');}
  }
  const waiting = exports.data?.waiting ?? 0, uncoded = exports.data?.uncoded_suppliers ?? [];
  return <>
    <Heading title="Books" subtitle="How approved invoices get into your accounting system: the account each supplier is coded to, and the file to import."/>
    <ErrorState error={exports.error}/>
    <Card>
      <div className="row between wrap"><div><h2>Send to the books</h2><p className="muted small">{waiting ? `${waiting} approved invoice${waiting === 1 ? ' is' : 's are'} waiting to be sent.` : 'Nothing is waiting. Invoices appear here once they are approved.'}</p></div>
        {canWork && <div className="control-group"><select aria-label="File format" className="input" value={format} onChange={event => setFormat(event.target.value)}>{Object.entries(current.formats).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select><Button disabled={pending || !waiting} onClick={() => void send()}><Download size={15}/>Send {waiting || ''} and download</Button></div>}</div>
      {uncoded.length > 0 && <div className="notice" style={{marginTop:12}}>No ledger account is set for {uncoded.join(', ')}. Choose one below before sending.</div>}
      <p className="help" style={{marginTop:12}}>Each invoice is sent once and then marked as sent. The file follows the import template of the system you pick; check its column headings against your own account&apos;s template before the first import. A QuickBooks file holds at most 100 bills and fewer than 1,000 rows; anything over waits for the next file.</p>
      {(exports.data?.items.length ?? 0) > 0 && <div className="table-wrap" style={{marginTop:12}}><table className="table"><thead><tr><th>Sent</th><th>Format</th><th className="num">Invoices</th><th/></tr></thead><tbody>{exports.data?.items.map(batch => <tr key={batch.id}><td>{new Date(batch.created_at).toLocaleString()}</td><td>{batch.format_name}</td><td className="num">{batch.documents}</td><td><Button variant="ghost" onClick={() => void saveFile(`/portal/exports/${batch.id}/file`, `bills-${batch.created_at.slice(0, 10)}-${batch.format}.csv`).catch(() => toast('The file could not be fetched.'))}><Download size={14}/>Download again</Button></td></tr>)}</tbody></table></div>}
    </Card>
    <div style={{height:24}}/>
    <Card>
      <h2>Accounts and approval</h2>
      <div className="grid grid-2" style={{marginTop:12}}>
        <div className="field"><label htmlFor="chart">Your ledger accounts</label><textarea id="chart" className="input" rows={6} disabled={!canWork} placeholder={'5000, Food cost\n5100, Produce'} value={chartText} onChange={event => setChart(event.target.value)}/><span className="help" style={{marginTop:4}}>One per line: the code, a comma, the name. Use the codes from your accounting system.</span></div>
        <div>
          <div className="field"><label htmlFor="default-account">Account for anything not set below</label><select id="default-account" className="input" disabled={!canWork} value={current.default_account} onChange={event => change({default_account: event.target.value})}><option value="">None</option>{options.map(account => <option key={account.code} value={account.code}>{account.code} {account.name}</option>)}</select></div>
          <div className="field"><label htmlFor="terms">Days to pay</label><input id="terms" className="input" type="number" min={0} max={365} disabled={!canWork} value={current.terms_days} onChange={event => change({terms_days: Number(event.target.value)})}/><span className="help" style={{marginTop:4}}>The due date on each bill is the invoice date plus this.</span></div>
          <div className="field"><label htmlFor="tax-code">Tax type or code</label><input id="tax-code" className="input" disabled={!canWork} placeholder="Tax Exempt (0%)" value={current.tax_code} onChange={event => change({tax_code: event.target.value})}/><span className="help" style={{marginTop:4}}>Written on every line. Xero needs one, and it must be the name of a tax rate in your Xero organisation exactly as Xero shows it. QuickBooks asks you to match it to one of its codes while importing.</span></div>
          <div className="field"><label htmlFor="date-format">Dates in the file</label><select id="date-format" className="input" disabled={!canWork} value={current.date_format} onChange={event => change({date_format: event.target.value})}><option value="mdy">Month first: 10/25/2026</option><option value="dmy">Day first: 25/10/2026</option><option value="iso">Year first: 2026-10-25</option></select><span className="help" style={{marginTop:4}}>Xero reads dates the way your region writes them. QuickBooks asks which format the file uses.</span></div>
        </div>
      </div>
      {current.suppliers.length > 0 && <div className="table-wrap" style={{marginTop:8}}><table className="table"><thead><tr><th>Supplier</th><th>Coded to</th></tr></thead><tbody>{current.suppliers.map(supplier => <tr key={supplier}><td>{supplier}</td><td><select aria-label={`Account for ${supplier}`} className="input" disabled={!canWork} value={current.supplier_accounts[supplier] ?? ''} onChange={event => change({supplier_accounts: {...current.supplier_accounts, [supplier]: event.target.value}})}><option value="">The default account</option>{options.map(account => <option key={account.code} value={account.code}>{account.code} {account.name}</option>)}</select></td></tr>)}</tbody></table></div>}
      <label className="inline-check" style={{marginTop:16}}><input type="checkbox" disabled={!canWork} checked={current.auto_approve_clean} onChange={event => change({auto_approve_clean: event.target.checked})}/>Approve invoices automatically when the checks find nothing wrong</label>
      <p className="help" style={{margin:'4px 0 16px'}}>Anything the checks flag still waits for a person: a total that does not match its lines, a price far from the last one paid, an invoice seen before, a field that could not be read.</p>
      {canWork && <Button disabled={pending || (!draft && chart === null)} onClick={() => void save()}>Save</Button>}
    </Card>
  </>;
}

const KINDS: Record<Channel['kind'], {title: string; help: string}> = {
  mailbox: {title: 'A mailbox', help: 'The mailbox your invoices arrive in. It is checked every two minutes for PDF and image attachments. Only mail that arrives after you connect it is read; nothing is moved, marked or deleted.'},
  inbound: {title: 'An address to send files to', help: 'For a scanner, a forwarding rule or another system. You get a web address and a key; a file posted there is read like an upload.'},
  webhook: {title: 'Send results on', help: 'Each result is posted as JSON to an https address of yours, for your accounting or reporting system.'},
};

function Channels({operation, canWork}: {operation: Operation; canWork: boolean}) {
  const channels = useResource<{items: Channel[]}>(`/portal/operations/${operation.id}/channels`, true, 10000);
  const {act, pending, toast} = useAction();
  const [kind, setKind] = useState<Channel['kind']>('mailbox'), [form, setForm] = useState({name:'', host:'', username:'', password:'', folder:'INBOX', url:'', key:'', client_id:'', tenant:'common'}), [microsoft, setMicrosoft] = useState(false), [issued, setIssued] = useState<Channel | null>(null);
  const set = (field: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) => setForm({...form, [field]: event.target.value});
  async function create() {
    const body = kind === 'mailbox' ? {kind, name: form.name, host: form.host, username: form.username, password: form.password, folder: form.folder || 'INBOX', ...(microsoft ? {client_id: form.client_id, tenant: form.tenant || 'common'} : {})} : kind === 'webhook' ? {kind, name: form.name, url: form.url, ...(form.key ? {key: form.key} : {})} : {kind, name: form.name};
    const made = await act<Channel>(`/portal/operations/${operation.id}/channels`, body);
    if (made) {setForm({name:'', host:'', username:'', password:'', folder:'INBOX', url:'', key:'', client_id:'', tenant:'common'}); setIssued(made.key ? made : null); toast(kind === 'mailbox' ? 'Mailbox connected. New mail will be read as it arrives.' : 'Channel added.');}
  }
  const items = channels.data?.items ?? [];
  return <>
    <Heading title="Channels" subtitle="Where documents come from, and where results go."/>
    <ErrorState error={channels.error}/>
    {issued && <div className="notice" style={{marginBottom:16}}><b>Keep this key now. It is not shown again.</b><div style={{marginTop:8}}>Post a file to <code>{API_URL}{issued.address}</code> with the header <code>Authorization: Bearer {issued.key}</code> and the file in a form field named <code>file</code>.</div><Button variant="ghost" style={{marginTop:8}} onClick={() => setIssued(null)}>Done</Button></div>}
    <Card className="flush table-wrap">{items.length ? <table className="table"><thead><tr><th>Channel</th><th>Kind</th><th>Details</th><th>Last checked</th><th>State</th><th aria-label="Actions"/></tr></thead><tbody>{items.map(channel => <tr key={channel.id}>
      <td><b>{channel.name}</b></td><td>{KINDS[channel.kind].title}</td>
      <td>{channel.kind === 'mailbox' ? `${channel.config.username} at ${channel.config.host}, ${channel.config.folder}${channel.config.auth === 'microsoft' ? ', Microsoft sign-in' : ''}` : channel.kind === 'webhook' ? channel.config.url : `${API_URL}/portal/inbound/${channel.id}`}{channel.last_error && <div className="cell-sub fail">{channel.last_error}</div>}</td>
      <td className="muted">{channel.last_checked_at ? new Date(channel.last_checked_at).toLocaleString() : channel.kind === 'mailbox' ? 'Not yet' : '—'}</td>
      <td><Badge value={channel.enabled ? channel.last_error && channel.kind === 'mailbox' ? 'attention' : 'connected' : 'paused'}/></td>
      <td>{canWork && <div className="control-group">{channel.kind === 'mailbox' && <Button variant="secondary" disabled={pending} onClick={async () => {const result = await act<{taken_in: number}>(`/portal/channels/${channel.id}/check`, {}); if (result) toast(result.taken_in ? `${result.taken_in} new document${result.taken_in === 1 ? '' : 's'}.` : 'Nothing new.');}}><Mail size={14}/>Check now</Button>}<Button variant="secondary" disabled={pending} onClick={() => void act(`/portal/channels/${channel.id}`, {enabled: !channel.enabled}, 'PATCH')}>{channel.enabled ? 'Pause' : 'Resume'}</Button><Button variant="ghost" className="icon" aria-label={`Remove ${channel.name}`} disabled={pending} onClick={() => void act(`/portal/channels/${channel.id}`, undefined, 'DELETE')}><Trash2 size={14}/></Button></div>}</td>
    </tr>)}</tbody></table> : channels.isLoading ? <Loading/> : <Empty title="No channels yet">Documents can always be uploaded under Documents. Connect a mailbox to have them arrive by themselves.</Empty>}</Card>
    {canWork && <><div style={{height:24}}/><Card>
      <h2>Add a channel</h2>
      <div className="control-group" style={{margin:'12px 0'}} role="radiogroup" aria-label="Kind of channel">{(Object.keys(KINDS) as Channel['kind'][]).map(value => <label className="inline-check" key={value} style={{margin:0}}><input type="radio" name="channel-kind" checked={kind === value} onChange={() => setKind(value)}/>{KINDS[value].title}</label>)}</div>
      <p className="muted small" style={{marginBottom:16,maxWidth:'70ch'}}>{KINDS[kind].help}</p>
      <form onSubmit={event => {event.preventDefault(); void create();}}>
        <div className="grid grid-2">
          <div className="field"><label htmlFor="channel-name">Name</label><input id="channel-name" className="input" required maxLength={200} placeholder={kind === 'mailbox' ? 'Invoices inbox' : kind === 'webhook' ? 'Accounting system' : 'Front office scanner'} value={form.name} onChange={set('name')}/></div>
          {kind === 'mailbox' && <><div className="field"><label htmlFor="channel-host">Mail server (IMAP)</label><input id="channel-host" className="input" required placeholder="imap.gmail.com" value={form.host} onChange={set('host')}/></div>
            <div className="field"><label htmlFor="channel-username">Account</label><input id="channel-username" className="input" required autoComplete="off" placeholder="invoices@yourbusiness.com" value={form.username} onChange={set('username')}/></div>
            <div className="field"><label htmlFor="channel-signin">Signs in with</label><select id="channel-signin" className="input" value={microsoft ? 'microsoft' : 'password'} onChange={event => setMicrosoft(event.target.value === 'microsoft')}><option value="password">An app password (Gmail and most servers)</option><option value="microsoft">Microsoft sign-in (Outlook.com, Microsoft 365)</option></select></div>
            <div className="field"><label htmlFor="channel-password">{microsoft ? 'Refresh token' : 'App password'}</label><input id="channel-password" className="input" type="password" required autoComplete="new-password" value={form.password} onChange={set('password')}/><span className="help" style={{marginTop:4}}>{microsoft ? 'Microsoft mailboxes take no password. Your provider gives you this token after you sign in to Microsoft once.' : 'A password made for one application, from the account\u2019s security settings, not the ordinary one.'} Stored encrypted and never shown again.</span></div>
            {microsoft && <><div className="field"><label htmlFor="channel-client">Application id</label><input id="channel-client" className="input" required placeholder="00000000-0000-0000-0000-000000000000" value={form.client_id} onChange={set('client_id')}/></div>
            <div className="field"><label htmlFor="channel-tenant">Tenant</label><input id="channel-tenant" className="input" value={form.tenant} onChange={set('tenant')}/><span className="help" style={{marginTop:4}}>common, consumers for a personal account, or your organisation&apos;s id.</span></div></>}
            <div className="field"><label htmlFor="channel-folder">Folder</label><input id="channel-folder" className="input" value={form.folder} onChange={set('folder')}/></div></>}
          {kind === 'webhook' && <><div className="field"><label htmlFor="channel-url">Address</label><input id="channel-url" className="input" type="url" required placeholder="https://" value={form.url} onChange={set('url')}/></div>
            <div className="field"><label htmlFor="channel-key">Key (optional)</label><input id="channel-key" className="input" type="password" autoComplete="new-password" value={form.key} onChange={set('key')}/><span className="help" style={{marginTop:4}}>Sent as a bearer token with each result.</span></div></>}
        </div>
        <Button disabled={pending}>{kind === 'mailbox' ? 'Connect mailbox' : 'Add channel'}</Button>
      </form>
    </Card></>}
  </>;
}
