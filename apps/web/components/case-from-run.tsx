'use client';
import {useState} from 'react';
import {Button} from './ui/button';
import {Card, useAction} from './shared';

export function CaseFromRun({runId}: {runId: string}) {
  const [name,setName]=useState(''),[split,setSplit]=useState('development'),[critical,setCritical]=useState(false),[authorized,setAuthorized]=useState(false);
  const [assertions,setAssertions]=useState('[\n  {"path": "", "value": ""}\n]'),[error,setError]=useState(''),[saved,setSaved]=useState(false);
  const {act,pending}=useAction();
  async function create() {
    let parsed:unknown;
    try {parsed=JSON.parse(assertions);}
    catch {setError('Enter the expected result as a JSON list of assertions.');return;}
    if(!Array.isArray(parsed)||!parsed.length){setError('Add at least one assertion describing the correct result.');return;}
    setError('');
    const created=await act(`/runs/${runId}/case`,{name,split,assertions:parsed,critical,authorize_data_use:authorized});
    if(created)setSaved(true);
  }
  return <Card className="mt-6"><details><summary>Use this request as a test case</summary>
    <p className="help" style={{marginTop:12}}>Turn a real request into a scenario the agent is tested against. You supply the correct result; the agent’s own answer is never used as the expectation.</p>
    {saved?<p className="small" role="status">Saved. The case will be used the next time this agent is evaluated.</p>:<form onSubmit={event=>{event.preventDefault();void create();}}>
      <div className="grid grid-2"><div className="field"><label htmlFor="case-name">Scenario name</label><input id="case-name" className="input" required maxLength={200} value={name} onChange={event=>setName(event.target.value)}/></div>
        <div className="field"><label htmlFor="case-split">Used for</label><select id="case-split" className="input" value={split} onChange={event=>setSplit(event.target.value)}><option value="development">Development: the builder can learn from it</option><option value="regression">Regression: must never break</option><option value="validation">Held-out: final check only</option></select></div></div>
      <div className="field"><label htmlFor="case-assertions">Correct result (assertions)</label><textarea id="case-assertions" className="input" rows={6} value={assertions} aria-invalid={Boolean(error)} aria-describedby={error?'case-assertions-error':'case-assertions-help'} onChange={event=>{setAssertions(event.target.value);setError('');}}/>
        <p className="help" id="case-assertions-help">Each assertion names a field path and the value it should have, for example {'{"path": "lines.0.sku", "value": "SKU-002"}'}.</p></div>
      {error&&<p id="case-assertions-error" className="error" role="alert">{error}</p>}
      <label className="inline-check" htmlFor="case-critical"><input id="case-critical" type="checkbox" checked={critical} onChange={event=>setCritical(event.target.checked)}/>Critical: a failure blocks promotion</label>
      <label className="inline-check" htmlFor="case-authorize"><input id="case-authorize" type="checkbox" checked={authorized} onChange={event=>setAuthorized(event.target.checked)}/>I authorize using this real request as test material</label>
      <Button disabled={pending||!authorized} style={{marginTop:14}}>Save as test case</Button>
      <p className="help">Administrators only. The decision is recorded in the audit log.</p>
    </form>}
  </details></Card>;
}
