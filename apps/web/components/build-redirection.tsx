'use client';
import {useState} from 'react';
import type {Version} from '../../../packages/contracts/src';
import {Button} from './ui/button';
import {Card, useAction} from './shared';

export function BuildRedirection({jobId,version}: {jobId: string; version: Version}) {
  const [reason,setReason]=useState(''), [draft,setDraft]=useState(()=>JSON.stringify(version.spec,null,2));
  const {act,pending,toast}=useAction();
  async function redirect() {
    let spec:unknown;
    try {spec=JSON.parse(draft);} catch {toast('Enter a valid agent configuration.');return;}
    await act(`/builds/${jobId}/redirect`,{expected_version_id:version.id,reason,spec});
  }
  return <Card><details><summary>Redirect this build</summary><p className="help">Revise the configuration and explain the change. This creates an immutable version and restarts evaluation with the remaining time, cost and iteration budgets. Previous evidence stays in history. Review the scenario library to ensure its expectations cover your revised requirements.</p><form onSubmit={event=>{event.preventDefault();void redirect();}}><div className="field"><label htmlFor="redirect-reason">Redirection reason</label><textarea id="redirect-reason" className="input" value={reason} onChange={event=>setReason(event.target.value)} minLength={10} maxLength={4000} required/></div><div className="field"><label htmlFor="redirect-spec">Revised build configuration</label><textarea id="redirect-spec" className="input" rows={18} value={draft} onChange={event=>setDraft(event.target.value)} required/></div><Button disabled={pending}>Save revision and redirect build</Button></form></details></Card>;
}
