import { expect, test } from "@playwright/test";

async function openCandidateAccess(page: import("@playwright/test").Page, email: string) {
  await page.goto("/candidate/access");
  await expect(page.getByRole("heading", { name: /open the managed assessment as the candidate/i })).toBeVisible();
  await page.getByTestId("candidate-invite-token").fill("invite_candidate_demo");
  await page.getByTestId("candidate-email").fill(email);
  await page.getByTestId("candidate-request-access").click();
  await page.getByTestId("candidate-redeem-access").click();
}

test("candidate preview renders through the real docker-backed runtime", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());

  await openCandidateAccess(page, "candidate@example.com");
  await page.goto("/candidate/assignments/warehouse-ops-api-v1");
  await expect(page.getByRole("heading", { name: /take-home assignment/i })).toBeVisible();
  await page.getByTestId("launch-managed-session-button").click();

  await expect(page).toHaveURL(/\/candidate\/session\/[^/]+$/);
  await expect(page.getByTestId("session-state")).toHaveText(/ready/i, { timeout: 180_000 });
  await expect(page.getByTestId("workspace-status")).toContainText("app/routes.py");

  await page.getByTestId("start-preview-button").click();
  await expect(page.getByTestId("preview-state")).toHaveText(/ready/i, { timeout: 180_000 });
  await expect(page.getByTestId("candidate-preview-iframe")).toBeVisible();

  const previewFrame = page.frameLocator('[data-testid="candidate-preview-iframe"]');
  await expect(previewFrame.locator("body")).toContainText(/Warehouse Ops API Starter/i, { timeout: 60_000 });
  await expect(previewFrame.locator("body")).toContainText(/inventory\/adjustments/i, { timeout: 60_000 });
});
