'use client';
import {useState} from 'react';
import {FileText, Trash2, Upload} from 'lucide-react';
import type {Agent, ContextDocument, Dataset} from '../../../packages/contracts/src';
import {usePagedCollection} from '@/lib/pagination';
import {Button} from './ui/button';
import {CollectionMore} from './collection-more';
import {Badge, Card, Empty, ErrorState, useAction} from './shared';

export const DATA_FILES = '.csv,.tsv,.json,.jsonl,.ndjson,.txt';
export const DOCUMENT_FILES = '.txt,.md,.markdown,.csv,.json,.yaml,.yml,.html';
const MAX_FILE_BYTES = 5_000_000;

/** Files are read in the browser and sent as text; the server stores no upload it has not parsed. */
export async function readText(file: File) {
  if (file.size > MAX_FILE_BYTES) throw new Error(`${file.name} is larger than 5 MB.`);
  return file.text();
}
export function datasetName(source: string) {
  const last = source.split(/[\\/]/).filter(Boolean).pop() ?? 'Examples';
  return (last.split('?')[0].replace(/\.[a-z0-9]+$/i, '') || 'Examples').slice(0, 120);
}
export function datasetBody(source: 'file' | 'url', content: string, url: string, name: string, development: number, selection: number, validation: number) {
  return {name, development, selection, validation, ...(source === 'file' ? {content} : {url})};
}

