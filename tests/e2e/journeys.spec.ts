/**
 * Critical browser journeys against the real FastAPI app, real SQLite database and the alert
 * worker, in fixture mode (fictitious SX: data). Run: cd apps/web && npx playwright test
 */
import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const MOD = process.platform === "darwin" ? "Meta" : "Control";

/** The shell (and its global key handler) is mounted once the topbar search button exists. */
async function ready(page: Page) {
  await expect(page.getByRole("button", { name: /Search symbols, pages and actions/ })).toBeVisible();
}

async function pickSymbol(page: Page, label: string | RegExp, query: string, symbol: string) {
  const box = page.getByRole("combobox", { name: label });
  await box.fill(query);
  await page.getByRole("option", { name: new RegExp(symbol.replace(":", "\\:")) }).first().click();
}

async function addTransaction(page: Page, t: { type: string; date: string; symbol?: string; qty?: string; price?: string; fees?: string; amount?: string }) {
  await page.getByRole("button", { name: "Add transaction" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add transaction" });
  await dialog.getByLabel("Type").selectOption(t.type);
  await dialog.getByLabel("Effective date").fill(t.date);
  if (t.symbol) await pickSymbol(page, /Instrument/, t.symbol.replace("SX:", ""), t.symbol);
  if (t.qty) await dialog.getByLabel("Quantity").fill(t.qty);
  if (t.price) await dialog.getByLabel("Price per share").fill(t.price);
  if (t.fees) await dialog.getByLabel("Fees and charges").fill(t.fees);
  if (t.amount) await dialog.getByLabel(/Amount/).fill(t.amount);
  await dialog.getByRole("button", { name: "Record transaction" }).click();
}

test("overview opens on the dashboard with a sample-data badge and honest empty states", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Sample data, dataset date 30 Jun 2026/ })).toBeVisible();
  await expect(page.getByText("No watchlist yet", { exact: true })).toBeVisible();
  await expect(page.getByText("No transactions yet", { exact: true })).toBeVisible(); // never invents holdings
  await page.getByRole("button", { name: "Create watchlist" }).click();
  const dialog = page.getByRole("dialog", { name: "New watchlist" });
  await dialog.getByLabel("Name").fill("E2E list");
  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText("E2E list is empty", { exact: true })).toBeVisible();
});

