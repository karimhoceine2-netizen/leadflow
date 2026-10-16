import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const EMAIL = "admin@example.com";
const PASSWORD = crypto.randomUUID() + crypto.randomUUID();
const ORIGIN = "http://127.0.0.1:3001";

async function login(page: Page) {
  await page.goto("/dashboard");
  await expect(page.getByLabel("E-mailadres")).toBeVisible();
  const setup = await page.getByRole("heading", { name: "Maak je beheeraccount." }).isVisible();
  await page.getByLabel("E-mailadres").fill(EMAIL);
  await page.getByLabel("Wachtwoord", { exact: true }).fill(PASSWORD);
  if (setup) await page.getByLabel("Herhaal wachtwoord").fill(PASSWORD);
  await page.getByRole("button", { name: setup ? "Beheeraccount maken" : "Inloggen", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Aanvragen", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Leadlijst" })).toHaveAttribute("aria-busy", "false");
}

async function createLead(page: Page, suffix: string) {
  const company = `Browserdemo ${suffix} ${crypto.randomUUID().slice(0, 8)}`;
  const response = await page.request.post("http://127.0.0.1:8001/api/leads", {
    headers: { "Idempotency-Key": crypto.randomUUID() },
    data: { name: "Amina Jansen", email: "amina@example.com", company_name: company, description: "We willen nieuwe aanvragen automatisch verwerken en opvolgen." },
  });
  expect(response.status()).toBe(201);
  return { id: (await response.json()).id as string, company };
}

function setTestAutomation(id: string, state: string, processed = false) {
  // Explicit test database only: never use settings/defaults from the user's .env.
  const backend = path.resolve(process.cwd(), "../backend");
  execFileSync(path.join(backend, ".venv/bin/python"), ["-c", `
import asyncio,json,sqlite3,sys
from pathlib import Path
from app.outbox import Outbox
database=Path.cwd().parent/'work/e2e.sqlite3'
assert database.name=='e2e.sqlite3' and database.parent.name=='work'
with sqlite3.connect(database) as db:
 row=db.execute('SELECT id,payload FROM lead_events WHERE lead_id=?',(sys.argv[1],)).fetchone()
 assert row
if sys.argv[3]=='yes': asyncio.run(Outbox(database).process(json.loads(row[1])))
with sqlite3.connect(database) as db:
 if sys.argv[2]=='not_scheduled': db.execute('DELETE FROM lead_events WHERE id=?',(row[0],))
 else: db.execute('UPDATE lead_events SET state=? WHERE id=?',(sys.argv[2],row[0]))
`, id, state, processed ? "yes" : "no"], { cwd: backend, stdio: "pipe" });
}

