import { expect, test } from "@playwright/test";

async function openCandidateAccess(page: import("@playwright/test").Page, email: string) {
  await page.goto("/candidate/access");
  await expect(page.getByRole("heading", { name: /open the managed assessment as the candidate/i })).toBeVisible();
  await page.getByTestId("candidate-invite-token").fill("invite_candidate_demo");
  await page.getByTestId("candidate-email").fill(email);
  await page.getByTestId("candidate-request-access").click();
  await page.getByTestId("candidate-redeem-access").click();
}

test("candidate can launch a session, start preview, and submit", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());

  await openCandidateAccess(page, "candidate@example.com");
  await page.goto("/candidate/assignments/warehouse-ops-api-v1");
  await expect(page.getByRole("heading", { name: /take-home assignment/i })).toBeVisible();
  await page.getByTestId("launch-managed-session-button").click();

  await expect(page).toHaveURL(/\/candidate\/session\/[^/]+$/);
  await expect(page.getByTestId("session-state")).toHaveText(/ready/i);
  await expect(page.getByTestId("workspace-status")).toContainText("app/routes.py");

  await page.getByTestId("run-tests-button").click();
  await expect(page.getByText("Tests completed.")).toBeVisible();
  await expect(page.getByText(/passed/i).first()).toBeVisible();

  await page.getByTestId("checkpoint-button").click();
  await expect(page.getByText("Milestone captured.")).toBeVisible();

  await page.getByTestId("start-preview-button").click();
  await expect(page.getByTestId("preview-state")).toHaveText(/ready/i);
  await expect(page.getByTestId("preview-frame-container")).toBeVisible();
  await expect(page.getByTestId("candidate-preview-iframe")).toBeVisible();

  const previewFrame = page.frameLocator('[data-testid="candidate-preview-iframe"]');
  await expect(previewFrame.getByTestId("e2e-preview-heading")).toHaveText("Warehouse Ops API Preview");

  await page.getByTestId("submit-assessment-button").click();
  await page.getByTestId("submission-checklist-brief").check();
  await page.getByTestId("candidate-summary-note").fill("Implemented safer inventory adjustment validation and query handling.");
  await page.getByTestId("candidate-tradeoff-note").fill("Focused on correctness first and left deeper pagination work for later.");
  await page.getByTestId("candidate-unfinished-note").fill("I would add observability and richer history filters next.");
  await page.getByTestId("confirm-submit-assessment-button").click();
  await expect(page).toHaveURL(/\/candidate\/report\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Warehouse Ops API" })).toBeVisible();
  await expect(page.getByTestId("candidate-report-review-state")).toContainText(
    /pending_review|awaiting_review|under_review|published/i,
  );
});
