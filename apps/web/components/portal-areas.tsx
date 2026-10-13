'use client';
import {useState} from 'react';
import Link from 'next/link';
import {ArrowRight, FlaskConical, TriangleAlert} from 'lucide-react';
import {PORTAL, useResource} from '@/lib/api';
import {Badge, Card, ErrorState, Loading} from './shared';

type Kind = 'money' | 'percent' | 'points' | 'count' | 'hours' | 'date' | 'badge' | 'text';
type Tile = {label: string; value: number | null; kind: Kind; sub: string; tone: string};
type Column = {key: string; label: string; kind: Kind};
type Row = Record<string, string | number | null> & {_tone?: string};
type Alert = {level: 'bad' | 'warn'; text: string; area?: string; area_title?: string};
type Area = {from_agents: number; area: string; title: string; fed_by: string; locations: string[]; location: string | null; from: string; to: string; weeks: number; sample: boolean;
  tiles: Tile[]; series: {title: string; kind: Kind; bucket: 'day' | 'week'; points: {start: string; value: number}[]}; bars: {title: string; note: string; kind: Kind; rows: {name: string; value: number}[]}[];
  tables: {title: string; note: string; columns: Column[]; rows: Row[]}[]; alerts: Alert[]};

const day = (value: string, year = false) => new Date(value + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric', ...(year ? {year: 'numeric'} : {})});
const dollars = (cents: number, whole = false) => `${cents < 0 ? '−' : ''}$${(Math.abs(cents) / 100).toLocaleString(undefined, {minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2})}`;
/** A figure as a person reads it. A large amount on a tile drops its cents; a table keeps them. */
function shown(value: string | number | null | undefined, kind: Kind, large = false) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return kind === 'date' ? day(value) : value;
  if (kind === 'money') return dollars(value, large && Math.abs(value) >= 1_000_000);
  if (kind === 'percent') return `${value.toFixed(1)}%`;
  if (kind === 'points') return `${value > 0 ? '+' : ''}${value.toLocaleString(undefined, {maximumFractionDigits: 1})} pts`;
  if (kind === 'hours') return `${value.toLocaleString()} h`;
  return value.toLocaleString();
}

/** Upright bars over time, to one scale. */
function Chart({series}: {series: Area['series']}) {
  const most = Math.max(...series.points.map(point => point.value), 0), every = Math.ceil(series.points.length / 10);
  if (!series.points.length || most <= 0) return <p className="muted small">Nothing to chart in this period.</p>;
  return <div role="img" aria-label={`${series.title}, highest ${shown(most, series.kind)}`}>
    <div className="muted small" style={{textAlign:'right',marginBottom:6}}><span style={{display:'inline-block',width:9,height:9,borderRadius:3,background:'#e0a100',marginRight:6}}/>highest {series.bucket}: {shown(most, series.kind)}</div>
    <div className="columns" style={{gap:series.points.length > 40 ? 2 : 8,padding:'0 4px'}}>{series.points.map(point => <div key={point.start} className={`column ${point.value === most ? 'peak' : ''}`}><span style={{height:`${point.value / most * 100}%`,minHeight:point.value > 0 ? 3 : 0}}/><em><b>{series.bucket === 'week' ? 'Week of ' : ''}{day(point.start)}</b><br/>{shown(point.value, series.kind)}</em></div>)}</div>
    <div style={{display:'flex',gap:series.points.length > 40 ? 2 : 8,marginTop:8,padding:'0 4px'}}>{series.points.map((point, index) => <div key={point.start} className="muted" style={{flex:1,minWidth:2,fontSize:11.5,textAlign:'center',whiteSpace:'nowrap',overflow:'visible'}}>{index % every === 0 ? day(point.start) : ''}</div>)}</div>
  </div>;
}

