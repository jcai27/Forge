'use client';
import {useResource} from '@/lib/api';
import {StoredPage} from './stored-page';
import {Card, humanize} from './shared';

type Row = Record<string, unknown>;
type Check = {path: string; expected: unknown; actual: unknown; passed: boolean; table: string | null; row: number | null; wrong: string[] | null};
type RunDocuments = {name: string | null; pages: Record<string, string[]>; checks: Check[]};

const shown = (value: unknown) => value === undefined || value === null || value === '' ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
const isTable = (value: unknown): value is Row[] => Array.isArray(value) && value.every(row => row !== null && typeof row === 'object' && !Array.isArray(row));

/** One table of the answer, such as an invoice's line items. For a test, each row is set against the row
 * expected in its place: a wrong cell shows what it should have been, and missing and unexpected rows are named. */
function AnswerTable({field, rows, checks}: {field: string; rows: Row[]; checks: Check[]}) {
  const expected = checks.filter(check => check.row !== null).sort((a, b) => (a.row ?? 0) - (b.row ?? 0));
  const extra = (checks.find(check => check.row === null)?.actual as Row[] | undefined) ?? [];
  const lines: {row: Row; want?: Row; wrong: string[]; state: 'plain' | 'right' | 'wrong' | 'missing' | 'extra'}[] = expected.length
    ? [...expected.map(check => {const answered = check.actual as Row | null; return {row: answered ?? {}, want: check.expected as Row, wrong: check.wrong ?? [], state: !answered ? 'missing' as const : check.passed ? 'right' as const : 'wrong' as const};}), ...extra.map(row => ({row, wrong: [], state: 'extra' as const}))]
    : rows.map(row => ({row, wrong: [], state: 'plain' as const}));
  const columns = Array.from(new Set(lines.flatMap(line => [...Object.keys(line.want ?? {}), ...Object.keys(line.row)])));
  const right = expected.filter(check => check.passed).length;
  return <div style={{marginTop:20}}>
    <h3 style={{marginBottom:4}}>{humanize(field)} · {rows.length} {rows.length === 1 ? 'row' : 'rows'}</h3>
    {expected.length > 0 && <p className="muted small" style={{marginBottom:8}}>{right} of {expected.length} expected rows right{extra.length ? `, ${extra.length} not expected` : ''}.</p>}
    <div className="table-wrap" style={{maxHeight:560,overflow:'auto'}}><table className="table" style={{fontSize:12.5}}><thead><tr>{columns.map(column => <th key={column} style={{padding:'6px 8px',whiteSpace:'nowrap'}}>{humanize(column)}</th>)}{expected.length > 0 && <th style={{padding:'6px 8px'}}>Result</th>}</tr></thead><tbody>{lines.map((line, index) => <tr key={index}>
      {columns.map(column => {const bad = line.state === 'missing' || line.wrong.includes(column), text = line.state === 'missing' ? shown(line.want?.[column]) : shown(line.row[column]); return <td key={column} className={bad ? 'fail' : undefined} title={text} style={{padding:'5px 8px',whiteSpace:'nowrap',maxWidth:210,overflow:'hidden',textOverflow:'ellipsis'}}>{text}{bad && line.state === 'wrong' && <div className="muted" style={{fontSize:11.5,fontWeight:400}}>should be {shown(line.want?.[column])}</div>}</td>;})}
      {expected.length > 0 && <td style={{padding:'5px 8px',whiteSpace:'nowrap'}} className={line.state === 'right' ? 'check' : 'fail'}>{line.state === 'right' ? 'Right' : line.state === 'wrong' ? 'Wrong' : line.state === 'missing' ? 'Missing' : 'Not expected'}</td>}
    </tr>)}</tbody></table></div>
  </div>;
}

/** The scanned document a run was given, beside what the agent answered and, for a test, what was expected. */
export function RunDocument({runId, output}: {runId: string; output: Record<string, unknown> | null}) {
  const documents = useResource<RunDocuments>(`/runs/${runId}/documents`);
  const pages = Object.entries(documents.data?.pages ?? {});
  if (!pages.length) return null;
  const checks = documents.data?.checks ?? [], single = checks.filter(check => !check.table), byPath = new Map(single.map(check => [check.path, check]));
  const tables = Array.from(new Set([...Object.keys(output ?? {}).filter(field => isTable(output?.[field])), ...checks.flatMap(check => check.table ? [check.table] : [])]));
  const fields = Array.from(new Set([...Object.keys(output ?? {}), ...single.map(check => check.path)])).filter(field => !tables.includes(field));
  const wrong = checks.filter(check => !check.passed).length;
  return <div style={{marginBottom:24}}><Card>
    <div className="row between wrap"><div><h2>Document and answer</h2><p className="muted small">{documents.data?.name ? `${documents.data.name}. ` : ''}The scanned pages the agent was given as text, and what it answered.{checks.length ? ` ${checks.length - wrong} of ${checks.length} checks against the expected answer passed.` : ''}</p></div></div>
    <div style={{display:'grid',gridTemplateColumns:'minmax(0, 5fr) minmax(0, 7fr)',gap:24,marginTop:16,alignItems:'start'}}>
      <div className="stack">{pages.map(([field, hashes]) => <div key={field}><h3 style={{marginBottom:8}}>{humanize(field)}{hashes.length > 1 ? ` · ${hashes.length} pages` : ''}</h3><div className="stack">{hashes.map((hash, index) => <StoredPage key={hash} path={`/document-pages/${hash}`} label={`${humanize(field)} page ${index + 1}`}/>)}</div></div>)}</div>
      <div style={{position:'sticky',top:16,minWidth:0}}><h3 style={{marginBottom:8}}>What the agent answered</h3>
        <div className="table-wrap"><table className="table"><thead><tr><th>Field</th><th>Answer</th>{single.length > 0 && <><th>Expected</th><th>Result</th></>}</tr></thead><tbody>{fields.map(field => {const check = byPath.get(field); return <tr key={field}><td>{humanize(field)}</td><td><b>{shown(output?.[field])}</b></td>{single.length > 0 && <><td>{check ? shown(check.expected) : '—'}</td><td className={check ? check.passed ? 'check' : 'fail' : 'muted'}>{check ? check.passed ? 'Right' : 'Wrong' : '—'}</td></>}</tr>;})}</tbody></table></div>
        {tables.map(field => <AnswerTable key={field} field={field} rows={isTable(output?.[field]) ? output[field] as Row[] : []} checks={checks.filter(check => check.table === field)}/>)}
        {!output && <p className="muted small" style={{marginTop:8}}>The run produced no answer.</p>}
      </div>
    </div>
  </Card></div>;
}