export function DataPanel({agent}: {agent: Agent}) {
  const datasets = usePagedCollection<Dataset>(`/agents/${agent.id}/datasets`), documents = usePagedCollection<ContextDocument>(`/agents/${agent.id}/context`);
  const {act, pending, toast} = useAction();
  const [source, setSource] = useState<'file' | 'url'>('file'), [file, setFile] = useState<File | null>(null), [url, setUrl] = useState(''), [development, setDevelopment] = useState(60), [selection, setSelection] = useState(60), [validation, setValidation] = useState(60);
  const building = agent.builds?.some(build => !['READY_FOR_REVIEW', 'DEPLOYED', 'FAILED', 'CANCELLED', 'BUDGET_EXHAUSTED','BELOW_TARGET'].includes(build.state)) ?? false;
  async function attach() {
    try {
      const content = source === 'file' && file ? await readText(file) : '';
      const made = await act<Dataset>(`/agents/${agent.id}/datasets`, datasetBody(source, content, url, datasetName(source === 'file' ? file?.name ?? '' : url), development, selection, validation));
      if (made) {setFile(null); setUrl(''); toast(`${made.profile.splits.development} examples to build from, ${made.profile.splits.selection ?? 0} to check changes and ${made.profile.splits.validation} held back.`);}
    } catch (error) {toast(error instanceof Error ? error.message : 'The file could not be read.');}
  }
  async function addDocuments(files: FileList | null) {
    for (const item of Array.from(files ?? [])) {
      try {if (!await act(`/agents/${agent.id}/context`, {name: item.name.slice(0, 200), text: await readText(item)})) return;}
      catch (error) {toast(error instanceof Error ? error.message : 'The file could not be read.'); return;}
    }
  }
  const basis = agent.truth_source === 'cases' ? 'Examples with known answers' : agent.truth_source === 'rules' ? 'Stated as checkable without data' : 'Nothing yet';
  return <div className="stack">
    <ErrorState error={datasets.error ?? documents.error}/>
    <Card>
      <div className="row between wrap"><div><h2>Source of truth</h2><p className="muted small">What a build of this agent is judged against. The builder reads the examples it builds from. Each change it makes is scored on a second set it never reads, and a third is held back for the final result.</p></div><Badge value={agent.truth_source ? 'ready' : 'needs data'}/></div>
      <dl className="dl" style={{marginTop:12}}><dt>Judged against</dt><dd>{basis}</dd>{agent.no_data_reason && <><dt>Stated reason</dt><dd>{agent.no_data_reason}</dd></>}</dl>
      {datasets.data?.items.length ? <div className="table-wrap" style={{marginTop:12}}><table className="table"><thead><tr><th>Dataset</th><th>Origin</th><th className="num">Rows</th><th className="num">To build from</th><th className="num">To check changes</th><th className="num">Held back</th><th>Answer field</th><th>Added</th><th aria-label="Remove"/></tr></thead><tbody>{datasets.data.items.map(dataset => <tr key={dataset.id}><td><b>{dataset.name}</b>{Object.values(dataset.profile.dropped).some(Boolean) && <div className="cell-sub">{Object.entries(dataset.profile.dropped).map(([reason, count]) => `${count} ${reason.replaceAll('_', ' ')}`).join(' · ')} left out</div>}</td><td>{dataset.origin === 'url' ? 'Web address' : 'Upload'}</td><td className="num">{dataset.rows.toLocaleString()}</td><td className="num">{dataset.profile.splits.development}</td><td className="num">{dataset.profile.splits.selection ?? 0}</td><td className="num">{dataset.profile.splits.validation}</td><td>{dataset.profile.expected_fields.map(field => `${field}${dataset.profile.answers[field] ? ` (${dataset.profile.answers[field].length} values)` : ''}`).join(', ')}</td><td className="muted">{new Date(dataset.created_at).toLocaleDateString()}</td><td className="num"><Button variant="ghost" className="icon" aria-label={`Remove ${dataset.name}`} title="Remove this dataset, its test cases and every result measured on them" disabled={pending || building} onClick={() => {if (window.confirm(`Remove ${dataset.name}? Its test cases and the results measured on them are deleted, and earlier versions must be evaluated again.`)) void act(`/datasets/${dataset.id}`, undefined, 'DELETE');}}><Trash2 size={14}/></Button></td></tr>)}</tbody></table></div> : <Empty title="No examples attached">Add a file of real requests with their correct answers.</Empty>}
      <CollectionMore resource={datasets} label="datasets"/>
      <div className="separator"/>
      <h3>Add examples</h3>
      <form onSubmit={event => {event.preventDefault(); void attach();}}>
        <div className="control-group" style={{margin:'8px 0 12px'}} role="radiogroup" aria-label="Where the examples are">{([['file', 'Upload a file'], ['url', 'Web address']] as const).map(([value, label]) => <label className="inline-check" key={value} style={{margin:0}}><input type="radio" name="data-source" checked={source === value} onChange={() => setSource(value)}/>{label}</label>)}</div>
        {source === 'file' ? <div className="field"><label htmlFor="data-file">Examples file</label><input id="data-file" className="input" type="file" accept={DATA_FILES} onChange={event => setFile(event.target.files?.[0] ?? null)}/><span className="help" style={{marginTop:0}}>CSV, TSV, JSON or JSON Lines, up to 5 MB. One row per example, with a column holding the correct answer.</span></div> : <div className="field"><label htmlFor="data-url">Examples address</label><input id="data-url" className="input" type="url" placeholder="https://" value={url} onChange={event => setUrl(event.target.value)}/><span className="help" style={{marginTop:0}}>A public https address that serves the file directly.</span></div>}
        <div className="grid grid-3"><div className="field"><label htmlFor="data-development">Examples to build from</label><input id="data-development" className="input" type="number" min={1} max={2000} value={development} onChange={event => setDevelopment(Number(event.target.value))}/></div><div className="field"><label htmlFor="data-selection">Examples to check changes</label><input id="data-selection" className="input" type="number" min={0} max={2000} value={selection} onChange={event => setSelection(Number(event.target.value))}/></div><div className="field"><label htmlFor="data-validation">Examples held back</label><input id="data-validation" className="input" type="number" min={1} max={2000} value={validation} onChange={event => setValidation(Number(event.target.value))}/></div></div>
        <Button variant="secondary" disabled={pending || building || (source === 'file' ? !file : !url)}><Upload size={14}/>Add examples</Button>
        {building && <span className="help" style={{marginLeft:12}}>Data cannot change while a build is running.</span>}
      </form>
    </Card>
    <Card>
      <h2>Business context</h2><p className="muted small">Documents about how this business operates: policies, procedures, terms. The builder reads them; the deployed agent is given only what the builder writes into its instructions.</p>
      {documents.data?.items.length ? <div className="table-wrap" style={{marginTop:12}}><table className="table"><thead><tr><th>Document</th><th className="num">Characters</th><th>Added</th><th aria-label="Remove"/></tr></thead><tbody>{documents.data.items.map(document => <tr key={document.id}><td><div className="row" style={{gap:10,alignItems:'flex-start'}}><FileText size={15} className="muted" style={{marginTop:3,flex:'none'}}/><div style={{minWidth:0}}><b>{document.name}</b><div className="cell-sub">{document.excerpt}</div></div></div></td><td className="num">{document.chars.toLocaleString()}</td><td className="muted">{new Date(document.created_at).toLocaleDateString()}</td><td className="num"><Button variant="ghost" className="icon" aria-label={`Remove ${document.name}`} disabled={pending} onClick={() => void act(`/context/${document.id}`, undefined, 'DELETE')}><Trash2 size={14}/></Button></td></tr>)}</tbody></table></div> : <Empty title="No documents attached">Add what the customer told you about how they work.</Empty>}
      <CollectionMore resource={documents} label="documents"/>
      <div className="field" style={{marginTop:16,marginBottom:0}}><label htmlFor="context-files">Add documents</label><input id="context-files" className="input" type="file" multiple accept={DOCUMENT_FILES} disabled={pending} onChange={event => {void addDocuments(event.target.files); event.target.value = '';}}/><span className="help" style={{marginTop:0}}>Plain text, Markdown, CSV or JSON, up to 200,000 characters each. Convert PDF and Word files to text first. Known credentials are removed before a document is stored.</span></div>
    </Card>
  </div>;
}
