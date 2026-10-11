'use client';
import {useEffect, useRef, useState} from 'react';
import Link from 'next/link';
import {ArrowLeft, BookOpen, LayoutDashboard, Check, Download, FileSpreadsheet, Inbox as InboxIcon, LogOut, Mail, Pencil, Plug, Trash2, TrendingUp, TriangleAlert, Upload} from 'lucide-react';
import {API_URL, api, token, useResource} from '@/lib/api';
import {Button} from './ui/button';
import {Badge, Card, Empty, ErrorState, Heading, Loading, humanize, useAction} from './shared';
import {StoredPage} from './stored-page';

type Row = Record<string, unknown>;
type Fields = {single: string[]; tables: Record<string, string[]>};
type Operation = {id: string; name: string; enabled: boolean; kind: 'invoice' | 'statement'; documents: number; fields: Fields};
type PortalMe = {workspace: {id: string; name: string; kind: string}; builder_workspace: string | null; role: string; can_work: boolean; operations: Operation[]};
type Stage = 'review' | 'ready' | 'approved' | 'exported';
type Exception = {kind: string; message: string; document_id?: string};
type DocumentSummary = {id: string; name: string; source: string; sender: string; status: string; stage: Stage | 'new'; exceptions: number; error: string | null; received_at: string; reviewed: boolean; corrected: boolean; pages: number; fields: Row; rows: Record<string, number>};
type DocumentDetail = DocumentSummary & {page_ids: string[]; answer: Row | null; agent_answer: Row | null; reviewed_at: string | null; deliveries: Record<string, string>; exception_list: Exception[]; approved_at: string | null; approved_automatically: boolean; export_id: string | null};
type Rise = {document_id: string; date: string; supplier: string; customer: string; code: string | null; description: string | null; last_price: number; last_date: string; price: number; rise_percent: number; quantity: number; extra_cents: number};
type Insights = {applies: boolean; documents: number; price_rises: Rise[]; extra_cents: number; spend: {supplier: string; documents: number; total_cents: number}[]; threshold_percent: number; stages: Record<Stage, number>; failed: number};
type Settings = {auto_approve_clean: boolean; terms_days: number; accounts: {code: string; name: string}[]; default_account: string; supplier_accounts: Record<string, string>; tax_code: string; suppliers: string[]; formats: Record<string, string>};
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

