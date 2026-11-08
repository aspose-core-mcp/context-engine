import { expect, test } from "@playwright/test";

/**
 * Smoke suite for the admin console shell and public pages; the console renders
 * fixtures when no backend is reachable.
 */

test.describe("Mono console shell", () => {
  test("loads Health by default with the full 18-item sidebar", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".page-title")).toHaveText("Health");
    // Source of truth: src/mono/lib/nav.ts (18 entries). Update BOTH together
    // when the sidebar changes.
    await expect(page.locator(".side-item")).toHaveCount(18);
    await expect(page.locator('.side-item[data-nav="health"]')).toHaveAttribute(
      "aria-current",
      "page",
    );
    // skip-link present for a11y
    await expect(page.locator("a.skip-link")).toHaveAttribute("href", "#main-content");
  });

  test("⌘K command palette opens, filters, and navigates", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Meta+k");
    const panel = page.locator(".cmdk-panel");
    await expect(panel).toBeVisible();
    await panel.locator("input").fill("analytics");
    await page.keyboard.press("Enter");
    await expect(page.locator(".page-title")).toHaveText("Analytics");
    await expect(panel).toBeHidden();
  });

  test("sidebar navigates between sections (hash-routed)", async ({ page }) => {
    await page.goto("/");
    await page.locator('.side-item[data-nav="snapshots"]').click();
    await expect(page.locator(".page-title")).toContainText("Snapshots");
    await expect(page).toHaveURL(/#snapshots/);
    await page.locator('.side-item[data-nav="coverage"]').click();
    await expect(page.locator(".page-title")).toContainText("Content Coverage");
  });

  test("theme toggle flips to dark and persists across reload", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".adcs")).not.toHaveClass(/theme-dark/);
    await page.locator('button[aria-label*="theme"]').first().click();
    await expect(page.locator(".adcs")).toHaveClass(/theme-dark/);
    await page.reload();
    await expect(page.locator(".adcs")).toHaveClass(/theme-dark/);
  });

  test("density toggle applies the compact root class", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Compact", exact: true }).click();
    await expect(page.locator(".adcs")).toHaveClass(/density-compact/);
  });

  test("status pills carry a dot (color is never the sole indicator)", async ({ page }) => {
    await page.goto("/");
    const firstPill = page.locator(".pill").first();
    await expect(firstPill).toBeVisible();
    await expect(firstPill.locator(".dot")).toBeVisible();
  });
});

test.describe("Mono public pages", () => {
  test("/status renders the public status dashboard", async ({ page }) => {
    await page.goto("/status");
    await expect(page.locator(".pub-nav")).toBeVisible();
    await expect(page.getByText("ADCS Service Status")).toBeVisible();
  });

  test("/integrations renders the MCP portal", async ({ page }) => {
    await page.goto("/integrations");
    await expect(page.locator(".pub-nav")).toBeVisible();
  });
});
