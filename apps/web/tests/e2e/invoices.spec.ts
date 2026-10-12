import {expect, test} from '@playwright/test';

test('customer invoice workflow: review, reconcile a statement and export approved bills', async ({page}) => {
  const rateLimited: string[] = [];
  page.on('response', response => {if (response.status() === 429) rateLimited.push(response.url());});
  await page.goto('/dashboard');
  await page.getByRole('button', {name: 'Open local demo workspace'}).click();
  await page.getByRole('link', {name: 'Customers', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Invoice Browser Customer'})).toBeVisible();
  // The customer platform opens in a tab of its own, with its own session.
  const [portal] = await Promise.all([page.context().waitForEvent('page'), page.getByRole('button', {name: 'Open customer platform'}).click()]);
  portal.on('response', response => {if (response.status() === 429) rateLimited.push(response.url());});
  await expect(portal.getByRole('heading', {name: 'Dashboard'})).toBeVisible();
  await portal.getByRole('link', {name: 'Supplier invoices', exact: true}).first().click();
  await expect(portal.getByRole('heading', {name: 'Supplier invoices'})).toBeVisible();
  await expect(portal.getByText('invoice-1002.pdf')).toBeVisible();
  await expect(portal.getByText('needs a person', {exact: true})).toBeVisible();
  await portal.getByRole('button', {name: 'Approve the 1 ready'}).click();

  await portal.getByRole('link', {name: 'Supplier statements', exact: true}).first().click();
  await expect(portal.getByText('statement-february.pdf')).toBeVisible();
  await portal.getByRole('link', {name: 'statement-february.pdf'}).click();
  await expect(portal.getByRole('heading', {name: 'Checked against your invoices'})).toBeVisible();
  await expect(portal.getByText('not on file', {exact: true})).toBeVisible();

  await portal.getByRole('link', {name: 'Supplier invoices', exact: true}).first().click();
  await portal.getByRole('link', {name: 'Books', exact: true}).click();
  await expect(portal.getByText('1 approved invoice is waiting to be sent.')).toBeVisible();
  await portal.getByLabel('Your ledger accounts').fill('5000, Food cost');
  await portal.getByLabel('Account for anything not set below').selectOption('5000');
  await portal.getByRole('button', {name: 'Save', exact: true}).click();
  await expect(portal.getByRole('alert').filter({hasText: 'Saved.'})).toBeVisible();
  await expect(portal.getByRole('button', {name: 'Send 1 and download'})).toBeEnabled();
  const exportCreated = portal.waitForResponse(response => response.request().method() === 'POST' && /\/portal\/operations\/[^/]+\/exports$/.test(response.url()));
  await portal.getByRole('button', {name: 'Send 1 and download'}).click();
  const exportResponse = await exportCreated;
  const exportBody = await exportResponse.json();
  expect(exportResponse.status(), JSON.stringify(exportBody)).toBe(201);
  expect(exportBody.documents).toBe(1);
  await expect(portal.getByText('1 sent to the books.')).toBeVisible();
  await expect(portal.getByRole('button', {name: 'Send and download'})).toBeDisabled();
  // The builder's own tab is still signed in to Agent Factory.
  await expect(page.getByRole('heading', {name: 'Customers'})).toBeVisible();
  expect(rateLimited, 'Customer invoice pages must stay within the API request limit').toEqual([]);
});