test("dashboard gates access, supports own login and logout", async ({ page }, testInfo) => {
  await page.goto("/dashboard");
  await expect(page.getByLabel("E-mailadres")).toBeVisible();
  await expect(page.getByRole("region", { name: "Leadlijst" })).not.toBeVisible();
  await page.screenshot({ path: `../outputs/leadflow-login-${testInfo.project.name}.png`, fullPage: true });
  expect((await page.request.get("/api/admin/leads")).status()).toBe(401);
  await login(page);
  const cookies = await page.context().cookies();
  expect(cookies.find(cookie => cookie.name === "leadflow_admin")?.httpOnly).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Aanvragen", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Uitloggen", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Welkom terug." })).toBeVisible();
  expect((await page.request.get("/api/admin/leads")).status()).toBe(401);
  await page.getByLabel("E-mailadres").fill(EMAIL);
  await page.getByLabel("Wachtwoord", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Inloggen", exact: true }).click();
  await expect(page.getByRole("form", { name: "Beheerlogin" }).getByRole("alert")).toContainText("E-mailadres of wachtwoord klopt niet.");
});

test("lead search, detail, status history, filtering and persistence", async ({ page }, testInfo) => {
  const lead = await createLead(page, testInfo.project.name);
  await login(page);
  await page.getByLabel("Zoeken").fill(lead.company);
  const link = page.getByRole("link", { name: lead.company, exact: true });
  await expect(link.filter({ visible: true })).toBeVisible();
  await link.filter({ visible: true }).click();
  await expect(page.getByRole("heading", { name: lead.company, exact: true })).toBeVisible();
  await expect(page.getByText(lead.id, { exact: true })).toBeVisible();
  await page.getByLabel("Status", { exact: true }).selectOption("contacted");
  await page.getByRole("button", { name: "Status opslaan", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Status opgeslagen.");
  await expect(page.getByRole("region", { name: "Wijzigingshistorie" })).toContainText("Nieuw → Gecontacteerd");
  await page.reload();
  await expect(page.getByLabel("Status", { exact: true })).toHaveValue("contacted");
  await page.screenshot({ path: `../outputs/leadflow-crm-detail-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("link", { name: "Terug naar aanvragen" }).click();
  await page.getByLabel("Zoeken").fill(lead.company);
  await page.getByLabel("Status", { exact: true }).selectOption("contacted");
  await expect(page.getByRole("link", { name: lead.company, exact: true }).filter({ visible: true })).toBeVisible();
  await page.getByLabel("Status", { exact: true }).selectOption("closed");
  await expect(page.getByRole("heading", { name: "Geen aanvragen gevonden" })).toBeVisible();
  await page.getByRole("button", { name: "Filters wissen" }).click();
  await expect(page.getByRole("link", { name: lead.company, exact: true }).filter({ visible: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Leadlijst" })).toHaveAttribute("aria-busy", "false");
  await page.screenshot({ path: `../outputs/leadflow-crm-${testInfo.project.name}.png`, fullPage: true });
  const sizes = [{ width: 375, height: 812 }, { width: 768, height: 1024 }, { width: 1024, height: 768 }, { width: 1440, height: 900 }];
  for (const viewport of sizes) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

test("concurrent edit refreshes the current lead instead of overwriting", async ({ page }, testInfo) => {
  const lead = await createLead(page, `conflict ${testInfo.project.name}`);
  await login(page);
  await page.goto(`/dashboard/leads/${lead.id}`);
  await expect(page.getByLabel("Status", { exact: true })).toHaveValue("new");
  const identity = await (await page.request.get("/api/admin/session")).json();
  const external = await page.request.patch(`/api/admin/leads/${lead.id}/status`, {
    headers: { Origin: ORIGIN, "X-CSRF-Token": identity.csrf_token },
    data: { status: "qualified", expected_version: 0 },
  });
  expect(external.status()).toBe(200);
  await page.getByLabel("Status", { exact: true }).selectOption("contacted");
  await page.getByRole("button", { name: "Status opslaan", exact: true }).click();
  await expect(page.getByRole("form", { name: "Status bijwerken" }).getByRole("alert")).toContainText("ondertussen gewijzigd");
  await expect(page.getByLabel("Status", { exact: true })).toHaveValue("qualified");
  await expect(page.getByRole("region", { name: "Wijzigingshistorie" })).toContainText("Nieuw → Gekwalificeerd");
});

test("proxy rejects unknown paths, oversized requests and missing csrf", async ({ page }) => {
  await login(page);
  expect((await page.request.get("/api/admin/private-config")).status()).toBe(404);
  expect((await page.request.post("/api/admin/logout", { headers: { Origin: ORIGIN } })).status()).toBe(403);
  expect((await page.request.post("/api/admin/login", { headers: { Origin: ORIGIN }, data: "x".repeat(16385) })).status()).toBe(413);
  expect((await page.request.post("/api/admin/logout", { headers: { Origin: "https://evil.example" } })).status()).toBe(403);
});

test("storage error offers retry and session expiry returns to login", async ({ page }) => {
  await login(page);
  await page.route("**/api/admin/leads?**", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Aanvragen laden is tijdelijk niet mogelijk." }) }));
  await page.getByRole("button", { name: "Vernieuwen" }).click();
  await expect(page.getByRole("region", { name: "Leadlijst" }).getByRole("alert")).toContainText("tijdelijk niet mogelijk");
  await page.unroute("**/api/admin/leads?**");
  await page.getByRole("button", { name: "Opnieuw proberen", exact: true }).click();
  await expect(page.getByRole("region", { name: "Leadlijst" })).toHaveAttribute("aria-busy", "false");
  await page.context().clearCookies();
  await page.getByRole("button", { name: "Vernieuwen" }).click();
  await expect(page.getByRole("heading", { name: "Welkom terug." })).toBeVisible();
});

test("automation refresh shows real processing without discarding an unsaved CRM status", async ({ page }, testInfo) => {
  const lead = await createLead(page, `automation ${testInfo.project.name}`);
  await login(page);
  await page.getByLabel("Zoeken").fill(lead.company);
  const list = page.getByRole("region", { name: "Leadlijst" });
  const entry = list.locator("tr, li").filter({ has: page.getByRole("link", { name: lead.company, exact: true }) }).filter({ visible: true });
  await expect(entry.getByText("Wacht op verwerking", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: lead.company, exact: true }).filter({ visible: true }).click();
  const automation = page.getByRole("region", { name: "Automatische verwerking" });
  await expect(automation.getByText("Wacht op verwerking", { exact: true })).toBeVisible();
  await page.getByLabel("Status", { exact: true }).selectOption("contacted");
  setTestAutomation(lead.id, "pending", true);
  await automation.getByRole("button", { name: "Verwerking vernieuwen" }).click();
  await expect(automation.getByText("Automatisch verwerkt", { exact: true })).toBeVisible();
  await expect(automation).toContainText("afleverbevestiging ontbreekt");
  await expect(page.getByLabel("Status", { exact: true })).toHaveValue("contacted");
  await expect(page.getByRole("button", { name: "Status opslaan", exact: true })).toBeEnabled();
  const before = await (await page.request.get(`/api/admin/leads/${lead.id}`)).json();
  expect(before.status).toBe("new"); expect(before.version).toBe(0); expect(before.history).toEqual([]);
  setTestAutomation(lead.id, "delivered", true);
  await automation.getByRole("button", { name: "Verwerking vernieuwen" }).click();
  await expect(automation.getByText(/afleverbevestiging ontbreekt/)).not.toBeVisible();
  await expect(automation).toContainText("Verwerkt op");
  await expect(automation).toContainText("Demo-prioriteit: Normaal");
  await page.screenshot({ path: `../outputs/leadflow-automation-detail-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Status opslaan", exact: true }).click();
  await expect(page.getByRole("form", { name: "Status bijwerken" }).getByRole("status")).toContainText("Status opgeslagen.");
  await expect(automation.getByText("Automatisch verwerkt", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Terug naar aanvragen" }).click();
  await page.getByLabel("Zoeken").fill(lead.company);
  await expect(entry.getByText("Automatisch verwerkt", { exact: true })).toBeVisible();
  await expect(entry.getByText("Gecontacteerd", { exact: true })).toBeVisible();
  await expect(list).toContainText("1 resultaat");
  await expect(list).toHaveAttribute("aria-busy", "false");
  await page.screenshot({ path: `../outputs/leadflow-automation-list-${testInfo.project.name}.png`, fullPage: true });
  for (const viewport of [{ width: 375, height: 812 }, { width: 768, height: 1024 }, { width: 1024, height: 768 }, { width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 812, height: 375 }]) {
    await page.setViewportSize(viewport);
    await expect(entry.getByText("Automatisch verwerkt", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});

test("failed and old workflows have clear labels; refresh failures retain the previous result", async ({ page }, testInfo) => {
  const lead = await createLead(page, `failed workflow ${testInfo.project.name}`);
  setTestAutomation(lead.id, "dead");
  await login(page);
  await page.getByLabel("Zoeken").fill(lead.company);
  const list = page.getByRole("region", { name: "Leadlijst" });
  const entry = list.locator("tr, li").filter({ has: page.getByRole("link", { name: lead.company, exact: true }) }).filter({ visible: true });
  await expect(entry.getByText("Opnieuw proberen nodig", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: lead.company, exact: true }).filter({ visible: true }).click();
  const automation = page.getByRole("region", { name: "Automatische verwerking" });
  await expect(automation).toContainText("handmatige retry");
  await page.route(`**/api/admin/leads/${lead.id}`, route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "De aanvraag kon niet worden geladen." }) }));
  await automation.getByRole("button", { name: "Verwerking vernieuwen" }).click();
  await expect(automation.getByRole("alert")).toContainText("eerder geladen verwerking blijft zichtbaar");
  await expect(automation.getByText("Opnieuw proberen nodig", { exact: true })).toBeVisible();
  await page.unroute(`**/api/admin/leads/${lead.id}`);
  setTestAutomation(lead.id, "not_scheduled");
  await automation.getByRole("button", { name: "Verwerking vernieuwen" }).click();
  await expect(automation.getByText("Niet ingepland", { exact: true })).toBeVisible();
  await expect(automation.getByRole("alert")).not.toBeVisible();
  await page.getByRole("link", { name: "Terug naar aanvragen" }).click();
  await page.getByLabel("Zoeken").fill(lead.company);
  await expect(entry.getByText("Niet ingepland", { exact: true })).toBeVisible();
});
