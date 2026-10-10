'use client';
import {useState} from 'react';
import type {Invitation, Me, Member, Role} from '../../../packages/contracts/src';
import {useCollection} from '@/lib/api';
import {Button} from './ui/button';
import {Badge, Card, ErrorState, useAction} from './shared';

export function Memberships({me}:{me:Me}) {
  const [offset,setOffset]=useState(0),[invitationOffset,setInvitationOffset]=useState(0);
  const admin=me.role==='admin';
  const members=useCollection<Member>(`/organizations/members?offset=${offset}&limit=20`);
  const invitations=useCollection<Invitation>(`/organizations/invitations?offset=${invitationOffset}&limit=20`,admin);
  const [email,setEmail]=useState(''),[role,setRole]=useState<Role>('viewer'),[created,setCreated]=useState<(Invitation&{token:string})|null>(null);
  const [code,setCode]=useState('');
  const [workspace,setWorkspace]=useState(me.organization.id);
  const {act,pending}=useAction();
  async function invite() {
    const result=await act<Invitation&{token:string}>('/organizations/invitations',{email,role});
    if(result){setCreated(result);setEmail('');setInvitationOffset(0);}
  }
  async function accept() {
    const result=await act<{token:string}>('/organization-invitations/accept',{token:code});
    if(result){setCode('');localStorage.setItem('factory-token',result.token);window.location.assign('/dashboard');}
  }
  async function switchWorkspace() {
    const result=await act<{token:string}>('/auth/switch-organization',{org_id:workspace});
    if(result){localStorage.setItem('factory-token',result.token);window.location.assign('/dashboard');}
  }
  return <div className="stack mt-6">
    {me.memberships.length>1&&<Card><h2>Your workspaces</h2><form onSubmit={event=>{event.preventDefault();void switchWorkspace();}}><div className="field"><label htmlFor="workspace-selection">Workspace</label><select id="workspace-selection" className="input" value={workspace} onChange={event=>setWorkspace(event.target.value)}>{me.memberships.map(item=><option key={item.org_id} value={item.org_id}>{item.organization_name} · {item.role}</option>)}</select></div><Button disabled={pending||workspace===me.organization.id}>Switch workspace</Button></form></Card>}
    <Card><h2>Workspace members</h2><p className="help">Administrators manage access. Editors can build and run agents; viewers can inspect workspace evidence. Removing membership revokes existing workspace sessions.</p>
      <ErrorState error={members.error}/>
      <div style={{overflowX:'auto'}}><table className="table" aria-label="Workspace members"><thead><tr><th scope="col">Account</th><th scope="col">Role</th>{admin&&<th scope="col">Access</th>}</tr></thead>
        <tbody>{members.data?.items.map(member=><tr key={member.id}><td>{member.email}{member.user_id===me.user.id&&' (you)'}</td><td>{admin?<select className="input" aria-label={`Role for ${member.email}`} value={member.role} disabled={pending||member.user_id===me.user.id} onChange={event=>void act(`/organizations/members/${member.id}`,{role:event.target.value},'PATCH')}><option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Administrator</option></select>:<Badge value={member.role}/>}</td>{admin&&<td><Button variant="destructive" disabled={pending||member.user_id===me.user.id} onClick={()=>void act(`/organizations/members/${member.id}`,undefined,'DELETE')}>Remove {member.email}</Button></td>}</tr>)}</tbody>
      </table></div>
      <div className="row wrap"><Button variant="secondary" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous members</Button><Button variant="secondary" disabled={!members.data||offset+20>=members.data.total} onClick={()=>setOffset(offset+20)}>Next members</Button><span className="help">{members.data?.total??0} members</span></div>
    </Card>
    {admin&&<Card><h2>Invite a teammate</h2><p className="help">An invitation is tied to this email and expires after 72 hours. A replacement invalidates the previous code. The recipient must sign in with that email to accept.</p>
      <form onSubmit={event=>{event.preventDefault();void invite();}}>
        <div className="field"><label htmlFor="invitation-email">Teammate email</label><input id="invitation-email" className="input" type="email" required maxLength={320} value={email} onChange={event=>setEmail(event.target.value)}/></div>
        <div className="field"><label htmlFor="invitation-role">Invitation role</label><select id="invitation-role" className="input" value={role} onChange={event=>setRole(event.target.value as Role)}><option value="viewer">Viewer</option><option value="editor">Editor</option><option value="admin">Administrator</option></select></div>
        <Button disabled={pending}>Create invitation</Button>
      </form>
      {created&&<div className="notice" style={{marginTop:18}}><p>Invitation for {created.email}. Share this code privately with the recipient; it is shown only now and is not emailed automatically.</p><label htmlFor="created-invitation-code">New invitation code</label><input id="created-invitation-code" className="input" readOnly value={created.token} autoComplete="off"/><p>The recipient can accept it from Workspace settings after signing in.</p><Button variant="secondary" onClick={()=>setCreated(null)}>Dismiss invitation code</Button></div>}
      <h3 style={{marginTop:24}}>Invitation history</h3><ErrorState error={invitations.error}/>
      <div style={{overflowX:'auto'}}><table className="table" aria-label="Workspace invitations"><thead><tr><th scope="col">Recipient</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Expires</th><th scope="col">Action</th></tr></thead><tbody>{invitations.data?.items.map(invitation=><tr key={invitation.id}><td>{invitation.email}</td><td>{invitation.role}</td><td><Badge value={invitation.status}/></td><td>{new Date(invitation.expires_at).toLocaleString()}</td><td>{invitation.status==='pending'&&<Button variant="secondary" disabled={pending} onClick={()=>void act(`/organizations/invitations/${invitation.id}/revoke`,{})}>Revoke {invitation.email}</Button>}</td></tr>)}</tbody></table></div>
      <div className="row wrap"><Button variant="secondary" disabled={invitationOffset===0} onClick={()=>setInvitationOffset(Math.max(0,invitationOffset-20))}>Previous invitations</Button><Button variant="secondary" disabled={!invitations.data||invitationOffset+20>=invitations.data.total} onClick={()=>setInvitationOffset(invitationOffset+20)}>Next invitations</Button></div>
    </Card>}
    <Card><h2>Join an invited workspace</h2><p className="help">Sign in using the invited email address. Accepting switches to the invited workspace; your other memberships remain available at login.</p><form onSubmit={event=>{event.preventDefault();void accept();}}><div className="field"><label htmlFor="accept-invitation-code">Invitation code</label><input id="accept-invitation-code" className="input" type="password" required minLength={32} maxLength={128} autoComplete="off" value={code} onChange={event=>setCode(event.target.value)}/></div><Button disabled={pending}>Accept invitation and open workspace</Button></form></Card>
  </div>;
}