test("search → open chart → change range → add to watchlist → persists after reload", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  await page.keyboard.press(`${MOD}+k`);
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await palette.getByRole("combobox").fill("glasswing");
  await expect(palette.getByRole("option", { name: /SX:GLASSWING/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/instrument\/SX%3AGLASSWING$/);
  await expect(page.getByRole("heading", { name: "SX:GLASSWING" })).toBeVisible();

  const chart = page.getByRole("region", { name: "Price history" }).or(page.locator("section", { hasText: "Price history" }).first());
  await expect(page.getByRole("radio", { name: "1Y" })).toHaveAttribute("aria-checked", "true");
  const historyResponse = page.waitForResponse((r) => r.url().includes("/api/market/history") && r.url().includes("range=3M"));
  await page.getByRole("radio", { name: "3M" }).click();
  expect((await historyResponse).status()).toBe(200);
  await expect(page.getByRole("radio", { name: "3M" })).toHaveAttribute("aria-checked", "true");
  await expect(chart.locator("canvas").first()).toBeVisible();
  // accessible table alternative for the chart
  await page.getByRole("button", { name: "Show data table" }).click();
  await expect(page.getByRole("table", { name: /Daily prices for SX:GLASSWING/ })).toBeVisible();
  await page.getByRole("button", { name: "Show chart" }).click();

  await page.getByRole("button", { name: "Add to E2E list" }).click();
  await expect(page.getByRole("button", { name: "In E2E list" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "In E2E list" })).toHaveAttribute("aria-pressed", "true");
  await page.goto("/watchlists");
  await expect(page.getByRole("link", { name: /SX:GLASSWING/ })).toBeVisible();
});

test("ledger: transactions update holdings and cash; invalid trade keeps input and explains", async ({ page }) => {
  await page.goto("/portfolio");
  await addTransaction(page, { type: "DEPOSIT", date: "2026-01-02", amount: "10000" });
  await expect(page.getByText("Transaction recorded.")).toBeVisible();
  await addTransaction(page, { type: "BUY", date: "2026-01-03", symbol: "SX:AURORA", qty: "10", price: "100", fees: "10" });
  await addTransaction(page, { type: "BUY", date: "2026-01-04", symbol: "SX:AURORA", qty: "10", price: "120", fees: "10" });
  await addTransaction(page, { type: "SELL", date: "2026-01-05", symbol: "SX:AURORA", qty: "5", price: "130", fees: "5" });

  const summary = page.getByRole("region", { name: "Portfolio summary" });
  await expect(summary.getByText("₹8,425.00")).toBeVisible(); // cash
  const holdings = page.getByRole("table", { name: "Holdings" });
  const row = holdings.getByRole("row", { name: /SX:AURORA/ });
  await expect(row.getByRole("cell", { name: "15", exact: true })).toBeVisible();
  await expect(row.getByRole("cell", { name: "₹111.00" })).toBeVisible();
  await expect(row.getByRole("cell", { name: "₹1,665.00" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Transaction ledger" }).getByText("+₹90.00")).toBeVisible(); // realized

  // A purchase the cash cannot fund is rejected by the server; the dialog keeps the input
  await page.getByRole("button", { name: "Add transaction" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add transaction" });
  await dialog.getByLabel("Effective date").fill("2026-01-06");
  await pickSymbol(page, /Instrument/, "AURORA", "SX:AURORA");
  await dialog.getByLabel("Quantity").fill("1000");
  await dialog.getByLabel("Price per share").fill("100");
  await dialog.getByRole("button", { name: "Record transaction" }).click();
  await expect(dialog.getByRole("alert").first()).toContainText("would make cash negative");
  await expect(dialog.getByLabel("Quantity")).toHaveValue("1000");
  // client-side validation is inline and associated with the field
  await dialog.getByLabel("Price per share").fill("-5");
  await dialog.getByRole("button", { name: "Record transaction" }).click();
  await expect(dialog.getByText("Price must be a plain number")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(summary.getByText("₹8,425.00")).toBeVisible();
});

test("CSV: preview → import → duplicate upload is rejected", async ({ page }) => {
  const csv = [
    "date,type,symbol,quantity,price,fees,amount,currency,notes",
    "2026-02-02,DEPOSIT,,,,,5000,INR,e2e import",
    "2026-02-03,BUY,SX:BANYAN,2,900,4.50,,INR,e2e import",
  ].join("\n");
  const file = { name: "e2e.csv", mimeType: "text/csv", buffer: Buffer.from(csv) };
  await page.goto("/portfolio");
  await page.getByRole("button", { name: "Import CSV" }).click();
  const dialog = page.getByRole("dialog", { name: /Import transactions/ });
  await dialog.locator("#csv-file").setInputFiles(file);
  await expect(dialog.getByText("2 new")).toBeVisible();
  await expect(page.getByText("5000", { exact: true })).toBeVisible(); // preview row values
  await dialog.getByRole("button", { name: "Import 2 row(s)" }).click();
  await expect(dialog.getByRole("status").filter({ hasText: "Imported 2 transaction(s)" })).toBeVisible();

  await dialog.locator("#csv-file").setInputFiles(file);
  await expect(dialog.getByText("2 duplicate")).toBeVisible();
  await expect(dialog.getByText("Every row already exists in the ledger")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cannot import" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Close" }).first().click();
  await expect(page.getByRole("table", { name: "Holdings" }).getByRole("row", { name: /SX:BANYAN/ })).toBeVisible();
});

test("alert: create → advance sample observation → exactly one event", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await page.getByRole("button", { name: "Create alert" }).click();
  const dialog = page.getByRole("dialog", { name: "Create price alert" });
  await dialog.getByLabel("Target price").fill("172");
  await dialog.getByRole("button", { name: "Create alert" }).click();
  await expect(page.getByText("Alert armed for SX:AURORA.")).toBeVisible();

  await page.goto("/alerts");
  await expect(page.getByText("No alert has triggered yet.")).toBeVisible();
  // the worker evaluates the base observation (169.80) without triggering
  await expect(page.getByRole("table", { name: "Price alerts" }).getByText("₹169.80")).toBeVisible({ timeout: 25_000 });
  await page.getByRole("button", { name: "Advance sample session" }).click();
  await expect(page.getByText("Sample session advanced to 1 Jul 2026.")).toBeVisible();

  const events = page.getByRole("table", { name: "Triggered alert events" });
  await expect(events.getByRole("row")).toHaveCount(2, { timeout: 30_000 }); // header + one event
  await expect(events.getByText("₹173.90")).toBeVisible();
  await expect(page.getByRole("button", { name: /Notifications: 1 unread alert/ })).toBeVisible();

  // further observations (175.80 next session) do not create another event until rearmed
  await page.getByRole("button", { name: "Advance sample session" }).click();
  await page.waitForTimeout(6000); // > 2 worker cycles
  await page.reload();
  await expect(events.getByRole("row")).toHaveCount(2);
  await expect(page.getByRole("table", { name: "Price alerts" }).getByText("Triggered")).toBeVisible();
  await page.getByRole("button", { name: "Reset" }).click();
});

test("journal: create, edit and filter a note", async ({ page }) => {
  await page.goto("/journal");
  await page.getByRole("button", { name: "New note" }).click();
  let dialog = page.getByRole("dialog", { name: "New journal note" });
  await pickSymbol(page, /Instrument/, "elara", "SX:ELARA");
  await dialog.getByLabel("Title").fill("E2E thesis");
  await dialog.getByLabel("Thesis").fill("Line one\nLine two <b>not html</b>");
  await dialog.getByLabel("Tags").fill("pharma, e2e");
  await dialog.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByRole("heading", { name: "E2E thesis" })).toBeVisible();
  await expect(page.getByText("<b>not html</b>", { exact: false })).toBeVisible(); // rendered as text

  await page.getByRole("button", { name: "Edit note E2E thesis" }).click();
  dialog = page.getByRole("dialog", { name: "Edit journal note" });
  await dialog.getByLabel("Title").fill("E2E thesis v2");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: "E2E thesis v2" })).toBeVisible();

  await page.getByLabel("Filter by tag").selectOption("pharma");
  await expect(page).toHaveURL(/tag=pharma/);
  await expect(page.getByRole("heading", { name: "E2E thesis v2" })).toBeVisible();
  await page.getByLabel("Search notes").fill("nothing-matches-this");
  await expect(page.getByText("No notes match these filters")).toBeVisible();
});

test("theme: switch to light, persists across reload", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByText("Theme saved.")).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("keyboard: command palette and shortcut help without a mouse", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  await page.keyboard.press(`${MOD}+k`);
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await page.keyboard.type("portf");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/portfolio$/);
  await page.keyboard.press(`${MOD}+k`);
  await expect(palette).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  await page.keyboard.press("Escape");
  // shortcuts are ignored while typing in a field
  await page.goto("/journal");
  await page.getByLabel("Search notes").fill("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeHidden();
});

