'use client';
import {useMemo, useState} from 'react';
import type {Json} from '../../../packages/contracts/src';
import {Button} from './ui/button';
import {Card, useAction} from './shared';

function record(value: unknown): value is Record<string,unknown> {
  return typeof value==='object'&&value!==null&&!Array.isArray(value);
}

export function TestProposals({jobId,proposal}: {jobId: string; proposal: Json}) {
  const [draft,setDraft]=useState(()=>JSON.stringify(proposal,null,2));
  const [error,setError]=useState('');
  const {act,pending}=useAction();
  const cases=useMemo(()=>{
    try {
      const plan:unknown=JSON.parse(draft);
      return record(plan)&&Array.isArray(plan.cases)?plan.cases.filter(record):[];
    } catch {return [];}
  },[draft]);
  async function accept() {
    let parsed:unknown;
    try {parsed=JSON.parse(draft);}
    catch {setError('Enter a valid proposed test plan.');return;}
    setError('');
    await act(`/builds/${jobId}/test-proposals/accept`,parsed);
  }
  return <Card>
    <h2>Review proposed evaluation cases</h2>
    <p className="help">The Test Designer proposed synthetic expectations. Independently verify and correct them before accepting. The worker will then test the agent; these proposals do not count as evidence until execution and grading. Keep development, regression and held-out scenarios separate.</p>
    {cases.length>0&&<div style={{overflowX:'auto',margin:'20px 0'}}>
      <table aria-label="Proposed scenario summary"><thead><tr><th scope="col">Scenario</th><th scope="col">Split</th><th scope="col">Critical</th><th scope="col">Assertions</th></tr></thead>
        <tbody>{cases.map((item,index)=><tr key={index}>
          <td>{typeof item.name==='string'?item.name:'Unnamed scenario'}</td>
          <td>{typeof item.split==='string'?item.split:'Unspecified'}</td>
          <td>{item.critical===true?'Yes':'No'}</td>
          <td>{Array.isArray(item.assertions)?item.assertions.length:0}</td>
        </tr>)}</tbody>
      </table>
      <p className="help">{cases.length} proposed scenarios. This summary follows your edits; acceptance still requires server validation and administrator review.</p>
    </div>}
    <div className="field"><label htmlFor="test-proposals-json">Proposed test plan</label>
      <textarea id="test-proposals-json" className="input" rows={20} value={draft} aria-invalid={Boolean(error)} aria-describedby={error?'test-proposals-error':undefined} onChange={event=>{setDraft(event.target.value);setError('');}}/>
    </div>
    {error&&<p id="test-proposals-error" className="error" role="alert">{error}</p>}
    <Button disabled={pending} onClick={()=>void accept()}>Accept corrected cases and resume</Button>
    <p className="help">Administrator review is required. Approval here authorizes isolated evaluation cases; business side effects retain their normal approval gates.</p>
  </Card>;
}