function Ranked({rows, kind}: {rows: {name: string; value: number}[]; kind: Kind}) {
  const most = Math.max(1, ...rows.map(row => Math.abs(row.value)));
  return <div>{rows.map((row, index) => <div key={row.name} className="rank-row"><span className="rank">{index + 1}</span><span className="small" title={row.name} style={{whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis',fontWeight:500}}>{row.name}</span><span className="track"><span style={{width:`${Math.max(1.5, Math.abs(row.value) / most * 100)}%`}}/></span><span className="small" style={{fontWeight:600}}>{shown(row.value, kind)}</span></div>)}</div>;
}

// How many findings a page lists before asking to show the rest.
const FIRST = 8;
const NUMERIC: Kind[] = ['money', 'percent', 'points', 'count', 'hours'];
function Table({table}: {table: Area['tables'][number]}) {
  return <Card className="flush table-wrap"><div style={{padding:'16px 20px 8px'}}><h2>{table.title}</h2>{table.note && <p className="muted small">{table.note}</p>}</div>
    {table.rows.length ? <table className="table"><thead><tr>{table.columns.map(column => <th key={column.key} className={NUMERIC.includes(column.kind) ? 'num' : undefined}>{column.label}</th>)}</tr></thead>
      <tbody>{table.rows.map((row, index) => <tr key={index} className={row._tone || undefined}>{table.columns.map(column => <td key={column.key} className={NUMERIC.includes(column.kind) ? 'num' : undefined} style={column.kind === 'date' ? {whiteSpace:'nowrap'} : undefined}>{column.kind === 'badge' && row[column.key] ? <Badge value={String(row[column.key])}/> : shown(row[column.key], column.kind)}</td>)}</tr>)}</tbody></table>
      : <div className="muted small" style={{padding:'4px 20px 20px'}}>Nothing here in this period.</div>}
  </Card>;
}

/** One operations area: its figures for the chosen location and weeks, and what its rules say needs somebody. */
export function AreaPage({area}: {area: string}) {
  const [location, setLocation] = useState(''), [weeks, setWeeks] = useState(8), [all, setAll] = useState(false);
  const query = new URLSearchParams({weeks: String(weeks), ...(location ? {location} : {})});
  const view = useResource<Area>(`/portal/areas/${area}?${query}`), data = view.data;
  if (!data) return view.isLoading ? <Loading/> : <ErrorState error={view.error}/>;
  const overview = area === 'overview', bad = data.alerts.filter(alert => alert.level === 'bad').length;
  return <>
    <section className="hero">
      <div className="hero-top"><div><h1>{overview ? 'Dashboard' : data.title}</h1><p className="hero-sub">{data.location ?? 'All locations'} · {day(data.from)} to {day(data.to, true)}</p></div>
        <div className="row wrap" style={{gap:10}}>
          <div className="segmented" role="group" aria-label="Period">{[4, 8].map(option => <button type="button" key={option} aria-pressed={weeks === option} onClick={() => setWeeks(option)}>{option} weeks</button>)}</div>
          {data.locations.length > 1 && <select aria-label="Location" className="input" value={location} onChange={event => setLocation(event.target.value)}><option value="">All locations</option>{data.locations.map(name => <option key={name} value={name}>{name}</option>)}</select>}
        </div></div>
      {data.tiles[0] && <div className="hero-figure"><span className="amount">{shown(data.tiles[0].value, data.tiles[0].kind, true)}</span><span className="caption">{data.tiles[0].label.toLowerCase()}{data.tiles[0].sub ? ` · ${data.tiles[0].sub}` : ''}</span>{data.alerts.length > 0 && <span className={`hero-chip ${bad ? 'bad' : 'warn'}`}><TriangleAlert size={13}/>{data.alerts.length} to look at</span>}</div>}
    </section>
    {data.sample && <div className="sample-note" role="note"><FlaskConical size={15}/><span><b>Sample data.</b> This is not a real business. {data.from_agents > 0 ? <>{data.from_agents.toLocaleString()} of the records behind this page were written by an agent reading sample documents; the earlier weeks are generated history.</> : <>These figures are generated. In a working workspace an agent fills this page from {data.fed_by.charAt(0).toLowerCase() + data.fed_by.slice(1)}</>}</span></div>}
    <div className="tiles">{data.tiles.slice(1).map(tile => <div className="tile" key={tile.label}><div style={{minWidth:0}}><div className="tile-label">{tile.label}</div><div className={`tile-value ${tile.tone}`}>{shown(tile.value, tile.kind, true)}</div><div className="tile-sub">{tile.sub}</div></div></div>)}</div>
    {data.alerts.length > 0 && <Card className="attention"><h2>{overview ? 'Needs attention' : 'To look at'}</h2><p className="muted small" style={{marginBottom:10}}>{overview ? 'What the rules of each area turned up, most pressing first.' : 'What the rules of this area turned up.'}</p>
      <ul>{data.alerts.slice(0, all ? undefined : FIRST).map((alert, index) => <li key={index} className={alert.level}><span className="mark"/><span style={{flex:1}}>{alert.text}</span>{alert.area && <Link className="link" href={`${PORTAL}/areas/${alert.area}`} style={{whiteSpace:'nowrap',display:'inline-flex',alignItems:'center',gap:4}}>{alert.area_title}<ArrowRight size={13}/></Link>}</li>)}</ul>{data.alerts.length > FIRST && <button type="button" className="link" style={{background:'none',border:0,padding:'10px 0 0'}} onClick={() => setAll(!all)}>{all ? 'Show fewer' : `Show all ${data.alerts.length}`}</button>}</Card>}
    {overview && data.tables.map(table => <div key={table.title} style={{marginBottom:24}}><Table table={table}/></div>)}
    <Card><h2 style={{marginBottom:12}}>{data.series.title}</h2><Chart series={data.series}/></Card>
    {data.bars.length > 0 && <div className={data.bars.length > 1 ? 'grid grid-2' : undefined} style={{alignItems:'start',marginTop:24}}>{data.bars.map(bar => <Card key={bar.title}><h2 style={{marginBottom:4}}>{bar.title}</h2><p className="muted small" style={{marginBottom:12}}>{bar.note}</p><Ranked rows={bar.rows} kind={bar.kind}/></Card>)}</div>}
    {!overview && data.tables.map(table => <div key={table.title} style={{marginTop:24}}><Table table={table}/></div>)}
  </>;
}

type AgentRow = {id: string; name: string; kind: string; enabled: boolean; documents: number; review: number; ready: number; failed: number};
type Installed = {id: string; name: string; kind: string; reads: string | null; area: string | null};
const READS: Record<string, string> = {invoice: 'Supplier invoices', statement: 'Supplier statements'};

/** The agents at work in this workspace: what each reads, the page it fills, how much it has handled and what waits. */
export function AgentsIndex({operations, areas}: {operations: Installed[]; areas: {area: string; title: string}[]}) {
  const stats = useResource<{agents: AgentRow[]}>('/portal/analytics', operations.length > 0, 15000);
  if (!stats.data) return stats.isLoading ? <Loading/> : <ErrorState error={stats.error}/>;
  const rows = stats.data.agents, waiting = rows.reduce((sum, row) => sum + row.review + row.failed, 0);
  return <>
    <section className="hero"><div className="hero-top"><div><h1>Agents</h1><p className="hero-sub">One agent for each kind of document. Each reads what arrives, checks it, and fills its page.</p></div></div>
      <div className="hero-figure"><span className="amount">{rows.length}</span><span className="caption">agents · {rows.reduce((sum, row) => sum + row.documents, 0).toLocaleString()} documents read</span>{waiting > 0 && <span className="hero-chip warn"><TriangleAlert size={13}/>{waiting} waiting for a person</span>}</div></section>
    <div className="agent-grid">{rows.map(row => {const installed = operations.find(item => item.id === row.id), area = areas.find(item => item.area === installed?.area); return <Link key={row.id} href={`${PORTAL}/agents/${row.id}`} className="agent-card">
      <div className="row between" style={{gap:8,alignItems:'flex-start'}}><h2 style={{margin:0}}>{row.name}</h2><Badge value={row.enabled ? 'working' : 'paused'}/></div>
      <p className="muted small" style={{margin:'8px 0 14px'}}>Reads: {installed?.reads ?? READS[row.kind] ?? 'Documents'}{area && <><br/>Fills: {area.title}</>}</p>
      <div className="agent-stats"><div><span>Documents read</span><b>{row.documents.toLocaleString()}</b></div><div><span>Waiting for you</span><b className={row.review + row.failed ? 'bad' : undefined}>{row.review + row.failed}</b></div></div>
    </Link>;})}</div>
  </>;
}
