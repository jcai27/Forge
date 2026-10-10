'use client';
import {useState} from 'react';
import type {ConnectionProposal} from '../../../packages/contracts/src';
import {usePagedCollection} from '@/lib/pagination';
import {Button} from './ui/button';
import {CollectionMore} from './collection-more';
import {Badge, Card, ErrorState, useAction} from './shared';

function Review({proposal}: {proposal: ConnectionProposal}) {
  const host=proposal.config.allowed_hosts[0]??'',writes=proposal.checks.write_operations??[];
  const [secret,setSecret]=useState(''),[typedHost,setTypedHost]=useState(''),[allowWrite,setAllowWrite]=useState(false),[attach,setAttach]=useState(true);
  const {act,pending}=useAction();
  const prefix=`proposal-${proposal.id.slice(0,8)}`;
  async function approve() {
    const done=await act(`/connection-proposals/${proposal.id}/approve`,{secret,allow_write:allowWrite,confirmed_hosts:[typedHost.trim()],attach});
    if(done)setSecret('');
  }
  return <form onSubmit={event=>{event.preventDefault();void approve();}} style={{marginTop:18}}>
    <div className="field"><label htmlFor={`${prefix}-host`}>Type the host to confirm it</label>
      <input id={`${prefix}-host`} className="input" required autoComplete="off" value={typedHost} onChange={event=>setTypedHost(event.target.value)} aria-describedby={`${prefix}-host-help`}/>
      <p className="help" id={`${prefix}-host-help`}>This connection will send your credential to <strong>{host}</strong> and nowhere else. Check it against the vendor’s own documentation before typing it.</p></div>
    <div className="field"><label htmlFor={`${prefix}-secret`}>Credential</label>
      <input id={`${prefix}-secret`} className="input" type="password" autoComplete="new-password" value={secret} onChange={event=>setSecret(event.target.value)}/>
      <p className="help">Encrypted at rest and sent as a bearer token. The builder never sees it.</p></div>
    {writes.length>0&&<label className="inline-check" htmlFor={`${prefix}-write`}><input id={`${prefix}-write`} type="checkbox" checked={allowWrite} onChange={event=>setAllowWrite(event.target.checked)}/>Allow approval-gated writes ({writes.join(', ')})</label>}
    {proposal.agent_id&&<label className="inline-check" htmlFor={`${prefix}-attach`}><input id={`${prefix}-attach`} type="checkbox" checked={attach} onChange={event=>setAttach(event.target.checked)}/>Add to the agent as a new version and re-evaluate it</label>}
    <div className="control-group" style={{marginTop:16}}>
      <Button disabled={pending||typedHost.trim()!==host}>Approve and connect</Button>
      <Button type="button" variant="destructive" disabled={pending} onClick={()=>void act(`/connection-proposals/${proposal.id}/reject`,{})}>Reject</Button>
    </div>
  </form>;
}

export function ConnectionProposals() {
  const proposals=usePagedCollection<ConnectionProposal>('/connection-proposals',true,5000);
  const items=proposals.data?.items??[];
  if(!items.length&&!proposals.error)return null;
  return <Card><h2>Proposed connections</h2>
    <p className="muted small">Drafts written by the builder or imported from an API description. A draft connects to nothing and holds no credential until you approve it.</p>
    <ErrorState error={proposals.error}/>
    {items.map(proposal=><section key={proposal.id} aria-label={`Proposed connection ${proposal.name}`} style={{margin:'24px 0'}}>
      <div className="row between wrap"><div className="row"><h3 style={{margin:0}}>{proposal.name}</h3><Badge value={proposal.status}/></div><span className="muted small">{proposal.origin==='builder'?'Drafted by the builder':proposal.origin==='openapi'?'Imported from OpenAPI':'Drafted manually'}</span></div>
      {proposal.rationale&&<p className="small" style={{marginTop:8}}>{proposal.rationale}</p>}
      <p className="small" style={{marginTop:8}}>Would reach <strong>{proposal.config.allowed_hosts.join(', ')}</strong> at {proposal.config.base_url}</p>
      <div style={{overflowX:'auto'}}><table className="table" aria-label={`Operations proposed for ${proposal.name}`}><thead><tr><th scope="col">Operation</th><th scope="col">Request</th><th scope="col">Access</th><th scope="col">Purpose</th></tr></thead>
        <tbody>{proposal.config.operations.map(operation=><tr key={operation.name}><td>{operation.name}</td><td className="trace-head">{operation.method??'GET'} {operation.path}</td><td><Badge value={(operation.method??'GET').toUpperCase()==='GET'?'read only':'approval required'}/></td><td>{operation.description}</td></tr>)}</tbody></table></div>
      {proposal.sources.length>0&&<details><summary>Public pages the builder read ({proposal.sources.length})</summary><ul className="small">{proposal.sources.map(source=><li key={source} style={{overflowWrap:'anywhere'}}>{source}</li>)}</ul><p className="help">Web content is untrusted. Confirm the host and operations against the vendor’s documentation yourself.</p></details>}
      {(proposal.checks.skipped?.length??0)>0&&<details><summary>Operations left out ({proposal.checks.skipped?.length})</summary><ul className="small">{proposal.checks.skipped?.map(entry=><li key={entry.operation}>{entry.operation}: {entry.reason}</li>)}</ul></details>}
      {proposal.status==='proposed'&&<Review proposal={proposal}/>}
    </section>)}
    <CollectionMore resource={proposals} label="proposals"/>
  </Card>;
}
