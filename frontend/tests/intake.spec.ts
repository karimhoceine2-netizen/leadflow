import { expect, test, type Page } from "@playwright/test";

async function fill(page: Page) {
  await page.getByLabel("Naam", { exact: true }).fill("Amina Jansen");
  await page.getByLabel("E-mailadres").fill("amina@example.com");
  await page.getByLabel("Bedrijfsnaam").fill("Northstar BV");
  await page.getByLabel("Waar kunnen we mee helpen?").fill("We willen aanvragen automatisch doorsturen naar onze collega's.");
}

test("valid lead is saved by the real API", async ({ page }) => {
  await page.goto("/");
  await fill(page);
  await page.getByRole("button", { name: "Verstuur aanvraag" }).click();
  await expect(page.getByRole("form").getByRole("status")).toContainText("Je aanvraag is ontvangen en opgeslagen.");
  await expect(page.getByRole("form").getByRole("status")).toContainText("Referentie:");
  await expect(page.getByLabel("Naam", { exact: true })).toHaveValue("");
});

test("invalid form shows inline errors without sending", async ({ page }) => {
  let requests = 0;
  page.on("request", request => { if (request.url().endsWith("/api/leads")) requests++; });
  await page.goto("/");
  await page.getByRole("button", { name: "Verstuur aanvraag" }).click();
  await expect(page.getByRole("form").getByRole("alert")).toContainText("Controleer de gemarkeerde velden.");
  await expect(page.getByRole("form").getByRole("alert")).toBeFocused();
  await expect(page.getByLabel("E-mailadres")).toHaveAttribute("aria-invalid", "true");
  expect(requests).toBe(0);
});

test("storage failure preserves input and retry key", async ({ page }) => {
  const keys: string[] = [];
  await page.route("**/api/leads", async route => {
    keys.push(route.request().headers()["idempotency-key"]);
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Opslaan is tijdelijk niet mogelijk. Probeer opnieuw." }) });
  });
  await page.goto("/"); await fill(page);
  await page.getByRole("button", { name: "Verstuur aanvraag" }).click();
  await expect(page.getByRole("form").getByRole("alert")).toContainText("Opslaan is tijdelijk");
  await expect(page.getByLabel("Naam", { exact: true })).toHaveValue("Amina Jansen");
  await page.getByRole("button", { name: "Verstuur aanvraag" }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);
  await expect(page.getByRole("button", { name: "Verstuur aanvraag" })).toBeEnabled();
  await page.getByLabel("Naam", { exact: true }).fill("Andere Naam");
  await page.getByRole("button", { name: "Verstuur aanvraag" }).click();
  await expect.poll(() => keys.length).toBe(3);
  expect(keys[2]).not.toBe(keys[0]);
});

test("layout fits viewport and reduced-motion preference", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.screenshot({ path: `../outputs/leadflow-${testInfo.project.name}.png`, fullPage: true });
  const sizes = testInfo.project.name === "desktop" ? [{ width: 768, height: 1024 }, { width: 1024, height: 768 }, { width: 1440, height: 900 }] : [{ width: 812, height: 375 }];
  for (const viewport of sizes) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});
