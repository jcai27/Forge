'use client';
import {useState} from 'react';
import type {Json} from '../../../packages/contracts/src';
import {Button} from './ui/button';
import {Card, useAction} from './shared';

export function TestProposals({jobId,proposal}: {jobId: string; proposal: Json}) {
  const [draft,setDraft]=useState(()=>JSON.stringify(proposal,null,2)), {act,pending,toast}=useAction();
  async function accept() {
    try {const parsed:unknown=JSON.parse(draft); await act(`/builds/${jobId}/test-proposals/accept`,parsed);}
    catch {toast('Enter a valid proposed test plan.');}
  }
  return <Card><h2>Review proposed evaluation cases</h2><p className="help">The Test Designer proposed synthetic expectations. Independently verify and correct them before accepting. The worker will then test the agent; these proposals do not count as evidence until execution and grading. Keep development, regression and held-out scenarios separate.</p><div className="field"><label htmlFor="test-proposals-json">Proposed test plan</label><textarea id="test-proposals-json" className="input" rows={20} value={draft} onChange={event=>setDraft(event.target.value)}/></div><Button disabled={pending} onClick={()=>void accept()}>Accept corrected cases and resume</Button><p className="help">Administrator review is required. Approval here authorizes isolated evaluation cases; business side effects retain their normal approval gates.</p></Card>;
}
