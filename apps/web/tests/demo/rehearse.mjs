// A rehearsal of the restaurant demo call, in a real browser against the running app.
//
//   bash demo/restaurant/reset.sh && (cd apps/web && node tests/demo/rehearse.mjs)
//
// It walks the seven steps of demo/restaurant/CALL.md as a person would, uploads one of the invoices kept for
// that (read by the live model, a fraction of a cent), and fails if any request is refused or any page throws.
// It changes the demo exactly as a showing does: reset before the next one.
import {chromium} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const demo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../demo/restaurant');
const login = JSON.parse(fs.readFileSync(path.join(demo, '.login'), 'utf8'));
const base = process.env.DEMO_URL ?? 'http://localhost:3000';
const upload = path.join(demo, 'data/live', process.env.DEMO_UPLOAD ?? 'GFS invoice 132029719.pdf');
const shots = process.env.DEMO_SHOTS;

const browser = await chromium.launch(), context = await browser.newContext({viewport: {width: 1440, height: 900}, acceptDownloads: true}), page = await context.newPage();
const problems = [], started = Date.now();
page.on('pageerror', error => problems.push(`page error: ${error}`));
page.on('console', message => {if (message.type() === 'error') problems.push(`console: ${message.text()}`);});
page.on('response', response => {if (response.status() >= 400) problems.push(`${response.status()} ${response.request().method()} ${response.url()}`);});
const seen = text => page.getByText(text).first().waitFor({timeout: 30000});
const step = async (name, run) => {const from = Date.now(); await run(); console.log(`ok  ${name}  (${((Date.now() - from) / 1000).toFixed(1)}s)`); if (shots) await page.screenshot({path: path.join(shots, `${name.slice(0, 1)}.png`)});};

try {
  await step('1 sign in and see the dashboard', async () => {
    await page.goto(`${base}/portal`);
    await page.getByLabel('Email').fill(login.email); await page.getByLabel('Password').fill(login.password);
    await page.getByRole('button', {name: 'Sign in', exact: true}).click();
    await page.getByRole('heading', {name: 'Dashboard'}).waitFor(); await seen('What you bought');
  });
  await step('2 open an invoice: the scan beside its lines', async () => {
    await page.getByRole('link', {name: 'Supplier invoices', exact: true}).first().click();
    await page.getByRole('link', {name: 'GFS invoice 820141051.pdf'}).click();
    await page.getByRole('heading', {name: 'What was read'}).waitFor();
    await page.getByRole('button', {name: /^Enlarge/}).first().click();
    await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({state: 'detached'});
  });
  await step('3 the invoice held for a person, and putting it right', async () => {
    await page.getByRole('link', {name: 'Supplier invoices', exact: true}).first().click();
    await page.getByRole('tab', {name: /Needs a person/}).click();
    await page.getByRole('link', {name: /^GFS invoice/}).first().click();
    await seen('This needs a person before it is approved');
    await page.locator('tr.flagged').first().waitFor();
    await page.getByRole('button', {name: 'Correct'}).click();
    // What the page prints for that line: one case at 71.40. The agent read the pack size as the quantity.
    await page.getByLabel('Quantity line 58', {exact: true}).fill('1'); await page.getByLabel('Unit price line 58', {exact: true}).fill('71.40');
    await page.getByRole('button', {name: 'Save and approve'}).click();
    await seen('Correction saved and approved.');
  });
  await step('4 upload an invoice the system has not seen', async () => {
    await page.getByRole('link', {name: 'Supplier invoices', exact: true}).first().click();
    await page.getByRole('heading', {name: 'Supplier invoices'}).waitFor();
    await page.locator('#portal-upload').setInputFiles(upload);
    await page.locator('.reading').waitFor();
    await page.getByRole('alert').filter({hasText: '1 read.'}).waitFor({timeout: 180000});
    await page.getByRole('link', {name: path.basename(upload)}).waitFor();
  });
  await step('5 approve, send to the books, and the file downloads', async () => {
    await page.getByRole('button', {name: /^Approve the \d+ ready$/}).click();
    await page.getByRole('alert').filter({hasText: /\d+ approved\./}).waitFor();
    await page.getByRole('link', {name: 'Books', exact: true}).click();
    await seen(/\d+ approved invoices are waiting to be sent\./);
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', {name: /^Send \d+ and download$/}).click()]);
    const rows = fs.readFileSync(await download.path(), 'utf8').trim().split('\n');
    if (rows.length < 60) throw new Error(`the export file holds only ${rows.length} rows`);
    await page.getByRole('alert').filter({hasText: /\d+ sent to the books\./}).waitFor();
    console.log(`    ${download.suggestedFilename()}: ${rows.length - 1} rows`);
  });
  await step('6 the supplier statement against the invoices', async () => {
    await page.getByRole('link', {name: 'Supplier statements', exact: true}).first().click();
    await page.getByRole('link', {name: /^GFS statement/}).click();
    await page.getByRole('heading', {name: 'Checked against your invoices'}).waitFor();
    const figures = await page.locator('.card', {has: page.getByRole('heading', {name: 'Checked against your invoices'})}).locator('.stat').allTextContents();
    console.log(`    agree ${figures[0]}, amount differs ${figures[1]}, listed not on file ${figures[2]}, received not listed ${figures[3]}`);
    if (Number(figures[0]) + Number(figures[1]) + Number(figures[2]) !== 60) throw new Error('the statement does not account for its 60 invoices');
  });
  await step('7 results and prices', async () => {
    await page.getByRole('link', {name: 'Supplier invoices', exact: true}).first().click();
    await page.getByRole('link', {name: 'Results', exact: true}).click(); await seen('Typing you did not do');
    await page.getByRole('link', {name: 'Prices', exact: true}).click(); await page.getByRole('heading', {name: 'Price watch'}).waitFor(); await seen('Prices that went up');
  });
} catch (error) {
  problems.push(String(error));
  if (shots) await page.screenshot({path: path.join(shots, 'failure.png')});
}
await browser.close();
console.log(`${((Date.now() - started) / 1000).toFixed(0)}s in all. ${problems.length ? `${problems.length} problem(s):\n  ${problems.join('\n  ')}` : 'No refused request, no page error.'}`);
process.exit(problems.length ? 1 : 0);