test("provider outage: cached data stays visible and marked stale, then recovers", async ({ page }) => {
  await page.goto("/instrument/SX%3AGLASSWING");
  await expect(page.getByRole("button", { name: /Data status: Sample/ }).first()).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("button", { name: "Simulate provider outage" }).click();
  await expect(page.getByText("Outage simulation is on")).toBeVisible();
  await page.goto("/instrument/SX%3AGLASSWING");
  await expect(page.getByRole("button", { name: /Data status: Stale/ }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "SX:GLASSWING" })).toBeVisible();
  await expect(page.locator(".num").filter({ hasText: /^₹1,632\.65$/ }).first()).toBeVisible(); // last value still shown
  await page.goto("/settings");
  await page.getByRole("button", { name: "End outage simulation" }).click();
  await page.goto("/instrument/SX%3AGLASSWING");
  await expect(page.getByRole("button", { name: /Data status: Sample/ }).first()).toBeVisible();
});

test("production build: SPA deep links load and unknown API routes return JSON 404", async ({ page, request }) => {
  const deep = await request.get("/journal?tag=pharma");
  expect(deep.status()).toBe(200);
  expect(deep.headers()["content-type"]).toContain("text/html");
  const api404 = await request.get("/api/does-not-exist");
  expect(api404.status()).toBe(404);
  expect(await api404.json()).toEqual({ error: { code: "not_found", message: "No such API route.", details: null } });
  await page.goto("/instrument/SX%3AHALCYON");
  await expect(page.getByRole("button", { name: "Add transaction" })).toBeDisabled();
  await expect(page.getByText(/INR-only with no currency conversion/)).toBeVisible();
});
