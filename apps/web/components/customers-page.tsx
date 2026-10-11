'use client';
import {useState} from 'react';
import {ArrowUpRight, Plus, UserPlus} from 'lucide-react';
import {api, useResource} from '@/lib/api';
import {Button} from './ui/button';
import {Badge, Card, Empty, ErrorState, Heading, Loading, useAction} from './shared';

type Customer = {id: string; name: string; created_at: string; operations: {id: string; name: string; enabled: boolean; source: {version?: number}}[]; documents: number; cost: number; customer_members: number};
type Installable = {deployment_id: string; agent: string; version: number};
type Invitation = {email: string; token: string; expires_at: string};

/** The builder's view of its customers: each has a workspace of its own, with agents put to work in it. */
export function Customers() {
  const customers = useResource<{items: Customer[]}>('/customers'), installable = useResource<{items: Installable[]}>('/customers/installable');
  const {act, pending, toast} = useAction(), [name, setName] = useState(''), [invited, setInvited] = useState<Invitation | null>(null);
  async function open(id: string) {const result = await api<{token: string}>('/auth/switch-organization', {org_id: id}); localStorage.setItem('factory-token', result.token); window.location.assign('/overview');}
  const items = customers.data?.items ?? [];
  return <>
    <Heading title="Customers" subtitle="Each customer has a workspace of its own. Put a deployed agent to work there, invite their people, and they see their documents and results in their portal."/>
    <ErrorState error={customers.error ?? installable.error}/>
    {invited && <div className="notice" style={{marginBottom:16}}><b>Invitation for {invited.email}. Send them this code privately; it is not shown again.</b><div style={{marginTop:8}}><code style={{wordBreak:'break-all'}}>{invited.token}</code></div><p className="small" style={{marginTop:8}}>They create an account or sign in with that email, open Settings, and enter the code under Join an invited workspace. It expires {new Date(invited.expires_at).toLocaleString()}.</p><Button variant="ghost" onClick={() => setInvited(null)}>Done</Button></div>}
    <Card><h2>Open a workspace for a customer</h2><form className="row" style={{gap:12,marginTop:12,alignItems:'flex-end'}} onSubmit={async event => {event.preventDefault(); if (await act('/customers', {name})) {setName(''); toast('Workspace opened.');}}}><div className="field" style={{flex:1,marginBottom:0}}><label htmlFor="customer-name">Customer name</label><input id="customer-name" className="input" required maxLength={200} value={name} onChange={event => setName(event.target.value)}/></div><Button disabled={pending}><Plus size={15}/>Open workspace</Button></form></Card>
    <div className="stack" style={{marginTop:24}}>{customers.isLoading ? <Loading/> : items.length ? items.map(customer => <CustomerCard key={customer.id} customer={customer} installable={installable.data?.items ?? []} open={open} onInvited={setInvited}/>) : <Card><Empty title="No customers yet">Open a workspace for your first customer above.</Empty></Card>}</div>
  </>;
}

function CustomerCard({customer, installable, open, onInvited}: {customer: Customer; installable: Installable[]; open: (id: string) => Promise<void>; onInvited: (invitation: Invitation) => void}) {
  const {act, pending, toast} = useAction(), [deployment, setDeployment] = useState(''), [label, setLabel] = useState(''), [email, setEmail] = useState('');
  const chosen = deployment || installable[0]?.deployment_id || '';
  return <Card>
    <div className="row between wrap"><div><h2>{customer.name}</h2><p className="muted small">Opened {new Date(customer.created_at).toLocaleDateString()} · {customer.documents} documents · ${customer.cost.toFixed(2)} of model spend · {customer.customer_members} of their people have joined</p></div><Button variant="secondary" onClick={() => void open(customer.id)}><ArrowUpRight size={14}/>Open their portal</Button></div>
    {customer.operations.length ? <div className="table-wrap" style={{marginTop:12}}><table className="table"><thead><tr><th>Work</th><th>Installed from</th><th>State</th><th aria-label="Actions"/></tr></thead><tbody>{customer.operations.map(operation => <tr key={operation.id}><td><b>{operation.name}</b></td><td className="muted">version {operation.source.version ?? '—'}</td><td><Badge value={operation.enabled ? 'connected' : 'paused'}/></td><td><Button variant="secondary" disabled={pending} onClick={() => void act(`/customers/${customer.id}/operations/${operation.id}`, {enabled: !operation.enabled}, 'PATCH')}>{operation.enabled ? 'Pause' : 'Resume'}</Button></td></tr>)}</tbody></table></div> : <p className="muted small" style={{marginTop:12}}>No agent is working here yet.</p>}
    <div className="grid grid-2" style={{marginTop:16}}>
      <form onSubmit={async event => {event.preventDefault(); if (await act(`/customers/${customer.id}/operations`, {deployment_id: chosen, name: label})) {setLabel(''); toast('Agent installed in their workspace.');}}}>
        <h3 style={{marginBottom:8}}>Put an agent to work</h3>
        {installable.length ? <><div className="field"><label htmlFor={`deployment-${customer.id}`}>Deployed agent</label><select id={`deployment-${customer.id}`} className="input" value={chosen} onChange={event => setDeployment(event.target.value)}>{installable.map(item => <option key={item.deployment_id} value={item.deployment_id}>{item.agent} · version {item.version}</option>)}</select></div>
          <div className="field"><label htmlFor={`label-${customer.id}`}>What the customer calls this work</label><input id={`label-${customer.id}`} className="input" required maxLength={200} placeholder="Supplier invoices" value={label} onChange={event => setLabel(event.target.value)}/></div>
          <Button variant="secondary" disabled={pending}>Install</Button><span className="help" style={{marginLeft:12}}>A copy of the approved version. None of your examples go with it.</span></> : <p className="muted small">Nothing can be installed yet. It needs an active deployment of an approved agent that takes one document as its request.</p>}
      </form>
      <form onSubmit={async event => {event.preventDefault(); const made = await act<Invitation>(`/customers/${customer.id}/invitations`, {email}); if (made) {setEmail(''); onInvited(made);}}}>
        <h3 style={{marginBottom:8}}>Invite one of their people</h3>
        <div className="field"><label htmlFor={`invite-${customer.id}`}>Their email</label><input id={`invite-${customer.id}`} className="input" type="email" required value={email} onChange={event => setEmail(event.target.value)}/></div>
        <Button variant="secondary" disabled={pending}><UserPlus size={14}/>Create invitation</Button><span className="help" style={{marginLeft:12}}>They get the portal only: documents, results, channels.</span>
      </form>
    </div>
  </Card>;
}