/** The customer's side of the product: their documents, what was read from them, and where they come from. */
export function Portal({path, logout, email}: {path: string; logout: () => void; email: string}) {
  const me = useResource<PortalMe>('/portal/me');
  const [chosen, setChosen] = useState('');
  useEffect(() => {try {setChosen(localStorage.getItem('portal-operation') ?? '');} catch {}}, []);
  const parts = path.split('/').filter(Boolean), section = parts[0] && parts[0] !== 'dashboard' ? parts[0] : 'overview';
  if (me.isLoading) return <Loading/>;
  if (!me.data) return <div style={{padding:32}}><ErrorState error={me.error}/><Button variant="secondary" onClick={logout}>Sign out</Button></div>;
  const all = me.data.operations, operations = all.filter(item => item.kind !== 'statement'), statements = all.find(item => item.kind === 'statement');
  const operation = operations.find(item => item.id === chosen) ?? operations[0];
  const pick = (id: string) => {setChosen(id); try {localStorage.setItem('portal-operation', id);} catch {}};
  async function back() {const result = await api<{token: string}>('/auth/switch-organization', {org_id: me.data?.builder_workspace}); localStorage.setItem('factory-token', result.token); window.location.assign('/customers');}
  const nav = [{href:'/overview', label:'Overview', icon:LayoutDashboard, active:section === 'overview'}, {href:'/inbox', label:'Inbox', icon:InboxIcon, active:section === 'inbox' || section === 'documents'}, {href:'/prices', label:'Price watch', icon:TrendingUp, active:section === 'prices'}, {href:'/books', label:'Books', icon:BookOpen, active:section === 'books'}, ...(statements ? [{href:'/statements', label:'Statements', icon:FileSpreadsheet, active:section === 'statements'}] : []), {href:'/channels', label:'Channels', icon:Plug, active:section === 'channels'}];
  let page;
  if (!operation) page = <Card><Empty title="Nothing is set up yet">Your provider has not put an agent to work in this workspace yet. Documents can be received once they have.</Empty></Card>;
  else if (section === 'documents' && parts[1]) page = <DocumentPage id={parts[1]} operations={all} canWork={me.data.can_work}/>;
  else if (section === 'books') page = <Books operation={operation} canWork={me.data.can_work}/>;
  else if (section === 'statements' && statements) page = <InboxPage operation={statements} canWork={me.data.can_work} statement/>;
  else if (section === 'prices') page = <Prices operation={operation}/>;
  else if (section === 'channels') page = <Channels operation={operation} canWork={me.data.can_work}/>;
  else if (section === 'inbox') page = <InboxPage operation={operation} canWork={me.data.can_work}/>;
  else page = <Overview operation={operation}/>;
  // A deep green rail instead of the builder's navy: the same product family, plainly a different place.
  const rail = {'--nav': '#0f2e2b', '--nav-line': '#1d4641', '--nav-ink': '#a9c4bf', '--nav-ink-strong': '#f1f7f6'} as React.CSSProperties;
  return <div className="shell" style={rail}>
    <aside className="sidebar">
      <Link href="/overview" className="brand"><span className="brand-icon"><InboxIcon size={16}/></span>{me.data.workspace.name}</Link>
      <nav className="nav" aria-label="Primary">
        <div className="nav-label">{operations.length > 1 ? 'Work' : operation?.name ?? 'Work'}</div>
        {operations.length > 1 && <div style={{padding:'0 12px 8px'}}><select aria-label="Operation" className="input" value={operation?.id ?? ''} onChange={event => pick(event.target.value)}>{operations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>}
        {nav.map(item => <Link key={item.href} className={`nav-link ${item.active ? 'active' : ''}`} aria-current={item.active ? 'page' : undefined} href={item.href}><item.icon size={16}/>{item.label}</Link>)}
      </nav>
      <div className="sidebar-bottom"><span className="avatar">{initials(me.data.workspace.name)}</span><div style={{minWidth:0}}><div className="org-name">{me.data.workspace.name}</div><div className="org-role">{me.data.role === 'customer' ? 'Member' : `Provider ${me.data.role}`}</div></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <nav className="breadcrumbs" aria-label="Breadcrumb"><span className="root">{me.data.workspace.name}</span><span className="sep root">/</span><span className="here">{section === 'documents' ? 'Document' : nav.find(item => item.active)?.label ?? 'Overview'}</span></nav>
        <div className="topbar-right">
          {me.data.builder_workspace && <Button variant="secondary" onClick={() => void back()}><ArrowLeft size={14}/>Back to Agent Factory</Button>}
          <span className="userchip"><span className="avatar light">{initials(email)}</span><span className="who">{email}</span></span>
          <Button variant="ghost" className="icon" aria-label="Sign out" title="Sign out" onClick={logout}><LogOut size={15}/></Button>
        </div>
      </header>
      <main className="content"><div className="content-inner">{page}</div></main>
    </div>
  </div>;
}

type OverviewData = {operation: string; invoices: number; lines: number; pages: number; clean: number; flagged: number; corrected: number; failed: number; stages: Record<Stage, number>; caught: Record<string, number>; from: string | null; to: string | null; billed_cents: number; by_place: {name: string; total_cents: number}[]; by_week: {week: string; total_cents: number}[]; by_supplier: {supplier: string; documents: number; total_cents: number}[]; price_rises: number; extra_cents: number; movers: {description: string | null; code: string | null; supplier: string; times: number; extra_cents: number; from: number; to: number}[]; threshold_percent: number; statements: {count: number; matched: number; not_received: number; amount_differs: number; not_on_statement: number}};
const CAUGHT: Record<string, string> = {lines_do_not_add_up: 'had a total that did not match its lines and tax', duplicate: 'had been received before', price_looks_misread: 'had a price far from the last one paid', missing_field: 'had a field that could not be read', unreadable_line: 'had a line that could not be read', line_arithmetic: 'had a line whose quantity and price did not make its amount', bad_date: 'had a date that could not be right', no_lines: 'had no lines'};

/** Horizontal bars to one scale, for where the money went. */
function Bars({rows}: {rows: {name: string; total_cents: number}[]}) {
  const most = Math.max(1, ...rows.map(row => row.total_cents));
  return <div className="stack" style={{gap:8}}>{rows.map(row => <div key={row.name} style={{display:'grid',gridTemplateColumns:'minmax(0, 190px) minmax(0, 1fr) auto',gap:12,alignItems:'center'}}><span className="small" title={row.name} style={{whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{row.name}</span><span style={{height:10,borderRadius:3,background:'var(--line)'}}><span style={{display:'block',height:10,borderRadius:3,width:`${Math.max(1, row.total_cents / most * 100)}%`,background:'var(--accent)'}}/></span><span className="small" style={{fontVariantNumeric:'tabular-nums'}}>{dollars(row.total_cents)}</span></div>)}</div>;
}

/** The first thing an owner sees: what was handled for them, what it caught, and where prices and money moved. */
function Overview({operation}: {operation: Operation}) {
  const overview = useResource<OverviewData>(`/portal/operations/${operation.id}/overview`, true, 15000);
  const [minutes, setMinutes] = useState(5);
  useEffect(() => {try {const kept = Number(localStorage.getItem('portal-minutes')); if (kept > 0) setMinutes(kept);} catch {}}, []);
  if (overview.isLoading) return <Loading/>;
  if (!overview.data) return <ErrorState error={overview.error}/>;
  const data = overview.data, hours = data.invoices * minutes / 60, noOne = data.invoices ? Math.round(data.clean / data.invoices * 100) : 0;
  const span = data.from && data.to ? `${new Date(data.from + 'T12:00:00').toLocaleDateString(undefined, {month: 'long', day: 'numeric'})} to ${new Date(data.to + 'T12:00:00').toLocaleDateString(undefined, {month: 'long', day: 'numeric', year: 'numeric'})}` : '';
  const caught = Object.entries(data.caught).sort((a, b) => b[1] - a[1]), found = data.statements.not_received + data.statements.amount_differs + data.statements.not_on_statement;
  if (!data.invoices) return <><Heading title="Overview" subtitle="What has been handled for you."/><Card><Empty title="Nothing to report yet">Once invoices arrive, this page shows how many were handled, what was caught, and where prices and money moved. Upload some from the inbox, or connect a mailbox under Channels.</Empty></Card></>;
  return <div className="report">
    <Heading title="Overview" subtitle={`${data.operation}${span ? `, invoices dated ${span}` : ''}.`} action={<Button variant="secondary" className="no-print" onClick={() => window.print()}><Download size={15}/>Print or save as PDF</Button>}/>
    <Card><p style={{fontSize:18,lineHeight:1.5,margin:0,maxWidth:'70ch'}}><b>{data.invoices} invoices</b> were read and <b>{data.lines.toLocaleString()} lines</b> entered for you, from {data.pages} pages. <b>{data.clean} needed no one</b> ({noOne}%): their lines and tax added up to the total, their prices were in line, and they had not been seen before. {data.flagged ? <><b>{data.flagged} were set aside</b> for a person to look at.</> : 'None had to be set aside.'}</p></Card>
    <div className="grid grid-4" style={{margin:'24px 0'}}>{[{label:'Billed in total', value:dollars(data.billed_cents)}, {label:`Price rises over ${data.threshold_percent}%`, value:String(data.price_rises)}, {label:'Paid above the last price', value:dollars(data.extra_cents)}, {label:'Statement differences', value:data.statements.count ? String(found) : '—'}].map(stat => <Card key={stat.label}><span className="muted small">{stat.label}</span><div className="stat" style={{fontSize:24}}>{stat.value}</div></Card>)}</div>
    <div className="grid grid-2" style={{alignItems:'start'}}>
      <Card><h2>Typing you did not do</h2>
        <p className="muted small" style={{margin:'6px 0 12px'}}>Entering an invoice by hand means keying every line. Put in how long one takes you; the count is ours, the minutes are yours.</p>
        <div className="row" style={{gap:12,alignItems:'center',flexWrap:'wrap'}}><label htmlFor="minutes" className="small">Minutes to enter one invoice by hand</label><input id="minutes" className="input no-print" type="number" min={1} max={120} style={{width:80}} value={minutes} onChange={event => {const value = Math.max(1, Number(event.target.value) || 1); setMinutes(value); try {localStorage.setItem('portal-minutes', String(value));} catch {}}}/></div>
        <div className="stat" style={{fontSize:28,marginTop:12}}>{hours < 10 ? hours.toFixed(1) : Math.round(hours)} hours</div>
        <p className="muted small">{data.invoices} invoices at {minutes} minutes each. An average invoice here has {Math.round(data.lines / data.invoices)} lines.</p>
      </Card>
      <Card><h2>What was caught</h2>
        {caught.length ? <ul style={{margin:'10px 0 0',paddingLeft:20}} className="stack">{caught.map(([kind, count]) => <li key={kind}><b>{count}</b> {count === 1 ? 'invoice' : 'invoices'} {CAUGHT[kind] ?? kind.replaceAll('_', ' ')}</li>)}</ul> : <p className="muted small" style={{marginTop:10}}>Nothing was flagged: no totals that did not add up, no duplicates, no prices out of line.</p>}
        {data.corrected > 0 && <p className="muted small" style={{marginTop:10}}>A person corrected {data.corrected} of them.</p>}
        {data.failed > 0 && <p className="muted small" style={{marginTop:10}}>{data.failed} could not be read at all.</p>}
        <Link className="link no-print" href="/inbox" style={{display:'inline-block',marginTop:12}}>Open the inbox</Link>
      </Card>
    </div>
    <div style={{height:24}}/>
    <Card className="flush table-wrap"><div style={{padding:'16px 20px 4px'}}><h2>Where prices moved</h2><p className="muted small">Items whose price rose more than {data.threshold_percent}% against the last time you bought them, by what the rise has cost so far.</p></div>{data.movers.length ? <table className="table"><thead><tr><th>Item</th><th>Supplier</th><th className="num">From</th><th className="num">To</th><th className="num">Times</th><th className="num">Cost you</th></tr></thead><tbody>{data.movers.map((mover, index) => <tr key={index}><td>{mover.description}{mover.code && <div className="cell-sub">{mover.code}</div>}</td><td>{mover.supplier}</td><td className="num">{mover.from.toFixed(2)}</td><td className="num"><b>{mover.to.toFixed(2)}</b></td><td className="num">{mover.times}</td><td className="num">{dollars(mover.extra_cents)}</td></tr>)}</tbody></table> : <div style={{padding:'8px 20px 20px'}} className="muted small">No item rose by more than {data.threshold_percent}% between two invoices.</div>}<div className="no-print" style={{padding:'0 20px 16px'}}><Link className="link" href="/prices">See every price rise</Link></div></Card>
    <div style={{height:24}}/>
    <div className="grid grid-2" style={{alignItems:'start'}}>
      <Card><h2 style={{marginBottom:12}}>Billed by location</h2><Bars rows={data.by_place.slice(0, 12)}/></Card>
      <Card><h2 style={{marginBottom:12}}>Billed by week</h2><Bars rows={data.by_week.map(row => ({name: `Week of ${new Date(row.week + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}`, total_cents: row.total_cents}))}/>
        {data.by_supplier.length > 1 && <><h3 style={{margin:'20px 0 12px'}}>By supplier</h3><Bars rows={data.by_supplier.map(row => ({name: row.supplier, total_cents: row.total_cents}))}/></>}</Card>
    </div>
    {data.statements.count > 0 && <><div style={{height:24}}/><Card><h2>Supplier statements</h2><p style={{margin:'8px 0 0',maxWidth:'70ch'}}>{data.statements.count === 1 ? 'One statement was' : `${data.statements.count} statements were`} checked against your invoices. <b>{data.statements.matched}</b> invoices agreed. {found ? <><b>{data.statements.not_received}</b> the supplier lists but you never received, <b>{data.statements.amount_differs}</b> where the amounts differ, and <b>{data.statements.not_on_statement}</b> you hold that the supplier does not list.</> : 'Nothing was out of place.'}</p><Link className="link no-print" href="/statements" style={{display:'inline-block',marginTop:12}}>Open statements</Link></Card></>}
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
  const tabs: {value: Stage | 'all' | 'failed'; label: string; count?: number}[] = statement
    ? [{value: 'all', label: 'All'}, {value: 'failed', label: 'Could not be read', count: failed}]
    : [{value: 'all', label: 'All'}, {value: 'review', label: 'Needs a person', count: stages.review}, {value: 'ready', label: 'Ready to approve', count: stages.ready}, {value: 'approved', label: 'Approved', count: stages.approved}, {value: 'exported', label: 'Sent to books', count: stages.exported}, {value: 'failed', label: 'Could not be read', count: failed}];
  return <>
    <Heading title={operation.name} subtitle={statement ? 'Statements from your suppliers, checked against the invoices you have received.' : 'Documents as they arrive, what was read from each, and what needs you.'} action={canWork ? <div className="control-group">{!statement && stages.ready > 0 && <Button variant="secondary" disabled={pending} onClick={async () => {const result = await act<{approved: number}>(`/portal/operations/${operation.id}/approve-ready`, {}); if (result) toast(`${result.approved} approved.`);}}><Check size={15}/>Approve the {stages.ready} ready</Button>}<input ref={input} id="portal-upload" type="file" multiple accept=".pdf,.png,.jpg,.jpeg" hidden onChange={event => void upload(event.target.files)}/><Button disabled={!!progress || !operation.enabled} onClick={() => input.current?.click()}><Upload size={15}/>{progress ? 'Reading…' : statement ? 'Upload a statement' : 'Upload documents'}</Button></div> : undefined}/>
    {!operation.enabled && <div className="notice" style={{marginBottom:16}}>This work is paused by your provider. Nothing new is being read.</div>}
    {progress && <div className="notice" style={{marginBottom:16}} role="status">{progress}</div>}
    <ErrorState error={documents.error}/>
    <div className="control-group" role="tablist" aria-label="Where documents stand" style={{marginBottom:16,flexWrap:'wrap'}}>{tabs.map(tab => <Button key={tab.value} role="tab" aria-selected={stage === tab.value} variant={stage === tab.value ? 'default' : 'secondary'} onClick={() => setStage(tab.value)}>{tab.label}{tab.count !== undefined && <span style={{marginLeft:6,opacity:.75}}>{tab.count}</span>}</Button>)}</div>
    <Card className="flush table-wrap">{items.length ? <table className="table"><thead><tr><th>Received</th><th>Document</th>{columns.map(column => <th key={column}>{label(column)}</th>)}{table && <th className="num">{statement ? 'Invoices listed' : humanize(table)}</th>}<th>Status</th></tr></thead><tbody>{items.map(item => <tr key={item.id}>
      <td className="muted" style={{whiteSpace:'nowrap'}}>{new Date(item.received_at).toLocaleDateString()}<div className="cell-sub">{SOURCES[item.source] ?? item.source}{item.sender ? ` · ${item.sender}` : ''}</div></td>
      <td><Link className="link" href={`/documents/${item.id}`}><b>{item.name}</b></Link>{item.error && <div className="cell-sub">{item.error}</div>}</td>
      {columns.map(column => <td key={column}>{display(column, item.fields[column])}</td>)}
      {table && <td className="num">{item.rows[table] ?? '—'}</td>}
      <td style={{whiteSpace:'nowrap'}}>{statement ? <Badge value={item.status === 'processed' ? 'read' : item.status}/> : <><Badge value={standing(item)}/>{item.exceptions > 0 && item.stage === 'review' && <div className="cell-sub">{item.exceptions} to check</div>}{item.corrected && <div className="cell-sub">corrected</div>}</>}</td>
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
  if (!document.data) return <><ErrorState error={document.error}/><Link className="link" href="/inbox">Back to the inbox</Link></>;
  const data = document.data, operation = operations.find(item => item.id === data.operation_id) ?? operations[0], statement = operation?.kind === 'statement';
  const current = draft ?? data.answer ?? {}, agent = data.agent_answer ?? {};
  const single = Object.keys(current).filter(field => !Array.isArray(current[field])), tables = Object.keys(current).filter(field => Array.isArray(current[field]));
  const editing = draft !== null, sent = data.stage === 'exported';
  const setField = (field: string, text: string) => setDraft({...current, [field]: coerce(text, (data.answer ?? {})[field])});
  const setCell = (table: string, index: number, column: string, text: string) => setDraft({...current, [table]: (current[table] as Row[]).map((row, position) => position === index ? {...row, [column]: coerce(text, ((data.answer ?? {})[table] as Row[])[index]?.[column])} : row)});
  async function save(corrected: Row | null) {const saved = await act<DocumentDetail>(`/portal/documents/${id}/review`, corrected ? {corrected, approve: true} : {approve: true}); if (saved) {setDraft(null); toast(corrected ? 'Correction saved and approved.' : 'Approved.');}}
  const back = statement ? '/statements' : '/inbox';
  return <>
    <Heading title={data.name} subtitle={`${SOURCES[data.source] ?? data.source}${data.sender ? ` from ${data.sender}` : ''} · received ${new Date(data.received_at).toLocaleString()}`} action={<Badge value={statement ? data.status === 'processed' ? 'read' : data.status : standing(data)}/>}/>
    <Link className="link" href={back} style={{display:'inline-flex',alignItems:'center',gap:6,marginBottom:16}}><ArrowLeft size={14}/>{statement ? 'Statements' : 'Inbox'}</Link>
    {data.status === 'failed' && <div className="error" role="alert">This document could not be read. {data.error}</div>}
    {data.status === 'processing' && <div className="notice" role="status">Reading this document…</div>}
    {data.exception_list.length > 0 && <div className="notice" style={{marginBottom:16}} role="status"><div className="row" style={{gap:8,alignItems:'center',marginBottom:6}}><TriangleAlert size={16}/><b>{data.stage === 'review' ? 'This needs a person before it is approved' : 'The checks raised these; a person approved it anyway'}</b></div><ul style={{margin:0,paddingLeft:22}}>{data.exception_list.map((item, index) => <li key={index}>{item.message}{item.document_id && <> <Link className="link" href={`/documents/${item.document_id}`}>Open it</Link></>}</li>)}</ul></div>}
    {data.status === 'processed' && !statement && data.exception_list.length === 0 && data.stage !== 'review' && <p className="muted small" style={{marginBottom:12}}>{data.stage === 'ready' ? 'The checks found nothing wrong: the lines add up to the total, the prices are in line with the last ones paid, and this invoice has not been seen before.' : data.approved_automatically ? 'Approved automatically: the checks found nothing wrong.' : sent ? 'Sent to the books.' : 'Approved by a person.'}</p>}
    {statement && data.status === 'processed' && <StatementCheck id={id}/>}
    <Card><div style={{display:'grid',gridTemplateColumns:'minmax(0, 5fr) minmax(0, 7fr)',gap:24,alignItems:'start'}}>
      <div className="stack">{data.page_ids.length ? data.page_ids.map((hash, index) => <StoredPage key={hash} path={`/portal/pages/${hash}`} label={`${data.name} page ${index + 1}`}/>) : <p className="muted small">No page image was kept for this document.</p>}</div>
      <div style={{position:'sticky',top:16,minWidth:0}}>
        <div className="row between wrap" style={{marginBottom:8}}><h2>What was read</h2>{canWork && data.status === 'processed' && !sent && !statement && <div className="control-group">{editing ? <><Button variant="secondary" disabled={pending} onClick={() => setDraft(null)}>Cancel</Button><Button disabled={pending} onClick={() => void save(draft)}><Check size={14}/>Save and approve</Button></> : <><Button variant="secondary" disabled={pending} onClick={() => setDraft({...(data.answer ?? {})})}><Pencil size={14}/>Correct</Button>{data.stage !== 'approved' && <Button disabled={pending} onClick={() => void save(null)}><Check size={14}/>Approve</Button>}</>}</div>}</div>
        {data.corrected && !editing && <p className="muted small" style={{marginBottom:8}}>A person corrected this. Where the reading was different, it is shown underneath.</p>}
        {single.length > 0 && <div className="table-wrap"><table className="table"><tbody>{single.map(field => <tr key={field}><th style={{width:'38%'}}>{label(field)}</th><td>{editing ? <input aria-label={label(field)} className="input" value={shown(current[field]) === '—' ? '' : String(current[field])} onChange={event => setField(field, event.target.value)}/> : <><b>{display(field, current[field])}</b>{data.corrected && shown(agent[field]) !== shown(current[field]) && <div className="cell-sub">read as {display(field, agent[field])}</div>}</>}</td></tr>)}</tbody></table></div>}
        {tables.map(table => {const rows = current[table] as Row[], columns = operation?.fields.tables[table] ?? Array.from(new Set(rows.flatMap(row => Object.keys(row)))); return <div key={table} style={{marginTop:20}}>
          <h3 style={{marginBottom:8}}>{humanize(table)} · {rows.length} {rows.length === 1 ? 'line' : 'lines'}</h3>
          <div className="table-wrap" style={{maxHeight:620,overflow:'auto'}}><table className="table" style={{fontSize:12.5}}><thead><tr>{columns.map(column => <th key={column} style={{padding:'6px 8px',whiteSpace:'nowrap'}}>{humanize(column)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(column => <td key={column} title={shown(row[column])} style={{padding:'5px 8px',whiteSpace:'nowrap',maxWidth:230,overflow:'hidden',textOverflow:'ellipsis'}}>{editing ? <input aria-label={`${humanize(column)} line ${index + 1}`} className="input" style={{height:28,fontSize:12.5,minWidth:column === 'description' ? 180 : 70}} value={shown(row[column]) === '—' ? '' : String(row[column])} onChange={event => setCell(table, index, column, event.target.value)}/> : shown(row[column])}</td>)}</tr>)}</tbody></table></div>
        </div>;})}
      </div>
    </div></Card>
  </>;
}

const MATCH: Record<string, string> = {matched: 'agrees', amount_differs: 'amount differs', not_received: 'not received'};
/** A supplier's statement set against the invoices on file: what agrees, what differs, what never arrived. */
function StatementCheck({id}: {id: string}) {
  const check = useResource<Reconciliation>(`/portal/documents/${id}/reconciliation`, true, 15000);
  if (!check.data) return check.isLoading ? <Loading/> : <ErrorState error={check.error}/>;
  const data = check.data, counts = data.counts, money = (value: number | null | undefined) => value === null || value === undefined ? '—' : `$${value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  return <div style={{marginBottom:24}}><Card>
    <h2>Checked against your invoices</h2>
    <p className="muted small" style={{marginBottom:12}}>Each invoice the statement lists, matched by number to the invoices you have received{data.supplier ? ` from ${data.supplier}` : ''}.</p>
    <div className="grid grid-4" style={{marginBottom:16}}>{[{label:'Agree', value:counts.matched}, {label:'Amount differs', value:counts.amount_differs}, {label:'Listed, never received', value:counts.not_received}, {label:'Received, not listed', value:counts.not_on_statement}].map(stat => <div key={stat.label}><span className="muted small">{stat.label}</span><div className="stat" style={{fontSize:22}}>{stat.value}</div></div>)}</div>
    <div className="table-wrap" style={{maxHeight:420,overflow:'auto'}}><table className="table"><thead><tr><th>Invoice</th><th>Date</th><th className="num">Statement says</th><th className="num">Your invoice says</th><th>Result</th><th/></tr></thead><tbody>
      {data.rows.filter(row => row.status !== 'matched').concat(data.rows.filter(row => row.status === 'matched')).map((row, index) => <tr key={index}><td><b>{row.invoice_number}</b></td><td>{row.invoice_date ?? '—'}</td><td className="num">{money(row.amount)}</td><td className="num">{row.status === 'not_received' ? '—' : money(row.our_amount)}</td><td className={row.status === 'matched' ? 'check' : 'fail'}>{MATCH[row.status]}</td><td>{row.document_id && <Link className="link" href={`/documents/${row.document_id}`}>Open</Link>}</td></tr>)}
      {data.not_on_statement.map(row => <tr key={row.document_id}><td><b>{row.invoice_number}</b></td><td>{row.invoice_date}</td><td className="num">—</td><td className="num">{money(row.our_amount)}</td><td className="fail">not on the statement</td><td><Link className="link" href={`/documents/${row.document_id}`}>Open</Link></td></tr>)}
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
    <Heading title="Price watch" subtitle={`Every line of every invoice, compared with the last price paid for the same item. A price more than ${data?.threshold_percent ?? 5}% higher is listed here. A price that looks misread is not: it waits in the inbox for a person.`} action={<Button variant="secondary" disabled={saving} onClick={() => void exportCsv()}><Download size={15}/>Export every line (CSV)</Button>}/>
    <ErrorState error={insights.error}/>
    {!data?.applies ? <Card><Empty title="Nothing to compare yet">Price watch works on documents with priced lines, such as invoices. It fills in once two or more have been read.</Empty></Card> : <>
      <div className="grid grid-4" style={{marginBottom:24}}>{[{label:'Invoices compared', value:String(data.documents)}, {label:'Price rises found', value:String(rises.length)}, {label:'Paid above the last price', value:dollars(data.extra_cents)}, {label:'Total billed', value:dollars(spend.reduce((sum, row) => sum + row.total_cents, 0))}].map(stat => <Card key={stat.label}><span className="muted small">{stat.label}</span><div className="stat" style={{fontSize:24}}>{stat.value}</div></Card>)}</div>
      <Card className="flush table-wrap"><div style={{padding:'16px 20px 4px'}}><h2>Prices that went up</h2></div>{rises.length ? <table className="table"><thead><tr><th>Date</th><th>Supplier</th><th>Location</th><th>Item</th><th className="num">Was</th><th className="num">Now</th><th className="num">Up</th><th className="num">Cost you</th><th/></tr></thead><tbody>{rises.map((rise, index) => <tr key={index}><td style={{whiteSpace:'nowrap'}}>{rise.date}</td><td>{rise.supplier}</td><td>{rise.customer}</td><td>{rise.description}{rise.code && <div className="cell-sub">{rise.code}</div>}</td><td className="num">{rise.last_price.toFixed(2)}<div className="cell-sub">{rise.last_date}</div></td><td className="num"><b>{rise.price.toFixed(2)}</b></td><td className="num fail">{rise.rise_percent}%</td><td className="num">{dollars(rise.extra_cents)}</td><td><Link className="link" href={`/documents/${rise.document_id}`}>Open</Link></td></tr>)}</tbody></table> : <div style={{padding:'8px 20px 20px'}} className="muted small">No item has gone up by more than {data.threshold_percent}% between two invoices.</div>}</Card>
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
    const body = {auto_approve_clean: current.auto_approve_clean, terms_days: current.terms_days, accounts: parsed, default_account: current.default_account, supplier_accounts: Object.fromEntries(Object.entries(current.supplier_accounts).filter(([, code]) => code)), tax_code: current.tax_code};
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
      <p className="help" style={{marginTop:12}}>Each invoice is sent once and then marked as sent. The file follows the import template of the system you pick; check its column headings against your own account&apos;s template the first time. Imported bills arrive as drafts in Xero.</p>
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
          <div className="field"><label htmlFor="tax-code">Tax code (optional)</label><input id="tax-code" className="input" disabled={!canWork} value={current.tax_code} onChange={event => change({tax_code: event.target.value})}/></div>
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
  const [kind, setKind] = useState<Channel['kind']>('mailbox'), [form, setForm] = useState({name:'', host:'', username:'', password:'', folder:'INBOX', url:'', key:''}), [issued, setIssued] = useState<Channel | null>(null);
  const set = (field: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) => setForm({...form, [field]: event.target.value});
  async function create() {
    const body = kind === 'mailbox' ? {kind, name: form.name, host: form.host, username: form.username, password: form.password, folder: form.folder || 'INBOX'} : kind === 'webhook' ? {kind, name: form.name, url: form.url, ...(form.key ? {key: form.key} : {})} : {kind, name: form.name};
    const made = await act<Channel>(`/portal/operations/${operation.id}/channels`, body);
    if (made) {setForm({name:'', host:'', username:'', password:'', folder:'INBOX', url:'', key:''}); setIssued(made.key ? made : null); toast(kind === 'mailbox' ? 'Mailbox connected. New mail will be read as it arrives.' : 'Channel added.');}
  }
  const items = channels.data?.items ?? [];
  return <>
    <Heading title="Channels" subtitle="Where documents come from, and where results go."/>
    <ErrorState error={channels.error}/>
    {issued && <div className="notice" style={{marginBottom:16}}><b>Keep this key now. It is not shown again.</b><div style={{marginTop:8}}>Post a file to <code>{API_URL}{issued.address}</code> with the header <code>Authorization: Bearer {issued.key}</code> and the file in a form field named <code>file</code>.</div><Button variant="ghost" style={{marginTop:8}} onClick={() => setIssued(null)}>Done</Button></div>}
    <Card className="flush table-wrap">{items.length ? <table className="table"><thead><tr><th>Channel</th><th>Kind</th><th>Details</th><th>Last checked</th><th>State</th><th aria-label="Actions"/></tr></thead><tbody>{items.map(channel => <tr key={channel.id}>
      <td><b>{channel.name}</b></td><td>{KINDS[channel.kind].title}</td>
      <td>{channel.kind === 'mailbox' ? `${channel.config.username} at ${channel.config.host}, ${channel.config.folder}` : channel.kind === 'webhook' ? channel.config.url : `${API_URL}/portal/inbound/${channel.id}`}{channel.last_error && <div className="cell-sub fail">{channel.last_error}</div>}</td>
      <td className="muted">{channel.last_checked_at ? new Date(channel.last_checked_at).toLocaleString() : channel.kind === 'mailbox' ? 'Not yet' : '—'}</td>
      <td><Badge value={channel.enabled ? channel.last_error && channel.kind === 'mailbox' ? 'attention' : 'connected' : 'paused'}/></td>
      <td>{canWork && <div className="control-group">{channel.kind === 'mailbox' && <Button variant="secondary" disabled={pending} onClick={async () => {const result = await act<{taken_in: number}>(`/portal/channels/${channel.id}/check`, {}); if (result) toast(result.taken_in ? `${result.taken_in} new document${result.taken_in === 1 ? '' : 's'}.` : 'Nothing new.');}}><Mail size={14}/>Check now</Button>}<Button variant="secondary" disabled={pending} onClick={() => void act(`/portal/channels/${channel.id}`, {enabled: !channel.enabled}, 'PATCH')}>{channel.enabled ? 'Pause' : 'Resume'}</Button><Button variant="ghost" className="icon" aria-label={`Remove ${channel.name}`} disabled={pending} onClick={() => void act(`/portal/channels/${channel.id}`, undefined, 'DELETE')}><Trash2 size={14}/></Button></div>}</td>
    </tr>)}</tbody></table> : channels.isLoading ? <Loading/> : <Empty title="No channels yet">Documents can always be uploaded from the inbox. Connect a mailbox to have them arrive by themselves.</Empty>}</Card>
    {canWork && <><div style={{height:24}}/><Card>
      <h2>Add a channel</h2>
      <div className="control-group" style={{margin:'12px 0'}} role="radiogroup" aria-label="Kind of channel">{(Object.keys(KINDS) as Channel['kind'][]).map(value => <label className="inline-check" key={value} style={{margin:0}}><input type="radio" name="channel-kind" checked={kind === value} onChange={() => setKind(value)}/>{KINDS[value].title}</label>)}</div>
      <p className="muted small" style={{marginBottom:16,maxWidth:'70ch'}}>{KINDS[kind].help}</p>
      <form onSubmit={event => {event.preventDefault(); void create();}}>
        <div className="grid grid-2">
          <div className="field"><label htmlFor="channel-name">Name</label><input id="channel-name" className="input" required maxLength={200} placeholder={kind === 'mailbox' ? 'Invoices inbox' : kind === 'webhook' ? 'Accounting system' : 'Front office scanner'} value={form.name} onChange={set('name')}/></div>
          {kind === 'mailbox' && <><div className="field"><label htmlFor="channel-host">Mail server (IMAP)</label><input id="channel-host" className="input" required placeholder="imap.gmail.com" value={form.host} onChange={set('host')}/></div>
            <div className="field"><label htmlFor="channel-username">Account</label><input id="channel-username" className="input" required autoComplete="off" placeholder="invoices@yourbusiness.com" value={form.username} onChange={set('username')}/></div>
            <div className="field"><label htmlFor="channel-password">Password</label><input id="channel-password" className="input" type="password" required autoComplete="new-password" value={form.password} onChange={set('password')}/><span className="help" style={{marginTop:4}}>For Gmail or Outlook, an app password. Stored encrypted and never shown again.</span></div>
            <div className="field"><label htmlFor="channel-folder">Folder</label><input id="channel-folder" className="input" value={form.folder} onChange={set('folder')}/></div></>}
          {kind === 'webhook' && <><div className="field"><label htmlFor="channel-url">Address</label><input id="channel-url" className="input" type="url" required placeholder="https://" value={form.url} onChange={set('url')}/></div>
            <div className="field"><label htmlFor="channel-key">Key (optional)</label><input id="channel-key" className="input" type="password" autoComplete="new-password" value={form.key} onChange={set('key')}/><span className="help" style={{marginTop:4}}>Sent as a bearer token with each result.</span></div></>}
        </div>
        <Button disabled={pending}>{kind === 'mailbox' ? 'Connect mailbox' : 'Add channel'}</Button>
      </form>
    </Card></>}
  </>;
}
