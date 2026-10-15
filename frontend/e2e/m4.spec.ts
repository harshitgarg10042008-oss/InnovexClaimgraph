import { expect, test } from "@playwright/test";
import path from "node:path";

test("M4 review workflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("http://localhost:3000/");
  await expect(page.locator("h1")).toHaveText("Cases");
  await expect.poll(() => page.locator("tbody tr").count(), { timeout: 15_000 }).toBeGreaterThanOrEqual(4);

  const cases = await page.request.get("http://localhost:8000/cases");
  expect(cases.ok()).toBeTruthy();
  const caseRows = await cases.json();
  const caseA = caseRows.find((item: { title?: string }) => /case a/i.test(item.title ?? "")) ?? caseRows[0];
  expect(caseA?.id).toBeTruthy();
  await page.goto(`http://localhost:3000/cases/${caseA.id}`);
  await expect(page.getByText("Case workspace", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Process documents" }).click();
  await expect.poll(
    async () => (await page.locator(".document-meta").allTextContents()).some((text) => /processing|queued/i.test(text)),
    { timeout: 20_000 },
  ).toBeFalsy();
  await expect(page.getByRole("button", { name: "Review" })).toBeVisible();

  const factsResponse = await page.request.get(`http://localhost:8000/cases/${caseA.id}/facts`);
  expect(factsResponse.ok()).toBeTruthy();
  const facts = await factsResponse.json();
  const evidenceFact = facts.find((fact: { bbox?: unknown; label?: string; field: string }) => fact.bbox);
  expect(evidenceFact).toBeTruthy();
  const evidenceRow = page.locator(".fact-row").filter({ hasText: evidenceFact.label ?? evidenceFact.field }).first();
  await expect(evidenceRow).toBeVisible({ timeout: 15_000 });
  await evidenceRow.click();
  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
  await expect(page.locator(".evidence-image img")).toBeVisible();
  await expect(page.locator(".bbox")).toHaveCount(1);
  await expect(page.locator(".bbox")).toHaveCSS("border-style", "solid");

  const needsReview = page.locator(".fact-row:has(.chip-needs_review)").first();
  await expect(needsReview).toBeVisible({ timeout: 15_000 });
  await needsReview.getByTitle("Edit").click();
  const editInput = page.locator(".fact-row input").first();
  await expect(editInput).toBeVisible();
  await editInput.fill("1,23,456.00");
  const editResponse = page.waitForResponse((response) => response.url().includes("/facts/") && response.request().method() === "PATCH");
  await editInput.press("Enter");
  await expect((await editResponse).status()).toBe(200);
  const editedFact = page.locator(".fact-row:has(.chip-edited)").first();
  await expect(editedFact).toContainText("edited", { timeout: 15_000 });
  await expect(editedFact).toContainText("was:");

  const confirmable = page.locator(".fact-row:has(.chip-needs_review)").first();
  await confirmable.getByTitle("Confirm").click();
  await expect(page.locator(".fact-row:has(.chip-confirmed), .fact-row:has(.chip-edited)").first()).toBeVisible({ timeout: 15_000 });

  const notPresent = page.locator(".fact-row:has(.chip-needs_review)").first();
  const notPresentResponse = page.waitForResponse((response) => response.url().includes("/facts/") && response.request().method() === "PATCH");
  await notPresent.getByTitle("Mark not present").click();
  await expect((await notPresentResponse).status()).toBe(200);
  await expect(page.locator(".fact-row:has(.chip-not_present)").first()).toBeVisible({ timeout: 15_000 });

  const bulk = page.getByRole("button", { name: /Confirm all auto/ }).first();
  if (await bulk.isVisible()) {
    await bulk.click();
    await expect(bulk).toBeVisible();
  }

  await page.screenshot({ path: path.resolve(process.cwd(), "../docs/screenshots/m4/review-1440.png"), fullPage: true });
  await page.reload();
  await expect(page.locator(".fact-row").filter({ hasText: /edited|not present|confirmed/i }).first()).toBeVisible();
  await page.getByRole("button", { name: /Audit log/ }).click();
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await expect.poll(() => page.locator(".audit-row").count(), { timeout: 15_000 }).toBeGreaterThan(0);

  const reviewPanel = page.locator(".review-panel");
  await reviewPanel.focus();
  await page.keyboard.press("j");
  await page.keyboard.press("Enter");
  await expect(page.locator(".status-chip").filter({ hasText: /confirmed/i }).first()).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.resolve(process.cwd(), "../docs/screenshots/m4/review-390.png"), fullPage: true });
});
