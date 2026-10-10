import {test,expect} from '@playwright/test';

const API='http://127.0.0.1:8100';

test('review a release, compare in shadow, turn a real request into a test case and review builder drafts',async({page})=>{
  const rateLimited:string[]=[];
  page.on('response',response=>{if(response.status()===429)rateLimited.push(response.url());});
  await page.goto('/dashboard');
  await page.getByRole('button',{name:'Open local demo workspace'}).click();
  await expect(page.getByRole('heading',{name:'Your agent factory'})).toBeVisible();
  await page.getByRole('link',{name:'Create agent',exact:true}).first().click();
  await page.getByLabel('Project name',{exact:true}).fill('Builder review project');
  await page.getByRole('button',{name:'Create project',exact:true}).click();
  await expect(page.getByLabel('Project',{exact:true})).toContainText('Builder review project');
  await page.getByRole('button',{name:'Restaurant order entry'}).click();
  await page.getByRole('checkbox',{name:/Fictional Business ERP/}).check();
  await page.getByRole('button',{name:'Create and start build'}).click();
  await expect(page).toHaveURL(/\/agents\/[^/]+\/build/);
  const agentId=page.url().split('/agents/')[1].split('/')[0];
  await expect(page.getByRole('status',{name:'Build status'})).toHaveText('ready for review',{timeout:60000});
  const token=await page.evaluate(()=>localStorage.getItem('factory-token'));
  const headers={Authorization:`Bearer ${token}`};

  // Release dossier: reach, evidence and what is still open, before anything is approved.
  await page.getByRole('link',{name:'Deployments',exact:true}).click();
  const dossier=page.locator('.card').filter({has:page.getByRole('heading',{name:'Release dossier'})});
  await expect(dossier.getByText('Not yet approved by an administrator')).toBeVisible();
  await expect(dossier.getByRole('table',{name:'Connections this version can reach'})).toContainText('Fictional Business ERP');
  await expect(dossier.getByText(/Latest evaluation: 100% of \d+ results passed/)).toBeVisible();

  await page.getByRole('button',{name:'Approve candidate'}).click();
  await expect(page.getByRole('button',{name:'Deploy approved version'})).toBeEnabled();
  await page.getByRole('button',{name:'Deploy approved version'}).click();
  await expect(page.getByRole('button',{name:'Invoke agent'})).toBeEnabled();
  await expect(dossier.getByText('Nothing is open for this version.')).toBeVisible();

  // A real request the agent cannot fully handle becomes a reviewed test case.
  await page.getByLabel('Business request',{exact:true}).fill('Harbor Bistro: 2 kg unobtainium');
  await page.getByRole('button',{name:'Invoke agent'}).click();
  await expect(page).toHaveURL(/\/runs\//);
  await expect(page.getByText('needs attention',{exact:true})).toBeVisible();
  await page.getByText('Use this request as a test case',{exact:true}).click();
  await page.getByLabel('Scenario name',{exact:true}).fill('Unknown product is flagged, not guessed');
  await page.getByLabel('Correct result (assertions)',{exact:true}).fill('not json');
  await page.getByRole('checkbox',{name:/I authorize using this real request/}).check();
  await page.getByRole('button',{name:'Save as test case',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Enter the expected result as a JSON list'})).toBeVisible();
  await page.getByLabel('Correct result (assertions)',{exact:true}).fill('[{"path":"flags_count","op":"gte","value":1}]');
  await page.getByRole('button',{name:'Save as test case',exact:true}).click();
  await expect(page.getByText('Saved. The case will be used the next time this agent is evaluated.')).toBeVisible();
  const feedback=await (await page.request.get(`${API}/agents/${agentId}/feedback`,{headers})).json();
  expect(feedback.items[0].already_a_case).toBe(true);

  // Shadow comparison of an older, non-deployed version against the deployed one. Read-only.
  await page.goto(`/agents/${agentId}/deployments`);
  const select=page.getByLabel('Candidate version',{exact:true});
  // Wait for the versions to load before reading the options.
  await expect(select.locator('option').filter({hasText:/^v1 /})).toHaveCount(1);
  const first=(await select.locator('option').allTextContents()).find(text=>text.startsWith('v1 '));
  await select.selectOption({label:first!});
  await expect(dossier.getByText('No shadow comparison against the deployed version has been run')).toBeVisible();
  const approvalsBefore=(await (await page.request.get(`${API}/approvals`,{headers})).json()).total;
  await dossier.getByRole('button',{name:'Run shadow comparison'}).click();
  await expect(dossier.getByText(/of 1 recent real requests gave the same result/)).toBeVisible({timeout:20000});
  expect((await (await page.request.get(`${API}/approvals`,{headers})).json()).total).toBe(approvalsBefore);

  // Builder-written code is shown for review before it can be approved.
  const agent=await (await page.request.get(`${API}/agents/${agentId}`,{headers})).json();
  const spec=agent.latest_version.spec;
  const created=await page.request.post(`${API}/agents/${agentId}/versions`,{headers,data:{...spec,generated_tools:[{name:'count_lines',description:'Count the lines of a prepared order.',code:'def run(input, call):\n    return {"count": len(input.get("lines", []))}\n',capabilities:{}}]}});
  expect(created.status()).toBe(201);
  const withCode=await created.json();
  await page.reload();
  await expect(select.locator('option').filter({hasText:new RegExp(`^v${withCode.number} `)})).toHaveCount(1);
  const label=(await select.locator('option').allTextContents()).find(text=>text.startsWith(`v${withCode.number} `));
  await select.selectOption({label:label!});
  await expect(page.getByRole('heading',{name:'Builder-written tool code'})).toBeVisible();
  await expect(page.getByLabel('Source code of count_lines')).toContainText('def run(input, call):');
  await expect(page.getByText('Calls no other tool. Pure computation.')).toBeVisible();
  await expect(page.getByRole('checkbox',{name:/I have read count_lines/})).not.toBeChecked();
  await expect(dossier.getByText('Builder-written tool code has not been reviewed and acknowledged')).toBeVisible();
  const refused=await page.request.post(`${API}/agents/${agentId}/versions`,{headers,data:{...spec,generated_tools:[{name:'reads_files',description:'Tries to read a file.',code:'import os\ndef run(input, call):\n    return {}\n',capabilities:{}}]}});
  expect(refused.status()).toBe(400);

  // A drafted connection is inert until an administrator confirms its host.
  const draft=await page.request.post(`${API}/connection-proposals`,{headers,data:{name:'Vendor orders',agent_id:agentId,rationale:'Needs live order status',config:{base_url:'https://api.vendor.example',allowed_hosts:['api.vendor.example'],operations:[{name:'list_orders',description:'List recent orders.',path:'/v1/orders',method:'GET'}]}}});
  expect(draft.status()).toBe(201);
  await page.goto('/integrations');
  const proposal=page.getByRole('region',{name:'Proposed connection Vendor orders'});
  await expect(proposal).toContainText('api.vendor.example');
  await expect(proposal.getByRole('table',{name:'Operations proposed for Vendor orders'})).toContainText('GET /v1/orders');
  const approve=proposal.getByRole('button',{name:'Approve and connect'});
  await expect(approve).toBeDisabled();
  await proposal.getByLabel('Type the host to confirm it').fill('evil.example');
  await expect(approve).toBeDisabled();
  await proposal.getByLabel('Type the host to confirm it').fill('api.vendor.example');
  await expect(approve).toBeEnabled();
  await proposal.getByRole('button',{name:'Reject'}).click();
  await expect(proposal.getByText('rejected',{exact:true})).toBeVisible();
  await expect(proposal.getByRole('button',{name:'Approve and connect'})).toHaveCount(0);
  expect((await (await page.request.get(`${API}/integrations`,{headers})).json()).items.some((item:{name:string})=>item.name==='Vendor orders')).toBe(false);
  expect(rateLimited,'Browser interactions must stay within the API request limit').toEqual([]);
});
