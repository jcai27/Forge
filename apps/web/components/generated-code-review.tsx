'use client';
import type {GeneratedTool} from '../../../packages/contracts/src';

export function GeneratedCodeReview({tools,acknowledged,onChange}: {tools: GeneratedTool[]; acknowledged: string[]; onChange: (hashes: string[]) => void}) {
  if(!tools.length) return null;
  const toggle=(hash: string,checked: boolean)=>onChange(checked?[...new Set([...acknowledged,hash])]:acknowledged.filter(item=>item!==hash));
  return <section aria-labelledby="generated-code-heading" style={{margin:'20px 0'}}>
    <h3 id="generated-code-heading">Builder-written tool code</h3>
    <p className="help">This version contains code the builder wrote. It runs only in the sandbox, with no network or credentials, and can reach your systems only through the tools listed for it. Read each tool and confirm it before approving. Code you have already approved for this agent does not need confirming again.</p>
    {tools.map(tool=>{
      const id=`acknowledge-${tool.code_hash.slice(0,12)}`,reach=Object.keys(tool.capabilities);
      return <div key={tool.code_hash} style={{margin:'18px 0'}}>
        <div className="row between wrap"><strong>{tool.name}</strong><span className="muted small">sha256 {tool.code_hash.slice(0,12)}</span></div>
        <p className="muted small">{tool.description}</p>
        <p className="small">{reach.length?`Can call: ${reach.join(', ')}`:'Calls no other tool. Pure computation.'}</p>
        <pre className="code" tabIndex={0} aria-label={`Source code of ${tool.name}`} style={{maxHeight:320,overflow:'auto'}}>{tool.code}</pre>
        <label className="inline-check" htmlFor={id}><input id={id} type="checkbox" checked={acknowledged.includes(tool.code_hash)} onChange={event=>toggle(tool.code_hash,event.target.checked)}/>I have read {tool.name} and accept it for this agent</label>
      </div>;
    })}
  </section>;
}
