import { expect, test, type Page } from "@playwright/test";

async function currentCsrfToken(page: Page) {
  const cookies = await page.context().cookies();
  const csrfCookie = cookies.find((cookie) => cookie.name === "forge_csrf");
  if (!csrfCookie) {
    throw new Error("Expected forge_csrf cookie in browser context.");
  }
  return csrfCookie.value;
}

async function signInReviewer(page: Page) {
  const request = page.context().request;

  const loginResponse = await request.post("/api/auth/login", {
    data: {
      email: "reviewer@verified.dev",
      password: "demo-password",
    },
  });
  expect(loginResponse.ok()).toBeTruthy();

  const enrollResponse = await request.post("/api/auth/mfa/enroll", {
    headers: {
      "X-CSRF-Token": await currentCsrfToken(page),
    },
  });
  expect(enrollResponse.ok()).toBeTruthy();
  const enrollPayload = await enrollResponse.json();
  const recoveryCode = enrollPayload.enrollment?.recovery_codes?.[0];
  if (!recoveryCode) {
    throw new Error("Expected MFA recovery code for reviewer session.");
  }

  const verifyResponse = await request.post("/api/auth/mfa/verify", {
    data: { code: recoveryCode },
    headers: {
      "X-CSRF-Token": await currentCsrfToken(page),
    },
  });
  expect(verifyResponse.ok()).toBeTruthy();
}

async function createSubmittedCandidate(page: Page) {
  page.on("dialog", (dialog) => dialog.accept());

  await page.goto("/candidate/access");
  await expect(page.getByRole("heading", { name: /open the managed assessment as the candidate/i })).toBeVisible();
  await page.getByTestId("candidate-invite-token").fill("invite_candidate_demo");
  await page.getByTestId("candidate-email").fill("candidate@example.com");
  await page.getByTestId("candidate-request-access").click();
  await page.getByTestId("candidate-redeem-access").click();

  await page.goto("/candidate/assignments/warehouse-ops-api-v1");
  await expect(page.getByRole("heading", { name: /take-home assignment/i })).toBeVisible();
  await page.getByTestId("launch-managed-session-button").click();

  await expect(page).toHaveURL(/\/candidate\/session\/[^/]+$/);
  await expect(page.getByTestId("session-state")).toHaveText(/ready/i);
  await expect(page.getByTestId("workspace-status")).toContainText("app/routes.py");

  await page.getByTestId("run-tests-button").click();
  await expect(page.getByText("Tests completed.")).toBeVisible();
  await page.getByTestId("start-preview-button").click();
  await expect(page.getByTestId("preview-state")).toHaveText(/ready/i);
  await page.getByTestId("submit-assessment-button").click();
  await page.getByTestId("submission-checklist-brief").check();
  await page.getByTestId("candidate-summary-note").fill("Hardened inventory adjustments and clarified query behavior.");
  await page.getByTestId("candidate-tradeoff-note").fill("Optimized for safer writes before adding broader reporting features.");
  await page.getByTestId("candidate-unfinished-note").fill("I would add deeper audit and observability coverage next.");
  await page.getByTestId("confirm-submit-assessment-button").click();
  await expect(page).toHaveURL(/\/candidate\/report\/[^/]+$/);

  const reportUrl = page.url();
  const reportId = reportUrl.split("/").pop();
  if (!reportId) {
    throw new Error("Expected candidate report id in URL.");
  }
  return reportId;
}

test("reviewer can publish and revoke employer access for a submitted candidate", async ({ page }) => {
  const reportId = await createSubmittedCandidate(page);

  await signInReviewer(page);
  await page.goto("/admin/review-queue");

  const queueItem = page.getByTestId(`review-queue-item-${reportId}`);
  await expect(queueItem).toBeVisible();
  await expect(page.getByTestId(`queue-review-state-${reportId}`)).toContainText(/pending_review/i);

  await page.getByTestId(`claim-review-${reportId}`).click();
  await expect(page.getByTestId(`queue-assignment-state-${reportId}`)).toContainText(/claimed/i);

  await page.getByTestId(`review-decision-${reportId}`).selectOption("advance");
  await page.getByTestId(`review-notes-${reportId}`).fill("Candidate showed strong debugging discipline and clean delivery.");
  await page.getByTestId(`save-draft-${reportId}`).click();

  await expect(page.getByTestId(`queue-review-state-${reportId}`)).toContainText(/in_review/i);
  await page.getByRole("link", { name: /Open review/i }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/reviews/${reportId}$`));
  await page.getByTestId(`review-workbench-strongest-signal-${reportId}`).fill("Clear correctness focus with evidence-backed fixes.");
  await page.getByTestId(`review-workbench-biggest-concern-${reportId}`).fill("The reporting surface still leaves room for deeper follow-up work.");
  await page.getByTestId(`review-workbench-interview-focus-${reportId}`).fill("Probe data modeling choices and operational visibility.");
  await page.getByTestId(`review-workbench-publish-reason-${reportId}`).fill("Portable because the artifact is coherent and reviewable.");
  await page.getByRole("button", { name: /Save draft/i }).click();
  const publishResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/internal/reviews/publish") && response.request().method() === "POST" && response.ok(),
  );
  await page.getByRole("button", { name: /Publish/i }).click();
  const publishPayload = await (await publishResponsePromise).json();

  const reportToken =
    publishPayload.report?.review_summary?.access?.report_token ?? publishPayload.report?.employer_summary?.report_access_token;
  if (!reportToken) {
    throw new Error("Expected published employer report token.");
  }

  const previewToken =
    publishPayload.report?.review_summary?.access?.preview_token ?? publishPayload.report?.employer_summary?.preview_access_token ?? null;
  await expect(page.getByTestId(`review-queue-item-${reportId}`)).toHaveCount(0);

  await page.goto(`/employer/report/${reportToken}`);
  await expect(page.getByRole("heading", { name: "Warehouse Ops API" })).toBeVisible();
  await expect(page.getByTestId("employer-report-review-state")).toContainText(/human_reviewed|second_review_required/i);
  await expect(page.getByTestId("employer-report-decision")).toContainText(/advance/i);
  await expect(page.getByTestId("employer-report-notes")).toContainText(/strong debugging discipline/i);
  await expect(page.getByTestId("employer-report-strongest-signal")).toContainText(/Clear correctness focus with evidence-backed fixes./i);
  await expect(page.getByTestId("employer-report-publication")).toContainText(/published|restricted/i);

  if (previewToken) {
    await page.goto(`/employer/preview/${previewToken}`);
    await expect(page.getByTestId("employer-preview-frame-container")).toBeVisible();
    const previewFrame = page.frameLocator('[data-testid="employer-preview-iframe"]');
    await expect(previewFrame.getByTestId("e2e-preview-heading")).toHaveText("Warehouse Ops API Preview");
  }
});
