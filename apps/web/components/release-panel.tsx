'use client';
import {useState} from 'react';
import type {Dossier} from '../../../packages/contracts/src';
import {percent, useResource} from '@/lib/api';
import {Button} from './ui/button';
import {Badge, Card, ErrorState, useAction} from './shared';

export function ReleasePanel({versionId}: {versionId?: string}) {
  const dossier=useResource<Dossier>(versionId?`/versions/${versionId}/dossier`:'',!!versionId);
  const [liveReads,setLiveReads]=useState(false),{act,pending}=useAction();
  if(!versionId)return null;
  const data=dossier.data;
  const externalReach=data?.reach.connections.some(connection=>connection.kind!=='fixture')??false;
  return <Card><div className="row between wrap"><div><h2>Release dossier</h2><p className="muted small">What this version is, what it can reach, how it measured and what is still open.</p></div>{data&&<Badge value={data.open_items.length?'needs review':'ready'}/>}</div>
    <ErrorState error={dossier.error}/>
    {data&&<>
      <h3 style={{marginTop:20}}>Open items</h3>
      {data.open_items.length?<ul className="small">{data.open_items.map(item=><li key={item}>{item}</li>)}</ul>:<p className="small">Nothing is open for this version.</p>}
      <div className="grid grid-2" style={{marginTop:20}}>
        <div><h3>What it can reach</h3>
          <div style={{overflowX:'auto'}}><table className="table" aria-label="Connections this version can reach"><thead><tr><th scope="col">Connection</th><th scope="col">Hosts</th><th scope="col">Access</th></tr></thead>
            <tbody>{data.reach.connections.map(connection=><tr key={connection.name}><td>{connection.name}<span className="muted small"> · {connection.kind}</span></td><td style={{overflowWrap:'anywhere'}}>{connection.hosts.join(', ')||'internal'}</td><td><Badge value={connection.write_allowed?'approval required':'read only'}/></td></tr>)}</tbody></table></div>
          <p className="small" style={{marginTop:10}}>Tools: {data.reach.tools.map(tool=>tool.name).join(', ')||'none'}</p>
          {data.generated_code.length>0&&<p className="small">Builder-written tools: {data.generated_code.map(tool=>`${tool.name} (${tool.reviewed?'reviewed':'not yet reviewed'})`).join(', ')}</p>}
          {data.provenance.research_sources.length>0&&<details><summary>Public pages that informed it ({data.provenance.research_sources.length})</summary><ul className="small">{data.provenance.research_sources.map(source=><li key={source} style={{overflowWrap:'anywhere'}}>{source}</li>)}</ul></details>}
        </div>
        <div><h3>How it measured</h3>
          {data.evidence[0]?<><p className="small">Latest evaluation: {percent(data.evidence[0].score)} of {data.evidence[0].total} results passed{data.evidence[0].graded_score!==undefined&&data.evidence[0].graded_score!==null?`, ${percent(data.evidence[0].graded_score)} partial credit`:''}. Critical failures: {data.evidence[0].critical_failures}.</p><p className="help">Scores are pass rates on this agent’s own authored scenarios, not a claim of general accuracy.</p></>:<p className="small">No completed evaluation for this version yet.</p>}
          {data.known_failures.length>0&&<details><summary>Known failing scenarios ({data.known_failures.length})</summary><ul className="small">{data.known_failures.map(failure=><li key={`${failure.case}-${failure.split}`}>{failure.case} <span className="muted">({failure.split}: {failure.failed.join(', ')})</span></li>)}</ul></details>}
          <h3 style={{marginTop:18}}>Shadow comparison</h3>
          {data.shadow?<p className="small">{data.shadow.identical} of {data.shadow.compared} recent real requests gave the same result as the deployed version; {data.shadow.different.length} differed. Run read-only on {new Date(data.shadow.at).toLocaleString()}.</p>:<p className="small">Not run yet. It replays recent real requests through this version without writing anything, and compares the answers.</p>}
          {externalReach&&<label className="inline-check" htmlFor="shadow-live-reads"><input id="shadow-live-reads" type="checkbox" checked={liveReads} onChange={event=>setLiveReads(event.target.checked)}/>Allow read-only access to connected systems for this comparison</label>}
          <Button variant="secondary" disabled={pending||data.version.deployed} style={{marginTop:12}} onClick={()=>void act(`/versions/${versionId}/shadow`,{authorize_live_reads:liveReads})}>Run shadow comparison</Button>
        </div>
      </div>
    </>}
  </Card>;
}
