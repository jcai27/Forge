'use client';
import {useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {Bot, Plus, Activity, ShieldCheck, Rocket, ChevronRight, FolderPlus} from 'lucide-react';
import {ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid} from 'recharts';
import type {Agent, Metrics, Run, Project, Connection, Build, Budget} from '../../../packages/contracts/src';
import {useCollection, useResource, percent, money} from '@/lib/api';
import {Button} from './ui/button';
import {usePagedCollection} from '@/lib/pagination';
import {CollectionMore} from './collection-more';
import {Heading, Card, Badge, Empty, ErrorState, Loading, Kpis, useAction} from './shared';
import {DATA_FILES, DATA_HELP, DOCUMENT_FILES, datasetRequest, documentText} from './build-inputs';

export function Dashboard() {
  const agents = usePagedCollection<Agent>('/agents'), metrics = useResource<Metrics>('/metrics', true, 4000), runs = useCollection<Run>('/runs?limit=8');
  if (agents.isLoading) return <Loading/>;
  const chart = [...(metrics.data?.evaluations ?? [])].reverse().filter(e => e.scorecard.total).map((e,i) => ({name:`Run ${i+1}`, score:Math.round(e.scorecard.score*100)}));
  const pendingApprovals = metrics.data?.pending_approvals ?? 0, live = metrics.data?.execution_mode === 'live';
  return <>
    <Heading title="Overview" subtitle="Agents in this workspace, the evidence behind them and what is running now." action={<Button asChild><Link href="/agents/new"><Plus size={15}/>Create agent</Link></Button>}/>
    <ErrorState error={agents.error ?? metrics.error}/>
    <Kpis items={[
      {label:'Agents', value:metrics.data?.agents ?? 0, foot:'In this workspace', icon:<Bot size={14}/>},
      {label:'Active deployments', value:metrics.data?.deployed ?? 0, foot:'Pinned to an approved version', icon:<Rocket size={14}/>},
      {label:'Evaluation runs', value:metrics.data?.evaluations.length ?? 0, foot:'Scored against test cases', icon:<Activity size={14}/>},
      {label:'Pending approvals', value:pendingApprovals, foot:pendingApprovals ? <Link className="link" href="/approvals">Review now</Link> : 'Nothing is waiting', icon:<ShieldCheck size={14}/>, attention:pendingApprovals > 0},
    ]}/>
    <div className="section-head"><h2>Agents<span className="count">{agents.data?.total ?? 0}</span></h2><Link href="/integrations" className="link">Manage integrations</Link></div>
    {agents.data?.items.length ? <Card className="flush table-wrap"><table className="table"><thead><tr><th>Agent</th><th>Workflow</th><th>Status</th><th>Created</th><th aria-label="Open"/></tr></thead><tbody>{agents.data.items.map(agent => <tr key={agent.id}>
      <td><Link href={`/agents/${agent.id}`} className="row" style={{gap:12}}><span className="agent-icon"><Bot size={16}/></span><span style={{minWidth:0}}><h3 className="cell-title">{agent.name}</h3><span className="cell-sub" style={{display:'block'}}>{agent.request}</span></span></Link></td>
      <td style={{textTransform:'capitalize'}}>{agent.template.replaceAll('_', ' ')}</td>
      <td><Badge value={agent.best_version_id ? 'verified candidate' : 'draft'}/></td>
      <td className="muted" style={{whiteSpace:'nowrap'}}>{new Date(agent.created_at).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'})}</td>
      <td className="num"><Link className="link" href={`/agents/${agent.id}`} aria-label={`Open ${agent.name}`}><ChevronRight size={15}/></Link></td>
    </tr>)}</tbody></table></Card> : <Card><Empty title="No agents yet">Create an agent from a business process and an authorized data source.</Empty></Card>}
    <CollectionMore resource={agents} label="agents"/>
    <div className="grid grid-2" style={{marginTop:28}}>
      <Card><div className="row between"><h2>Evaluation pass rate</h2>{!live && <span className="badge neutral plain">Demo fixtures</span>}</div><p className="muted small">Share of checks passed in each completed evaluation, oldest first.</p>{chart.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chart} margin={{top:6,right:6,left:-18,bottom:0}}><defs><linearGradient id="score" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#1f4fd1" stopOpacity={.16}/><stop offset="100%" stopColor="#1f4fd1" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#e3e6eb" vertical={false}/><XAxis dataKey="name" tick={{fontSize:11,fill:'#5b6779'}} axisLine={false} tickLine={false} minTickGap={24}/><YAxis domain={[0,100]} unit="%" tick={{fontSize:11,fill:'#5b6779'}} axisLine={false} tickLine={false}/><Tooltip formatter={value => [`${value}%`, 'Pass rate']} contentStyle={{fontSize:12,borderRadius:6,border:'1px solid #cfd4dc'}}/><Area type="monotone" dataKey="score" stroke="#1f4fd1" strokeWidth={2} fill="url(#score)"/></AreaChart></ResponsiveContainer></div> : <Empty title="No evaluations yet">Build an agent to see measured results.</Empty>}</Card>
      <Card><h2>Runtime health</h2><p className="muted small">Across all recorded executions, including isolated evaluations.</p><dl className="dl" style={{marginTop:12}}><dt>Executions</dt><dd>{metrics.data?.runs ?? 0}</dd><dt>Failure rate</dt><dd>{percent(metrics.data?.failure_rate)}</dd><dt>Mean latency</dt><dd>{Math.round(metrics.data?.mean_latency_ms ?? 0)} ms</dd><dt>Recorded cost</dt><dd>{money(metrics.data?.cost)}</dd></dl><div className="notice" style={{marginTop:16}}>{live ? 'Model costs are configured estimates based on recorded usage.' : 'Demo executions use deterministic SDK tool dispatch. No live model calls or model charges.'}</div></Card>
    </div>
    <div className="section-head"><h2>Recent executions</h2></div>
    <Card className="flush table-wrap"><table className="table"><thead><tr><th>Execution</th><th>Mode</th><th>Status</th><th className="num">Latency</th><th>Started</th></tr></thead><tbody>{runs.data?.items.map(run => <tr key={run.id}><td><Link className="link mono" href={`/runs/${run.id}`}>{run.id.slice(0,8)}</Link></td><td style={{textTransform:'capitalize'}}>{run.mode}</td><td><Badge value={run.status}/></td><td className="num">{Math.round(Number(run.metrics.duration_ms ?? 0)).toLocaleString()} ms</td><td className="muted">{new Date(run.created_at).toLocaleString()}</td></tr>)}</tbody></table>{!runs.data?.items.length && <Empty title="No executions yet">Runs appear here when an agent is evaluated or invoked.</Empty>}</Card>
  </>;
}
type Source = 'file' | 'url' | 'builtin' | 'none';
const defaults: Budget = {max_iterations:10,max_cost:25,max_seconds:14400,target_score:.95,stagnation_limit:3};
export function NewAgent() {
  const projects = usePagedCollection<Project>('/projects'), integrations = usePagedCollection<Connection>('/integrations');
  const [project, setProject] = useState(''), [request, setRequest] = useState(''), [selected, setSelected] = useState<string[]>([]), [budget, setBudget] = useState(defaults), [projectName, setProjectName] = useState('');
  const {act,pending,toast} = useAction(), router = useRouter();
  // What the build will be judged against. A build cannot start without one of these.
  const [source, setSource] = useState<Source>('file'), [dataFile, setDataFile] = useState<File | null>(null), [dataUrl, setDataUrl] = useState(''), [reason, setReason] = useState(''), [documents, setDocuments] = useState<File[]>([]), [development, setDevelopment] = useState(60), [selection, setSelection] = useState(60), [validation, setValidation] = useState(60), [working, setWorking] = useState(false);
  const templates = [{name:'Restaurant order entry',text:'Build an agent that processes restaurant orders from email, matches customer aliases to catalog SKUs, checks customer pricing and inventory, and requests approval before creating an order.'}, {name:'Quote generation',text:'Build an agent that processes RFQs, retrieves supplier prices, applies customer margins, verifies arithmetic, and prepares quotes for approval.'}, {name:'Hiring coordination',text:'Build an agent that coordinates interview scheduling, retrieves candidate and job records, and requests authorization before sending communications.'}];
  async function create() {
    const chosen = project || projects.data?.items[0]?.id; if (!chosen) return;
    setWorking(true);
    try {
      // Read every file before anything is created, so an unreadable file leaves nothing half made.
      const texts = await Promise.all(documents.map(async file => ({name: file.name.slice(0, 200), text: await documentText(file)})));
      const agent = await act<Agent>('/agents', {project_id:chosen,request,connection_ids:selected,minimum_score:budget.target_score,...(source === 'none' ? {no_data_reason:reason} : {})});
      if (!agent) return;
      const data = `/agents/${agent.id}/data`;
      for (const document of texts) if (!await act(`/agents/${agent.id}/context`, document)) {router.push(data); return;}
      if (source === 'file' || source === 'url') {
        const [path, body] = await datasetRequest(agent.id, source, dataFile, dataUrl, {development, selection, validation});
        if (!await act(path, body)) {router.push(data); return;}
      }
      const build = await act<Build>(`/agents/${agent.id}/builds`, budget);
      router.push(build ? `/agents/${agent.id}/build` : data);
    } catch (error) {toast(error instanceof Error ? error.message : 'A file could not be read.');}
    finally {setWorking(false);}
  }
  const budgetFields: {key: keyof Budget; label: string; help: string; step?: string; max?: number}[] = [{key:'max_iterations', label:'Maximum iterations', help:'Improvement rounds before the build stops.'}, {key:'max_cost', label:'Maximum cost (USD)', help:'Ceiling on model spend. A pass over a few hundred examples on a large model costs a few dollars.'}, {key:'max_seconds', label:'Time limit (seconds)', help:'Limit on active build time. Time spent paused or waiting for review does not count.'}, {key:'stagnation_limit', label:'Stagnation limit', help:'Rounds without improvement before stopping.'}];
  const connected = integrations.data?.items.filter(c => c.status === 'connected') ?? [];
  const sources: {value: Source; title: string; help: string}[] = [{value:'file', title:'Upload examples', help:'A file of real requests with their correct answers.'}, {value:'url', title:'Examples at a web address', help:'A public https address that serves such a file.'}, {value:'builtin', title:'Built-in demo cases', help:'For the order, quote and hiring examples, which come with fictional cases. Needs the demo connection.'}, {value:'none', title:'No data needed', help:'The correct answer can be checked from the request alone, by rule or calculation.'}];
  const ready = !!projects.data?.items.length && (source === 'file' ? !!dataFile : source === 'url' ? dataUrl.startsWith('https://') : source === 'builtin' ? selected.length > 0 : reason.trim().length >= 20);
  return <>
    <Heading title="Create an agent" subtitle="Describe a business process. The builder designs a specification, tests it against cases and keeps the version that measures best."/>
    <ErrorState error={projects.error ?? integrations.error}/>
    <div className="split">
      <Card><form onSubmit={e=>{e.preventDefault();void create();}}>
        <div className="field"><label htmlFor="request">Business process</label><textarea id="request" className="input" rows={7} required minLength={10} value={request} onChange={e=>setRequest(e.target.value)} placeholder="Build an agent that processes incoming orders…"/><span className="help" style={{marginTop:0}}>Include the business rules and the decisions that need a person.</span></div>
        <div className="field"><label htmlFor="project">Project</label><select id="project" className="input" value={project || projects.data?.items[0]?.id || ''} onChange={e=>setProject(e.target.value)}>{projects.data?.items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
        <CollectionMore resource={projects} label="projects"/>
        <fieldset className="field" style={{border:0,padding:0,minWidth:0}}><legend style={{fontSize:13,fontWeight:600,color:'var(--ink-2)',padding:0,marginBottom:6}}>Source of truth</legend><span className="help" style={{margin:'0 0 6px'}}>What the agent is judged against. The builder reads one part, each change is scored on a second part it never reads, and a third is held back for the final result.</span>
          {sources.map(option => <div key={option.value}><label className={`choice ${source === option.value ? 'selected' : ''}`}><input type="radio" name="source" checked={source === option.value} onChange={() => setSource(option.value)}/><span><span className="choice-title">{option.title}</span><span className="choice-help" style={{display:'block'}}>{option.help}</span></span></label>
            {source === option.value && option.value === 'file' && <div className="choice-body"><input aria-label="Examples file" className="input" type="file" accept={DATA_FILES} onChange={e => setDataFile(e.target.files?.[0] ?? null)}/><span className="help" style={{marginTop:6}}>{DATA_HELP}</span></div>}
            {source === option.value && option.value === 'url' && <div className="choice-body"><input aria-label="Examples address" className="input" type="url" placeholder="https://" value={dataUrl} onChange={e => setDataUrl(e.target.value)}/></div>}
            {source === option.value && option.value === 'none' && <div className="choice-body"><textarea aria-label="Why no data is needed" className="input" rows={2} minLength={20} placeholder="For example: the answer is a calculation on values in the request." value={reason} onChange={e => setReason(e.target.value)}/><span className="help">The builder drafts test cases from the rules, and each one waits for your review before it counts.</span></div>}
          </div>)}
          {(source === 'file' || source === 'url') && <div className="grid grid-3" style={{marginTop:4}}><div className="field" style={{marginBottom:0}}><label htmlFor="development">Examples to build from</label><input id="development" className="input" type="number" min={1} max={2000} value={development} onChange={e => setDevelopment(Number(e.target.value))}/></div><div className="field" style={{marginBottom:0}}><label htmlFor="selection">Examples to check changes</label><input id="selection" className="input" type="number" min={0} max={2000} value={selection} onChange={e => setSelection(Number(e.target.value))}/></div><div className="field" style={{marginBottom:0}}><label htmlFor="validation">Examples held back</label><input id="validation" className="input" type="number" min={1} max={2000} value={validation} onChange={e => setValidation(Number(e.target.value))}/></div></div>}
        </fieldset>
        <div className="field"><label htmlFor="target">Score required for approval</label><input id="target" className="input" type="number" min={0} max={1} step=".01" style={{maxWidth:160}} value={budget.target_score} onChange={e => setBudget({...budget, target_score:Number(e.target.value)})}/><span className="help" style={{marginTop:0}}>The share of held-back examples the agent must get right, from 0 to 1. The build aims for it, and a version below it cannot be approved.</span></div>
        <div className="field"><label htmlFor="context">Business context <span className="muted" style={{fontWeight:400}}>(optional)</span></label><input id="context" className="input" type="file" multiple accept={DOCUMENT_FILES} onChange={e => setDocuments(Array.from(e.target.files ?? []))}/><span className="help" style={{marginTop:0}}>Policies, procedures and notes on how the business operates, as text or PDF files. Read by the builder only.</span></div>
        <div className="field"><label>Data connections <span className="muted" style={{fontWeight:400}}>(optional)</span></label><span className="help" style={{margin:'0 0 4px'}}>Systems the agent may read or prepare operations in. Leave empty for an agent that works from the request alone.</span><CollectionMore resource={integrations} label="connections"/>{connected.map(c=><label className="inline-check" key={c.id}><input type="checkbox" checked={selected.includes(c.id)} onChange={e=>setSelected(e.target.checked ? [...selected,c.id] : selected.filter(id=>id!==c.id))}/><span style={{flex:1}}>{c.name}<span className="help" style={{display:'block',marginTop:2}}>{c.kind} · {c.permissions.write ? 'Read, and writes after approval' : 'Read only'}</span></span><Badge value={c.status}/></label>)}{!connected.length && <Link className="link" href="/integrations">Connect a system</Link>}</div>
        <details><summary>Build limits</summary><div className="grid grid-2" style={{marginTop:14}}>{budgetFields.map(field=><div className="field" key={field.key}><label htmlFor={field.key}>{field.label}</label><input className="input" id={field.key} type="number" min={field.key==='target_score'?0:1} max={field.max} step={field.step ?? '1'} value={budget[field.key]} onChange={e=>setBudget({...budget,[field.key]:Number(e.target.value)})}/><span className="help" style={{marginTop:0}}>{field.help}</span></div>)}</div></details>
        <div className="notice" style={{margin:'16px 0'}}>Evaluations run in isolated fictional state. Production deployment requires review. Imported data is model-visible only after explicit authorization.</div>
        <Button disabled={pending || working || !ready}>{pending || working ? 'Creating agent…' : 'Create and start build'}</Button>
      </form></Card>
      <div className="stack">
        <Card><h2>Start from an example</h2><p className="muted small" style={{marginBottom:12}}>Fills in the request. Edit it before you start.</p><div className="template-list">{templates.map(t=><Button key={t.name} variant="secondary" className="full" style={{justifyContent:'space-between'}} onClick={()=>{setRequest(t.text);setSource('builtin');}}>{t.name}<ChevronRight size={14}/></Button>)}</div></Card>
        <Card><h2>New project</h2><p className="muted small" style={{marginBottom:12}}>Projects group agents with their evaluations and deployment history.</p><form onSubmit={async e=>{e.preventDefault();const created=await act<Project>('/projects',{name:projectName});if(created){setProject(created.id);setProjectName('');}}}><div className="field"><label htmlFor="project-name">Project name</label><input id="project-name" className="input" required value={projectName} onChange={e=>setProjectName(e.target.value)}/></div><Button variant="secondary" disabled={pending}><FolderPlus size={14}/>Create project</Button></form></Card>
        <Card><h2>What the build does</h2><ol className="steps-list">{['Discovers the tools each connection allows','Writes a versioned specification','Runs independent test scenarios','Diagnoses the failures it observes','Revises and compares candidates','Validates the best version on held-out cases'].map(step=><li key={step}>{step}</li>)}</ol></Card>
      </div>
    </div>
  </>;
}
