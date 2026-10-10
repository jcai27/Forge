import {test,expect} from '@playwright/test';

const topics=['card','loan','transfer','account'];
const rows=Array.from({length:40},(_,n)=>`${topics[n%4]} question number ${n},${topics[n%4]}`);
const csv=['text,category',...rows].join('\n');

test('give a build its task, business context and examples, with part of the data held back',async({page})=>{
  const rateLimited:string[]=[];
  page.on('response',response=>{if(response.status()===429)rateLimited.push(response.url());});
  await page.goto('/dashboard');
  await page.getByRole('button',{name:'Open local demo workspace'}).click();
  await expect(page.getByRole('heading',{name:'Overview'})).toBeVisible();
  await page.getByRole('link',{name:'Create agent',exact:true}).first().click();
  const start=page.getByRole('button',{name:'Create and start build'});
  await page.getByLabel('Business process').fill('Route each support ticket to the queue that handles its topic.');

  // Nothing to judge the agent against yet, so there is nothing to start.
  await expect(page.getByRole('radio',{name:/Upload examples/})).toBeChecked();
  await expect(start).toBeDisabled();
  await page.getByRole('radio',{name:/No data needed/}).check();
  await page.getByLabel('Why no data is needed').fill('too short');
  await expect(start).toBeDisabled();

  await page.getByRole('radio',{name:/Upload examples/}).check();
  await page.getByLabel('Examples file').setInputFiles({name:'support-tickets.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  await page.getByLabel('Examples to build from').fill('16');
  await page.getByLabel('Examples to check changes').fill('8');
  await page.getByLabel('Examples held back').fill('8');
  await page.getByLabel(/Business context/).setInputFiles({name:'routing-guide.md',mimeType:'text/markdown',buffer:Buffer.from('Card disputes always go to the card queue, even when a loan is mentioned.')});
  await expect(start).toBeEnabled();
  await start.click();

  // The agent, its document and its examples exist. This workspace is in demo mode, where an agent
  // without tools has nothing to run on, so the build is refused with the reason and the data is shown.
  await expect(page).toHaveURL(/\/agents\/[^/]+\/data/);
  await expect(page.getByRole('alert').filter({hasText:'needs a live model'})).toBeVisible();
  await expect(page.getByText('Examples with known answers',{exact:true})).toBeVisible();
  const dataset=page.getByRole('row').filter({hasText:'support-tickets'});
  await expect(dataset).toContainText('Upload');
  await expect(dataset).toContainText('category (4 values)');
  await expect(dataset.getByRole('cell').nth(3)).toHaveText('16');
  await expect(dataset.getByRole('cell').nth(4)).toHaveText('8');
  await expect(dataset.getByRole('cell').nth(5)).toHaveText('8');
  await expect(page.getByRole('row').filter({hasText:'routing-guide.md'})).toContainText('Card disputes always go to the card queue');

  // The examples are evaluation cases now, and the agent's answer is limited to the data's vocabulary.
  await page.getByRole('link',{name:'Evaluations',exact:true}).click();
  await expect(page.getByRole('heading',{name:/Scenario library/})).toContainText('32');
  await page.getByRole('link',{name:'Studio',exact:true}).click();
  await expect(page.getByText(/"enum"/).first()).toBeVisible();

  // The same file again brings in only the rows not yet used, and never moves one between the two sides.
  await page.getByRole('link',{name:'Data',exact:true}).click();
  await page.getByLabel('Examples file').setInputFiles({name:'again.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  await page.getByRole('button',{name:'Add examples'}).click();
  await expect(page.getByRole('alert').filter({hasText:'2 examples to build from, 2 to check changes and 2 held back'})).toBeVisible();
  await expect(page.getByRole('row').filter({hasText:'again'})).toContainText('32 already in suite left out');
  // What is left is too little to split again, and the refusal says so; a document can be removed.
  await page.getByLabel('Examples file').setInputFiles({name:'third.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  await page.getByRole('button',{name:'Add examples'}).click();
  await expect(page.getByRole('alert').filter({hasText:'too few usable rows'})).toBeVisible();
  await page.getByRole('button',{name:'Remove routing-guide.md'}).click();
  await expect(page.getByText('No documents attached')).toBeVisible();
  expect(rateLimited,'Browser interactions must stay within the API request limit').toEqual([]);
});
