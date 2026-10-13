// A rehearsal of the operations demo, in a real browser against the running app.
//
//   bash demo/operations/reset.sh && (cd apps/web && node tests/demo/rehearse-operations.mjs)
//
// For each agent it uploads one of the documents kept for that (read by the live model), waits for it to be read
// and recorded, and checks that the page it fills now rests on more records than before. It fails if any request
// is refused or any page throws. It changes the demo exactly as a showing does: reset before the next one.
import {chromium} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const demo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../demo/operations');
const login = JSON.parse(fs.readFileSync(path.join(demo, '.login'), 'utf8'));
const base = process.env.DEMO_URL ?? 'http://localhost:3000', shots = process.env.DEMO_SHOTS;
// Agent as the customer names it, the folder its documents are in, the page it fills and that page's title.
const AGENTS = [
  ['Daily sales', 'till', 'sales', 'Sales'],
  ['Cash-up and banking', 'cashup', 'cash', 'Cash and banking'],
  ['Delivery payouts', 'payout', 'delivery', 'Delivery platforms'],
  ['Timesheets', 'timesheet', 'labour', 'Labour'],
  ['Stock counts', 'stockcount', 'inventory', 'Stock and food cost'],
  ['Catering quotes', 'enquiry', 'catering', 'Catering and events'],
  ['Licences and certificates', 'certificate', 'compliance', 'Compliance and upkeep'],
];

const browser = await chromium.launch(), context = await browser.newContext({viewport: {width: 1440, height: 900}}), page = await context.newPage();
const problems = [], started = Date.now();
page.on('pageerror', error => problems.push(`page error: ${error}`));
page.on('console', message => {if (message.type() === 'error') problems.push(`console: ${message.text()}`);});
page.on('response', response => {if (response.status() >= 400) problems.push(`${response.status()} ${response.request().method()} ${response.url()}`);});
const step = async (name, run) => {const from = Date.now(); const note = await run(); console.log(`ok  ${name}  (${((Date.now() - from) / 1000).toFixed(1)}s)${note ? `  ${note}` : ''}`); if (shots) await page.screenshot({path: path.join(shots, `${name.split(' ')[0]}.png`)});};
// How many of the records behind an area's page an agent wrote, asked of the API as the signed-in person.
const written = area => page.evaluate(async where => {
  const response = await fetch(`http://127.0.0.1:8000/portal/areas/${where}`, {headers: {Authorization: `Bearer ${localStorage.getItem('portal-token')}`}});
  return (await response.json()).from_agents;
}, area);

try {
  await step('0 sign in and see the dashboard', async () => {
    await page.goto(`${base}/portal`);
    await page.getByLabel('Email').fill(login.email); await page.getByLabel('Password').fill(login.password);
    await page.getByRole('button', {name: 'Sign in', exact: true}).click();
    await page.getByRole('heading', {name: 'Dashboard'}).waitFor(); await page.getByText('Needs attention').waitFor();
    await page.getByText('Sample data').first().waitFor();
  });
  let number = 0;
  for (const [agent, folder, area, title] of AGENTS) {
    number += 1;
    // The certificate uploaded is the renewed hood cleaning one, so the last step can see the expired one cleared.
    const files = fs.readdirSync(path.join(demo, 'data/live', folder)).filter(name => name.endsWith('.pdf')).sort(), file = files.find(name => name.includes('hood')) ?? files[0];
    await step(`${number} ${agent}: upload, read, recorded`, async () => {
      const before = await written(area);
      await page.getByRole('link', {name: 'Agents', exact: true}).click();
      await page.getByRole('link', {name: new RegExp(`^${agent}`)}).click();
      await page.getByRole('heading', {name: agent, exact: true}).waitFor();
      await page.locator('#portal-upload').setInputFiles(path.join(demo, 'data/live', folder, file));
      await page.getByRole('alert').filter({hasText: '1 read.'}).waitFor({timeout: 180000});
      await page.getByRole('link', {name: file}).click();
      await page.getByRole('heading', {name: 'What was read'}).waitFor();
      await page.getByRole('heading', {name: folder === 'enquiry' ? 'The quote' : 'Recorded', exact: true}).waitFor();
      const after = await written(area);
      if (!(after > before)) throw new Error(`${title} rests on ${after} agent-written records, as many as before (${before})`);
      await page.getByRole('link', {name: title, exact: true}).first().click();
      await page.locator('h1', {hasText: title}).waitFor();
      return `${file}: ${title} ${before} -> ${after} records`;
    });
  }
  await step('8 the renewed certificate clears the expired one', async () => {
    const gone = await page.evaluate(async () => {
      const response = await fetch('http://127.0.0.1:8000/portal/areas/compliance', {headers: {Authorization: `Bearer ${localStorage.getItem('portal-token')}`}});
      return !(await response.json()).alerts.some(alert => /hood cleaning certificate.*expired/.test(alert.text));
    });
    if (!gone) throw new Error('the expired hood cleaning certificate is still listed');
  });
} catch (error) {
  problems.push(String(error));
  if (shots) await page.screenshot({path: path.join(shots, 'failure.png')});
}
await browser.close();
console.log(`${((Date.now() - started) / 1000).toFixed(0)}s in all. ${problems.length ? `${problems.length} problem(s):\n  ${problems.join('\n  ')}` : 'No refused request, no page error.'}`);
process.exit(problems.length ? 1 : 0);
