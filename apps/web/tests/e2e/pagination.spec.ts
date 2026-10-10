import {test,expect} from '@playwright/test';

test('reach older agents and select projects and integrations beyond the first page',async({page})=>{
  const rateLimited:string[]=[];
  page.on('response',response=>{if(response.status()===429)rateLimited.push(response.url());});
  await page.goto('/dashboard');
  await page.getByLabel('Email',{exact:true}).fill('pagination-fixture@example.invalid');
  await page.getByLabel('Password',{exact:true}).fill('local-pagination-fixture-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your agent factory'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Collection Agent 000',exact:true})).toHaveCount(0);
  await expect(page.getByText('Showing 50 of 53 agents',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Load more agents',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Collection Agent 000',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Load more agents',exact:true})).toHaveCount(0);
  await page.getByRole('heading',{name:'Collection Agent 000',exact:true}).click();
  await page.getByRole('link',{name:'Evaluations',exact:true}).click();
  await expect(page.getByLabel('Evaluation suite')).not.toContainText('Collection Suite 000');
  await page.getByRole('button',{name:'Load more suites',exact:true}).click();
  await page.getByLabel('Evaluation suite').selectOption({label:'Collection Suite 000'});
  await expect(page.getByRole('heading',{name:/Scenario library/})).toContainText('0');
  await page.getByText('Import an authored evaluation case',{exact:true}).click();
  await page.getByLabel('Evaluation case JSON').fill(JSON.stringify({name:'Older suite catalog check',split:'development',source:'synthetic',input:{text:'Harbor Bistro: 2 kg Tomatoes'},assertions:[{path:'total_cents',op:'equals',value:900}]}));
  await page.getByRole('button',{name:'Add case',exact:true}).click();
  await expect(page.getByRole('heading',{name:/Scenario library/})).toContainText('1');
  await page.getByRole('button',{name:'Retest latest',exact:true}).click();
  await expect(page.locator('summary').filter({hasText:'Older suite catalog check'})).toBeVisible();
  await page.getByLabel('Evaluation suite').selectOption({label:'Collection Suite 052'});
  await expect(page.getByRole('heading',{name:/Scenario library/})).toContainText('0');
  await expect(page.locator('summary').filter({hasText:'Older suite catalog check'})).toHaveCount(0);
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await expect(page.getByRole('button',{name:'Load more audit records',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Load more audit records',exact:true}).click();
  await expect(page.getByRole('button',{name:'Load more audit records',exact:true})).toHaveCount(0);
  await page.getByRole('link',{name:'Create agent',exact:true}).first().click();
  await page.getByRole('button',{name:'Restaurant order entry'}).click();
  await expect(page.getByLabel('Project',{exact:true})).not.toContainText('Collection Project 000');
  await page.getByRole('button',{name:'Load more projects',exact:true}).click();
  await expect(page.getByLabel('Project',{exact:true})).toContainText('Collection Project 000');
  await page.getByLabel('Project',{exact:true}).selectOption({label:'Collection Project 000'});
  await expect(page.getByRole('checkbox',{name:/Collection Connection 000/})).toHaveCount(0);
  await page.getByRole('button',{name:'Load more connections',exact:true}).click();
  await page.getByRole('checkbox',{name:/Collection Connection 000/}).check();
  await expect(page).toHaveURL(/\/agents\/new$/);
  const selectedProject=await page.getByLabel('Project',{exact:true}).inputValue();
  await page.getByRole('button',{name:'Create and start build'}).click();
  await expect(page).toHaveURL(/\/agents\/[^/]+\/build/);
  await expect(page.getByRole('status',{name:'Build status'})).toHaveText('ready for review',{timeout:60000});
  // The build timeline is paged and refreshes on a poll, so its "Load more" control appears a moment
  // after the build finishes. Wait for it, then load every page. While a page is being fetched the
  // button reads "Loading…", so wait for the count to change rather than for the button to vanish.
  const shown=page.getByText(/^Showing \d+ of \d+ build events$/);
  await expect(shown).toBeVisible({timeout:15000});
  for(let pages=0;pages<20;pages++) {
    if(await shown.count()===0)break;
    const before=await shown.textContent();
    await page.getByRole('button',{name:'Load more build events',exact:true}).click();
    await expect(page.getByText(before!,{exact:true})).toHaveCount(0);
  }
  await expect(page.getByText('requirements analyzed',{exact:true})).toBeVisible();
  const id=page.url().split('/agents/')[1].split('/')[0];
  const token=await page.evaluate(()=>localStorage.getItem('factory-token'));
  const agent=await (await page.request.get(`http://127.0.0.1:8100/agents/${id}`,{headers:{Authorization:`Bearer ${token}`}})).json();
  expect(agent.project_id).toBe(selectedProject);
  expect(agent.latest_version.spec.connection_ids).toHaveLength(1);
  expect(rateLimited).toEqual([]);
});
