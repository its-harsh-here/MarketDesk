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
  await expect(page.getByRole("radiogroup", { name: "Chart range" }).getByRole("radio", { name: "1Y" })).toHaveAttribute("aria-checked", "true");
  const historyResponse = page.waitForResponse((r) => r.url().includes("/api/market/history") && r.url().includes("range=3M"));
  await page.getByRole("radiogroup", { name: "Chart range" }).getByRole("radio", { name: "3M" }).click();
  expect((await historyResponse).status()).toBe(200);
  await expect(page.getByRole("radiogroup", { name: "Chart range" }).getByRole("radio", { name: "3M" })).toHaveAttribute("aria-checked", "true");
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
  await expect(dialog.getByRole("alert").first()).toContainText("would make INR cash negative");
  await expect(dialog.getByLabel("Quantity")).toHaveValue("1000");
  // client-side validation is inline and associated with the field
  await dialog.getByLabel("Price per share").fill("-5");
  await dialog.getByRole("button", { name: "Record transaction" }).click();
  await expect(dialog.getByText("Price must be a plain number")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(summary.getByText("₹8,425.00")).toBeVisible();
});

test("USD account: an FX conversion funds a US listing; all-accounts view converts at a stated rate", async ({ page }) => {
  await page.goto("/portfolio");
  await page.getByRole("button", { name: "Convert currency" }).click();
  const dialog = page.getByRole("dialog", { name: "Add transaction" });
  await expect(dialog.getByLabel("Type")).toHaveValue("FX");
  await dialog.getByLabel("Effective date").fill("2026-01-06");
  await dialog.getByLabel("Amount converted (INR)").fill("8400");
  await dialog.getByLabel("Amount received (USD)").fill("100");
  await dialog.getByLabel("Conversion fees (INR)").fill("25");
  await dialog.getByLabel("Quoted rate (INR per USD)").fill("84");
  await expect(dialog.getByText("Effective 84.0000 INR per USD from the amounts.")).toBeVisible();
  await dialog.getByLabel("Rate source").fill("Sample Bank");
  await dialog.getByRole("button", { name: "Record transaction" }).click();
  const recorded = page.getByRole("status").filter({ hasText: "Transaction recorded." });
  await expect(recorded).toBeVisible();
  await recorded.getByRole("button", { name: "Dismiss" }).click(); // so the next confirmation is unambiguous
  await expect(recorded).toHaveCount(0);
  const summary = page.getByRole("region", { name: "Portfolio summary" });
  await expect(summary.getByText("Ledger balance · INR")).toBeVisible();
  await expect(summary.getByText("₹0.00", { exact: true }).first()).toBeVisible(); // 8,425 − 8,400 − 25

  await page.getByRole("radio", { name: "USD account" }).click();
  await expect(page).toHaveURL(/account=USD/);
  await expect(summary.getByText("$100.00").first()).toBeVisible();
  await addTransaction(page, { type: "BUY", date: "2026-01-07", symbol: "SX:HALCYON", qty: "0.5", price: "160" });
  await expect(recorded).toBeVisible();
  await expect(summary.getByText("$20.00").first()).toBeVisible(); // cash after the purchase, still in USD
  await expect(page.getByRole("table", { name: "Holdings" }).getByRole("row", { name: /SX:HALCYON/ })).toBeVisible();
  await expect(page.getByRole("table", { name: "Transaction ledger" }).getByText("INR → USD")).toBeVisible();

  await page.getByRole("radio", { name: "All accounts" }).click();
  await expect(page.getByText("All accounts, in INR at current rates")).toBeVisible();
  await expect(page.getByText(/USD\/INR 91\.3700 · sample/)).toBeVisible();
  await expect(page.getByText(/no historical rate is applied/)).toBeVisible();
  await page.getByRole("radio", { name: "INR account" }).click();
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

test("alert: crossing rule → advance sample observation → one inbox event → mark read persists", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await page.getByRole("button", { name: "Create alert" }).click();
  const dialog = page.getByRole("dialog", { name: "Create alert" });
  await dialog.getByLabel("Condition").selectOption("CROSS:ABOVE");
  await expect(dialog.getByText(/The first quote after arming is a baseline/)).toBeVisible();
  await dialog.getByLabel("Price level").fill("172");
  await dialog.getByLabel("After it fires").selectOption("");
  await dialog.getByRole("button", { name: "Create alert" }).click();
  await expect(page.getByText("Alert armed for SX:AURORA.")).toBeVisible();

  await page.goto("/alerts");
  const rules = page.getByRole("table", { name: "Alert rules" });
  await expect(rules.getByText("Crosses above 172.00", { exact: true })).toBeVisible();
  // the worker records the base observation (169.80) as the crossing baseline without firing
  await expect(rules.getByText("₹169.80")).toBeVisible({ timeout: 25_000 });
  await page.getByRole("radio", { name: "Alerts", exact: true }).click(); // inbox filter: alerts only
  await expect(page.getByText("Nothing matches these filters.")).toBeVisible();
  await page.getByRole("button", { name: "Advance sample session" }).click();
  await expect(page.getByText("Sample session advanced to 1 Jul 2026.")).toBeVisible();

  const inbox = page.getByRole("list", { name: "Inbox items" });
  await expect(inbox.getByRole("listitem")).toHaveCount(1, { timeout: 30_000 });
  await expect(inbox.getByText("Moved from 169.80 to 173.90, crossing 172.00", { exact: false })).toBeVisible();
  await expect(inbox.getByText("In-app: delivered")).toBeVisible();
  await expect(page.getByRole("button", { name: /Inbox: 1 unread/ })).toBeVisible();

  // further observations (175.80 next session) never create another event for the same arm
  await page.getByRole("button", { name: "Advance sample session" }).click();
  await page.waitForTimeout(6000); // > 2 worker cycles
  await page.reload();
  await page.getByRole("radio", { name: "Alerts", exact: true }).click();
  await expect(inbox.getByRole("listitem")).toHaveCount(1);
  await expect(rules.getByText("Triggered")).toBeVisible();

  await inbox.getByRole("button", { name: /Mark read: SX:AURORA/ }).click();
  await expect(inbox.getByText("New", { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Inbox", exact: true })).toBeVisible(); // no unread count after reload
  await page.getByRole("button", { name: "Reset" }).click();
});

test("briefing: sample end-of-session briefing appears in the inbox and the bell", async ({ page }) => {
  await page.goto("/alerts");
  await page.getByRole("button", { name: "Write sample briefing" }).click();
  await expect(page.getByText(/Sample briefing written for 30 Jun 2026/)).toBeVisible();
  await page.getByRole("radio", { name: "Briefings", exact: true }).click();
  const inbox = page.getByRole("list", { name: "Inbox items" });
  await expect(inbox.getByText("India (NSE/BSE) end-of-session briefing, 30 Jun 2026")).toBeVisible();
  await expect(inbox.getByText("Sample data", { exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "US", exact: true }).click(); // market filter
  await expect(page.getByText("Nothing matches these filters.")).toBeVisible();
  await page.getByRole("button", { name: /Inbox: \d+ unread/ }).click();
  await expect(page.getByRole("menuitem", { name: /end-of-session briefing/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Write sample briefing" }).click(); // once per session, never twice
  await expect(page.getByText(/No briefing written: it already exists/).first()).toBeVisible();
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
  // a thesis edit must say what changed; the original version is kept
  await expect(dialog.getByText("Say what changed and why")).toBeVisible();
  await dialog.getByLabel(/What changed and why/).fill("Renamed after the results call.");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("New version saved; earlier versions are unchanged.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "E2E thesis v2" })).toBeVisible();

  // history: both versions, with the change shown as removed/added lines; evidence: the stored snapshot
  await page.getByRole("button", { name: "History, evidence and reviews for E2E thesis v2" }).click();
  const detail = page.getByRole("dialog", { name: /SX:ELARA · E2E thesis v2/ });
  await expect(detail.getByText("Renamed after the results call.")).toBeVisible();
  await expect(detail.getByText("Removed: ", { exact: false }).first()).toBeAttached();
  await detail.getByRole("radio", { name: "Evidence" }).click();
  await expect(detail.getByText("Then (v1, stored)")).toBeVisible();
  await expect(detail.getByText("Now (fetched for comparison, not stored)")).toBeVisible();
  await detail.getByRole("radio", { name: /Reviews/ }).click();
  await detail.getByLabel("Outcome").selectOption("weakened");
  await detail.getByLabel("Review notes").fill("Margins slipped.");
  await detail.getByRole("button", { name: "Complete review" }).click();
  await expect(detail.getByRole("list", { name: "Review history" }).getByText("Margins slipped.")).toBeVisible();
  await detail.getByRole("button", { name: "Close", exact: true }).click();

  await page.getByLabel("Filter by tag").selectOption("pharma");
  await expect(page).toHaveURL(/tag=pharma/);
  await expect(page.getByRole("heading", { name: "E2E thesis v2" })).toBeVisible();
  await page.getByLabel("Search notes").fill("nothing-matches-this");
  await expect(page.getByText("No notes match these filters")).toBeVisible();
});

test("ai research: cited answer from retrieved evidence, sources listed, repeat request reuses the saved answer", async ({ page }) => {
  // The harness points the server at a local fake provider (Groq path): no key, no network, no cost.
  await page.goto("/instrument/SX%3AAURORA");
  await page.getByRole("button", { name: "Ask AI" }).click();
  const dialog = page.getByRole("dialog", { name: "Research SX:AURORA" });
  await dialog.getByRole("radio", { name: "Ask" }).click();
  await dialog.getByLabel("Your question").fill("What does the evidence show?");
  await dialog.getByRole("button", { name: "Run", exact: true }).click();
  const answer = dialog.getByRole("article", { name: "AI answer" });
  await expect(answer.getByText("Test-harness answer for SX:AURORA (fake AI endpoint)")).toBeVisible({ timeout: 20_000 });
  await expect(answer.getByText("Model output · openai/gpt-oss-120b via Groq (free tier)", { exact: false })).toBeVisible();
  await expect(answer.getByText("Fact", { exact: true })).toBeVisible();
  await expect(answer.getByRole("link", { name: "Source S1" }).first()).toBeVisible();
  await expect(answer.getByText("automated check", { exact: false })).toHaveCount(0); // the quoted price is in S1
  await answer.getByRole("button", { name: /Show the \d+ sources/ }).click();
  await expect(answer.getByText(/SX:AURORA last observed price/)).toBeVisible();
  // the same question on unchanged evidence is answered from the saved answer, at no cost
  await dialog.getByRole("button", { name: "Run", exact: true }).click();
  await expect(dialog.getByText(/Reused answer #\d+/)).toBeVisible({ timeout: 20_000 });
  await expect(dialog.getByText("Saved answers for SX:AURORA")).toBeVisible();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await page.goto("/settings");
  const panel = page.getByRole("region", { name: "AI research (optional)" });
  await expect(panel.getByText("On", { exact: true })).toBeVisible();
  await expect(panel.getByText(/1\/30 answers/)).toBeVisible(); // the reused answer did not count
  await expect(panel.getByText("Groq (free tier)")).toBeVisible();
  await expect(panel.getByText(/3,240 of 150,000 tokens/)).toBeVisible();
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
  // a USD listing is recorded in the USD account (preselected); an index cannot be held at all
  await page.goto("/instrument/SX%3AHALCYON");
  await page.getByRole("button", { name: "Add transaction" }).click();
  const dialog = page.getByRole("dialog", { name: "Add transaction" });
  await expect(dialog.getByLabel("Account")).toHaveValue("USD");
  await expect(dialog.getByLabel("Price per share (USD)")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await page.goto("/instrument/SX%3ASX50");
  await expect(page.getByRole("button", { name: "Add transaction" })).toBeDisabled();
  await expect(page.getByText("Indices cannot be held in the portfolio.")).toBeVisible();
});

test("instrument header: a long symbol never overlaps the price at any width", async ({ page }) => {
  // Regression: at ~450–550 px and ~1040–1140 px the symbol column shrank below the ticker's width and
  // RELIANCE.NS ran into the large price figure.
  await page.goto("/instrument/SX%3AGLASSWING");
  await expect(page.getByRole("heading", { name: "SX:GLASSWING" })).toBeVisible();
  await expect(page.locator(".num").filter({ hasText: /^₹[\d,]+\.\d{2}$/ }).first()).toBeVisible();
  const problems: string[] = [];
  for (let w = 360; w <= 1400; w += 20) {
    await page.setViewportSize({ width: w, height: 800 });
    const r = await page.evaluate(() => {
      const h1 = document.querySelector("#inst-title")!;
      const idCol = h1.parentElement!.parentElement!;
      const price = idCol.nextElementSibling!.getBoundingClientRect();
      const sameRow = Math.abs(price.top - idCol.getBoundingClientRect().top) < 4;
      return {
        overlap: sameRow && h1.getBoundingClientRect().right > price.left + 0.5,
        pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });
    if (r.overlap || r.pageOverflow) problems.push(`${w}px${r.overlap ? " overlap" : ""}${r.pageOverflow ? " page-overflow" : ""}`);
  }
  expect(problems).toEqual([]);
});

test("compare: two instruments rebased to 100 with method, table alternative and limits", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA?tab=chart");
  const cmp = page.getByRole("region", { name: "Compare" });
  await expect(cmp.getByText(/Add one or two instruments/)).toBeVisible();
  await cmp.getByRole("combobox").fill("BANYAN");
  await page.getByRole("option", { name: /SX:BANYAN/ }).first().click();
  await expect(cmp.getByText(/Base 100 on/)).toBeVisible();
  await expect(cmp.getByText(/dividends are not included/)).toBeVisible();
  await expect(cmp.getByRole("combobox")).toHaveValue(""); // picker clears after adding
  await cmp.getByRole("button", { name: "Show comparison table" }).click();
  const table = cmp.getByRole("table", { name: /Comparison values rebased to 100/ });
  await expect(table.getByRole("columnheader", { name: "SX:BANYAN" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "100.00" }).first()).toBeVisible(); // the base date row
  await cmp.getByRole("button", { name: "Remove SX:BANYAN from the comparison" }).click();
  await expect(cmp.getByText(/Add one or two instruments/)).toBeVisible();
});

test("research tabs: keyboard navigation, URL state, and an explicit reason when SEC data does not apply", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  const tabs = page.getByRole("tablist", { name: "Instrument sections" });
  await tabs.getByRole("tab", { name: "Chart" }).click();
  await expect(tabs.getByRole("tab", { name: "Chart" })).toHaveAttribute("aria-selected", "true"); // the strip follows the URL a frame or two later
  await tabs.getByRole("tab", { name: "Chart" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Financials" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/tab=financials/);
  await expect(page.getByText(/SEC filings cover US-registered issuers/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Financials" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Events" }).click();
  await expect(page.getByRole("heading", { name: "Past events" })).toBeVisible(); // T4 calendar replaced the M02 panels
  await page.getByRole("tab", { name: "Description" }).click();
  await expect(page.getByRole("heading", { name: "Price history" })).toBeVisible();
  await expect(page).not.toHaveURL(/tab=/);
  await page.locator("body").click({ position: { x: 5, y: 300 } }); // focus out of the tab strip
  await page.keyboard.press("]");
  await expect(page).toHaveURL(/tab=chart/);
  await page.keyboard.press("[");
  await page.keyboard.press("[");
  await expect(page).toHaveURL(/tab=valuation/); // wraps from the first tab to the last
});

test("screener: named list → load data → filter (missing never passes) → save → watchlist; heatmap; peers", async ({ page }) => {
  await page.goto("/screener");
  await ready(page);
  const csrf = (await (await page.request.get("/api/auth/session")).json()).csrf_token;
  await page.request.post("/api/watchlists", { data: { name: "Screen picks" }, headers: { "x-csrf-token": csrf } });
  await page.getByRole("button", { name: "Manage lists" }).click();
  const lists = page.getByRole("dialog", { name: "Screening lists" });
  await lists.getByRole("button", { name: "New list" }).click();
  await lists.getByLabel("Name").fill("E2E screen");
  await lists.getByLabel("Symbols").fill("AURORA, SX:BANYAN GLASSWING NIMBUS HALCYON BOGUS");
  await lists.getByRole("button", { name: "Save list" }).click();
  await expect(lists.getByText(/BOGUS/)).toBeVisible(); // skipped with the provider's reason, the rest saved
  await page.keyboard.press("Escape");
  await expect(page.getByRole("combobox", { name: "Universe" })).toHaveValue(/^list:/);

  const results = page.getByRole("region", { name: "Results" });
  // The worker may already have loaded the new list's members; either way the button fetches what is missing/old.
  await results.getByRole("button", { name: /^(Load|Refresh) data$/ }).click();
  const table = results.getByRole("table", { name: /Screen results for List · E2E screen/ });
  await expect(table.getByRole("row", { name: /SX:NIMBUS/ })).toBeVisible({ timeout: 30_000 });

  // P/E ≤ 20: NIMBUS has negative earnings, so no P/E — excluded and counted, never a pass
  await page.getByRole("combobox", { name: "Add a filter" }).selectOption("pe_ratio");
  await page.getByLabel("P/E (trailing) condition").selectOption("lte");
  await page.getByLabel("P/E (trailing) value").fill("20");
  await expect(table.getByRole("row", { name: /SX:NIMBUS/ })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Active filters" }).getByText(/without data \(excluded\)/)).toBeVisible();
  await expect(table.getByRole("row", { name: /SX:AURORA/ })).toBeVisible();

  // save the screen; it reopens from the URL
  await page.getByRole("button", { name: "Save this screen" }).click();
  await page.getByLabel("Name for this screen").fill("Cheap names");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved “Cheap names”.")).toBeVisible();
  await expect(page).toHaveURL(/screen=\d+/);
  await page.reload();
  await expect(page.getByLabel("P/E (trailing) value")).toHaveValue("20");

  // preview, then add a result to a watchlist
  await table.getByRole("row", { name: /SX:AURORA/ }).click();
  const preview = page.getByRole("dialog", { name: /SX:AURORA/ });
  await expect(preview.getByText("Return on equity (FY)")).toBeVisible();
  await expect(preview.getByText(/fiscal year ending 31 Mar 2026/).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await table.getByRole("checkbox", { name: "Select SX:AURORA" }).check();
  await results.getByRole("button", { name: /Add 1 to watchlist/ }).click();
  await expect(page.getByText(/1 added to|already there/)).toBeVisible();

  // heatmap over the same declared universe
  await page.getByRole("radio", { name: "Sector heatmap" }).click();
  const heat = page.getByRole("region", { name: "Sector heatmap" });
  await expect(heat.getByRole("list", { name: /Sectors by 1D change/ }).getByText("Technology")).toBeVisible();
  await expect(heat.getByText(/equally weighted/)).toBeVisible();

  // peers: suggestions from loaded instruments in the same sector, editable
  await page.goto("/instrument/SX%3AGLASSWING?tab=peers");
  const peers = page.getByRole("region", { name: "Peers" });
  await expect(peers.getByRole("columnheader", { name: /SX:NIMBUS/ })).toBeVisible({ timeout: 20_000 });
  await expect(peers.getByText("Same sector (Technology)").first()).toBeVisible();
});

test("performance & risk: time-weighted vs money-weighted, table alternative, exposure; rebalance is a simulation", async ({ page }) => {
  await page.goto("/portfolio");
  await ready(page);
  const csrf = (await (await page.request.get("/api/auth/session")).json()).csrf_token;
  const post = (data: object) => page.request.post("/api/portfolio/transactions", { data, headers: { "x-csrf-token": csrf } });
  expect((await post({ type: "DEPOSIT", effective_date: "2025-03-03", amount: "100000" })).status()).toBe(201);
  expect((await post({ type: "BUY", effective_date: "2025-03-04", symbol: "SX:GLASSWING", quantity: "30", price: "1500" })).status()).toBe(201);
  const txnCount = (await (await page.request.get("/api/portfolio/transactions")).json()).items.length;
  await page.goto("/portfolio"); // show the transactions created above

  await page.getByRole("radio", { name: "Performance & risk" }).click();
  await expect(page).toHaveURL(/section=performance/);
  const perf = page.getByRole("region", { name: "Performance" });
  await expect(perf.getByText("Time-weighted return", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(perf.getByText("Money-weighted return", { exact: true })).toBeVisible();
  await expect(perf.getByText(/Growth of 100 \(time-weighted\)/)).toBeVisible();
  await perf.getByRole("radio", { name: "Table" }).click();
  await expect(perf.getByRole("table", { name: /Daily portfolio value/ })).toBeVisible();
  await perf.getByText("How these are calculated").click();
  await expect(perf.getByText(/split-adjusted/).first()).toBeVisible();
  const exp = page.getByRole("region", { name: "Exposure and concentration" });
  await expect(exp.getByText("Effective holdings")).toBeVisible();
  await exp.getByRole("radio", { name: "Sector" }).click();
  await expect(exp.getByRole("cell", { name: "Technology" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Correlation" }).getByRole("table")).toBeVisible();

  await page.getByRole("radio", { name: "Rebalance" }).click();
  await page.getByLabel("SX:GLASSWING", { exact: true }).fill("60");
  await page.getByRole("button", { name: "Save targets" }).click();
  await expect(page.getByText("Targets saved.")).toBeVisible();
  await page.getByRole("button", { name: "Simulate with saved targets" }).click();
  const sim = page.getByRole("region", { name: "Rebalance simulation" });
  await expect(sim.getByText(/no orders are placed/).first()).toBeVisible();
  const shares = sim.getByLabel("Shares to trade for SX:GLASSWING (negative sells)");
  await shares.fill("1");
  await expect(shares).toHaveValue("1");
  // nothing was written to the ledger by the simulation
  expect((await (await page.request.get("/api/portfolio/transactions")).json()).items.length).toBe(txnCount);
});

test("valuation lab: DCF from sourced defaults, invalid assumption rejected, sensitivity, saved scenario, bank refused; stress test", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA?tab=valuation");
  await ready(page);
  await expect(page.getByText(/Hypothetical: these values follow from the assumptions/)).toBeVisible();
  await expect(page.getByText("Value per share", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/operating cash flow − capital expenditure, fiscal year ending/)).toBeVisible();
  await expect(page.getByRole("table", { name: /Value per share by Discount rate \(rows\) and Terminal growth/ })).toBeVisible();
  // terminal growth at the discount rate has no finite value: rejected on the field
  const tg = page.getByLabel(/Terminal growth \(% a year\)/);
  const dr = page.getByLabel(/Discount rate \(cost of equity\)/);
  await dr.fill("5");
  await tg.fill("5");
  await page.getByRole("button", { name: "Calculate" }).click();
  await expect(page.getByText(/at least 0.5 percentage points below the discount rate/).first()).toBeVisible();
  await dr.fill("12");
  await tg.fill("4");
  await page.getByRole("button", { name: "Calculate" }).click();
  await page.getByRole("button", { name: "Save as scenario" }).click();
  await page.getByLabel("Name", { exact: true }).fill("E2E base");
  await page.getByRole("button", { name: "Save scenario" }).click();
  await expect(page.getByText("Saved “E2E base”.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask AI about scenario E2E base" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Peer multiples" })).toBeVisible();

  await page.goto("/instrument/SX%3APEREGRINE?tab=valuation");
  await expect(page.getByText("Not applied to this company")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/banks, lenders and insurers/)).toBeVisible();

  await page.goto("/portfolio?section=performance");
  const stress = page.getByRole("region", { name: "Stress test" });
  await stress.getByRole("button", { name: "India −10%" }).click();
  await expect(stress.getByRole("table", { name: /Effect of the shocks/ })).toBeVisible({ timeout: 30_000 });
  await expect(stress.getByText(/not a forecast/)).toBeVisible();
});

test("earnings: deadline (never an announced date), fiscal-year changes, reminder alert, brief task; upcoming results", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA?tab=earnings");
  await ready(page);
  const cal = page.getByRole("region", { name: "Results calendar" });
  await expect(cal.getByText("deadline", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(cal.getByText(/SEBI LODR Regulation 33\(3\)/)).toBeVisible();
  await expect(cal.getByText(/No consensus estimates are used/)).toBeVisible();
  const chg = page.getByRole("region", { name: "Reported changes" });
  await expect(chg.getByRole("radio", { name: "Fiscal year" })).toHaveAttribute("aria-checked", "true");
  await expect(chg.getByRole("rowheader", { name: "Revenue" })).toBeVisible();
  await page.getByRole("button", { name: "Compare latest two" }).click();
  await expect(page.getByText(/SEC filings \(US registrants/)).toBeVisible();

  await cal.getByRole("button", { name: "Remind me" }).click();
  const dlg = page.getByRole("dialog", { name: "Create alert" });
  await dlg.getByLabel("Condition").selectOption("EARNINGS");
  await dlg.getByLabel("Days before").fill("7");
  await dlg.getByRole("button", { name: "Create alert" }).click();
  await expect(page.getByText("Alert armed for SX:AURORA.")).toBeVisible();

  await cal.getByRole("button", { name: "Bull · base · bear brief" }).click();
  const ai = page.getByRole("dialog", { name: "Research SX:AURORA" });
  await expect(ai.getByRole("radio", { name: "Bull · base · bear" })).toHaveAttribute("aria-checked", "true");
  await page.keyboard.press("Escape");

  await page.goto("/alerts");
  const up = page.getByRole("region", { name: "Upcoming results" });
  await expect(up.getByRole("link", { name: "SX:AURORA" })).toBeVisible({ timeout: 30_000 });
  // The rule row; the worker may already have fired the reminder (the deadline is within 7 days), which repeats the text in the inbox.
  await expect(page.getByText("Results reminder 7 day(s) before the next results date").first()).toBeVisible();
});

test("events: calendar with status marks and sources, kind filter, reported earnings history, universe calendar (CACS code)", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await ready(page);
  // The universe calendar reads the watchlists: make sure SX:AURORA is on one even when this journey runs alone.
  const csrf = (await (await page.request.get("/api/auth/session")).json()).csrf_token;
  const wl = await (await page.request.post("/api/watchlists", { data: { name: "T4 events" }, headers: { "x-csrf-token": csrf } })).json();
  if (wl.id) await page.request.post(`/api/watchlists/${wl.id}/items`, { data: { symbol: "SX:AURORA" }, headers: { "x-csrf-token": csrf } });
  await page.keyboard.press(`${MOD}+k`);
  await page.getByRole("dialog", { name: "Command palette" }).getByRole("combobox").fill("cacs");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/tab=events/);
  const up = page.getByRole("region", { name: "Upcoming" });
  await expect(up.getByText("Results due by (SEBI deadline)")).toBeVisible({ timeout: 30_000 });
  await expect(up.getByText("deadline", { exact: true }).first()).toBeVisible(); // the status pill: a regulatory deadline, never an announced date
  await expect(up.getByText(/Consensus estimates and surprises/)).toBeVisible();
  const past = page.getByRole("region", { name: "Past events" });
  await expect(past.getByText("Dividend 4.00 per share").first()).toBeVisible();
  await expect(past.getByText("Source: fixture corporate actions").first()).toBeVisible();
  const filter = past.getByRole("group", { name: "Show event kinds" });
  await filter.getByRole("button", { name: /^Dividend/ }).click();
  await expect(filter.getByRole("button", { name: /^Dividend/ })).toHaveAttribute("aria-pressed", "false");
  await expect(past.getByText("Dividend 4.00 per share")).toHaveCount(0);
  await filter.getByRole("button", { name: "Show all" }).click();
  await expect(past.getByText("Dividend 4.00 per share").first()).toBeVisible();

  await page.getByRole("tab", { name: "Earnings" }).click();
  const hist = page.getByRole("region", { name: "Earnings history" });
  const table = hist.getByRole("table", { name: "Reported figures for SX:AURORA by period" });
  await expect(table).toBeVisible({ timeout: 30_000 });
  expect(await table.getByRole("row").count()).toBeGreaterThan(2);
  await expect(table.getByRole("cell", { name: /[+-]\d+\.\d+%/ }).first()).toBeVisible(); // year-on-year change computed here
  await expect(hist.getByText(/unofficial provider data/).first()).toBeVisible();

  await page.goto("/alerts");
  const cal = page.getByRole("region", { name: "Corporate events" });
  await cal.getByRole("radiogroup", { name: "Days ahead" }).getByRole("radio", { name: "120 d" }).click();
  await expect(cal.getByRole("link", { name: "SX:AURORA" }).first()).toBeVisible({ timeout: 30_000 });
  await expect(cal.getByText("Results due by (SEBI deadline)").first()).toBeVisible();
  await expect(cal.getByText(/No consensus figures/)).toBeVisible();
});

test("macro: watchboard with provider/frequency/revision, briefing, official statistics not approximated, exposure link", async ({ page }) => {
  await page.goto("/macro");
  await ready(page);
  const board = page.getByRole("region", { name: "Macro watchboard" });
  await expect(board.getByText("SampleX Composite Index")).toBeVisible({ timeout: 30_000 });
  await expect(board.getByText(/daily \(trading days\).*Market price: not revised/).first()).toBeVisible();
  await expect(page.getByText(/Needs a FRED API key/)).toBeVisible();
  const moved = page.getByRole("region", { name: "What moved" });
  await moved.getByRole("radio", { name: "1M" }).click();
  await expect(moved.getByText(/since 2026-05/).first()).toBeVisible();
  const ex = page.getByRole("region", { name: "Exposure map" });
  await ex.getByRole("combobox", { name: "Company" }).fill("AURORA");
  await page.getByRole("option", { name: /SX:AURORA/ }).first().click();
  await ex.getByLabel("Series", { exact: true }).selectOption("SX:USDINR");
  await ex.getByLabel("Why (your note)").fill("imported turbines");
  await ex.getByRole("button", { name: "Add link" }).click();
  await expect(page.getByText("Link added.")).toBeVisible();
  await expect(ex.getByText(/Correlation -?\d\.\d\d \(daily, n = \d+\)/)).toBeVisible();
  await expect(moved.getByText(/Your link: .*imported turbines/)).toBeVisible();
  await ex.getByRole("button", { name: "Remove link SX:AURORA to SX:USDINR" }).click();
  await expect(ex.getByText(/No links yet/)).toBeVisible();
});

test("research lab: rule test executes after its signal, run ledger reproduces, paper order pending until the next session", async ({ page }) => {
  await page.goto("/lab");
  await ready(page);
  await expect(page.getByText("Simulated · nothing here is a real trade")).toBeVisible();
  await pickSymbol(page, "Instrument", "AURORA", "SX:AURORA");
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByText("Run recorded in the run ledger.")).toBeVisible({ timeout: 30_000 });
  const result = page.getByRole("region", { name: "Result" });
  await expect(result.getByRole("table", { name: /Results of the rule, buy and hold and the benchmark/ })).toBeVisible();
  await expect(result.getByText(/fingerprint/)).toBeVisible();
  await page.getByRole("radio", { name: "Run ledger" }).click();
  await page.getByRole("button", { name: "Reproduce" }).first().click();
  await expect(page.getByText("Identical data and identical results.")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("radio", { name: "Paper portfolio" }).click();
  await page.getByLabel("New paper portfolio (₹1,00,000)").fill("E2E paper");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await pickSymbol(page, "Instrument", "BANYAN", "SX:BANYAN");
  await page.getByLabel("Shares").fill("3");
  await page.getByRole("button", { name: "Place" }).click();
  await expect(page.getByText(/Simulated order placed/)).toBeVisible();
  await expect(page.getByText("Waiting for the next session's opening price.")).toBeVisible();
  await page.getByRole("radio", { name: "Read me" }).click();
  await expect(page.getByRole("heading", { name: "Survivorship bias" })).toBeVisible();
});

test("workspaces: switch from the top bar, survives reload, saved from the current layout, palette action", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  await page.getByRole("button", { name: /Switch workspace/ }).click();
  await page.getByRole("menuitem", { name: /Research/ }).click();
  await expect(page).toHaveURL(/\/screener$/);
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await page.reload();
  await ready(page);
  await expect(page.getByRole("button", { name: "Workspace: Research. Switch workspace" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await page.goto("/settings?s=workspaces");
  const panel = page.getByRole("region", { name: "Workspaces" });
  await panel.getByLabel("Name").fill("Evening review");
  await panel.getByLabel("Start page").selectOption({ label: "Journal" });
  await panel.getByRole("button", { name: "Save as workspace" }).click();
  await expect(panel.getByText("Evening review")).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("Workspace: Market");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator("html")).not.toHaveAttribute("data-density", "compact");
});

test("research export: private sections off by default, file states sources and what is private", async ({ page }) => {
  await page.goto("/instrument/SX:AURORA");
  await ready(page);
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /Export research/ });
  await expect(dialog.getByLabel("My journal entries")).not.toBeChecked();
  await expect(dialog.getByLabel("My holding")).not.toBeChecked();
  let download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download .md" }).click();
  let text = await (await download).createReadStream().then(async (s) => {
    const chunks: Buffer[] = [];
    for await (const c of s) chunks.push(c as Buffer);
    return Buffer.concat(chunks).toString("utf8");
  });
  expect(text).toContain("**Private sections included:** none.");
  expect(text).toMatch(/source fixture; status sample/);
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await dialog.getByLabel("My holding").check();
  await expect(dialog.getByText(/This file will contain private data \(holdings\)/)).toBeVisible();
  download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download .md" }).click();
  text = await (await download).createReadStream().then(async (s) => {
    const chunks: Buffer[] = [];
    for await (const c of s) chunks.push(c as Buffer);
    return Buffer.concat(chunks).toString("utf8");
  });
  expect(text).toContain("**Private sections included:** holdings.");
});

test("offline: opt-in copy is shown labelled read-only and not live when the server is unreachable", async ({ page, context }) => {
  await page.goto("/settings?s=offline");
  await ready(page);
  await page.getByLabel("Keep a read-only offline copy on this device").check();
  await expect(page.getByText(/Last synced: \d/)).toBeVisible();
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload(); // now controlled by the service worker
  await ready(page);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Offline copy · read-only · not live" })).toBeVisible();
  await expect(page.getByText(/Synced from this device on/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Add transaction" })).toHaveCount(0);
  await context.setOffline(false);
  await page.getByRole("button", { name: "Try the server again" }).click();
  await ready(page);
  await page.goto("/settings?s=offline");
  await page.getByLabel("Keep a read-only offline copy on this device").uncheck();
  expect(await page.evaluate(() => localStorage.getItem("md-offline-snapshot"))).toBeNull();
});

test("description: tiles with sources, coverage with reasons, function codes from the palette", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await ready(page);
  await expect(page.getByRole("tab", { name: "Description" })).toHaveAttribute("aria-selected", "true");
  const biz = page.getByRole("region", { name: "Business" });
  await expect(biz.getByText(/fictitious company in MarketDesk's sample dataset/)).toBeVisible();
  await expect(biz.getByText(/company profile, as supplied by the provider \(not verified\)/)).toBeVisible();
  const stats = page.getByRole("region", { name: "Key statistics" });
  await expect(stats.getByText("Last price")).toBeVisible();
  await expect(stats.getByText(/Snapshot computed/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Identity" }).getByText(/Classification: fixture fundamentals/)).toBeVisible();
  const cov = page.getByRole("table", { name: /Which kinds of data are available for SX:AURORA/ });
  await expect(cov.getByRole("row", { name: /Consensus estimates and analyst ratings/ })).toContainText("Licensed data");
  await expect(cov.getByRole("row", { name: /^Filings/ })).toContainText("No filing source applies");
  // function codes: "SYMBOL CODE" jumps to that view; "?" lists codes
  await page.keyboard.press(`${MOD}+k`);
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await palette.getByRole("combobox").fill("glasswing fa");
  await expect(palette.getByRole("option", { name: /SX:GLASSWING FA/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/instrument\/SX%3AGLASSWING\?tab=financials$/);
  await expect(page.getByRole("tab", { name: "Financials" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press(`${MOD}+k`);
  await palette.getByRole("combobox").fill("?");
  await expect(palette.getByRole("option", { name: /SX:GLASSWING RV/ })).toBeVisible();
  await expect(palette.getByRole("option", { name: /EQS/ })).toBeVisible();
  await palette.getByRole("combobox").fill("dvd");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/tab=events/);
  await page.keyboard.press(`${MOD}+k`);
  await palette.getByRole("combobox").fill("hds");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#coverage$/);
  await expect(page.getByRole("heading", { name: "Coverage for this listing" })).toBeInViewport();
});

test("financial analysis: margins, growth, returns with formulas; unofficial provider data labelled; bands explain gaps", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA?tab=financials");
  await ready(page);
  const fa = page.getByRole("region", { name: "Financial analysis" });
  await expect(fa.getByText("Unofficial", { exact: true })).toBeVisible();
  await expect(fa.getByRole("table", { name: /Margins/ })).toBeVisible();
  await expect(fa.getByRole("table", { name: /Growth/ })).toBeVisible();
  await expect(fa.getByText(/Compound annual growth: Fewer than 3 years reported/)).toBeVisible(); // sample has 3 years
  await expect(fa.getByText(/Not available from this source \(per share\)/)).toBeVisible();
  await expect(fa.getByRole("rowheader", { name: /Net margin \(Net income ÷ revenue × 100\)/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Valuation bands" }).getByText(/need reported EPS/)).toBeVisible();
  await page.getByRole("radio", { name: "Quarterly" }).click();
  await expect(fa.getByText(/annual provider statements only/)).toBeVisible();
});

test("risk: beta against the benchmark (changeable), drawdowns, liquidity estimate, universe position, gated short interest", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await ready(page);
  await page.keyboard.press(`${MOD}+k`);
  await page.getByRole("dialog", { name: "Command palette" }).getByRole("combobox").fill("beta");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/tab=risk/);
  const sens = page.getByRole("region", { name: "Benchmark sensitivity" });
  await expect(sens.getByRole("table", { name: /against SX:SX50/ })).toBeVisible();
  await expect(sens.getByText(/daily returns \(same trading time zone\)/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Volatility and drawdowns" }).getByRole("table", { name: /Deepest declines/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Liquidity" }).getByText(/No bid-ask spread is shown/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Within your universe" }).getByText(/\d+ members · \d+ with data/)).toBeVisible();
  await expect(page.getByRole("table", { name: /Where SX:AURORA sits within All watchlists/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Short interest" }).getByText(/US-traded securities/)).toBeVisible();
  await pickSymbol(page, "Benchmark", "BANYAN", "SX:BANYAN");
  await expect(page).toHaveURL(/bench=SX%3ABANYAN/);
  await expect(sens.getByRole("table", { name: /against SX:BANYAN/ })).toBeVisible();
});

test("accessibility: no serious or critical WCAG 2.1 A/AA violations on the main screens", async ({ page }) => {
  const { default: AxeBuilder } = await import("@axe-core/playwright");
  const views = ["/", "/watchlists", "/screener", "/macro", "/portfolio", "/portfolio?section=performance", "/alerts", "/journal", "/lab", "/settings",
    "/instrument/SX%3AAURORA", "/instrument/SX%3AAURORA?tab=financials", "/instrument/SX%3AAURORA?tab=risk", "/instrument/SX%3AAURORA?tab=valuation"];
  const problems: string[] = [];
  for (const url of views) {
    await page.goto(url);
    await ready(page);
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    for (const v of results.violations) {
      if (v.impact === "serious" || v.impact === "critical") problems.push(`${url}: ${v.id} (${v.impact}) ${v.nodes[0]?.target.join(" ")}`);
    }
  }
  expect(problems, problems.join("\n")).toEqual([]);
});

test("interaction polish: keyboard rows, undo after removing a symbol, palette recents and prefilled actions, tab-strip fade", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  const csrf = (await (await page.request.get("/api/auth/session")).json()).csrf_token;
  const h = { "x-csrf-token": csrf };
  const wl = await (await page.request.post("/api/watchlists", { data: { name: "Keys" }, headers: h })).json();
  for (const s of ["SX:AURORA", "SX:COBALT", "SX:ELARA"]) await page.request.post(`/api/watchlists/${wl.id}/items`, { data: { symbol: s }, headers: h });
  await page.goto(`/watchlists?id=${wl.id}`);
  await ready(page);
  // rows are keyboard rows: ↓ moves, Enter opens the instrument
  const rows = page.getByRole("table", { name: "Keys watchlist" }).locator("tbody tr[data-row]");
  await expect(rows).toHaveCount(3);
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(1)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/instrument\/SX%3ACOBALT$/);
  await expect(page.getByRole("heading", { name: "SX:COBALT" })).toBeVisible();
  // removing from a watchlist can be undone from the toast
  await page.goto(`/watchlists?id=${wl.id}`);
  await ready(page);
  await page.getByRole("button", { name: "Remove SX:AURORA from Keys" }).click();
  await expect(page.getByText("Removed SX:AURORA from Keys.")).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByText("SX:AURORA is back in Keys.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove SX:AURORA from Keys" })).toBeVisible();
  // palette: recently viewed instruments when nothing is typed; actions prefilled with the current instrument
  await page.goto("/instrument/SX%3ABANYAN");
  await ready(page);
  await page.keyboard.press(`${MOD}+k`);
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette.getByRole("option", { name: /SX:COBALT.*recently viewed/ })).toBeVisible();
  await palette.getByRole("combobox").fill("create alert");
  await palette.getByRole("option", { name: "Create alert for SX:BANYAN" }).click();
  await expect(page.getByRole("dialog", { name: "Create alert" }).getByRole("combobox", { name: /Instrument/ })).toHaveValue("SX:BANYAN");
  await page.keyboard.press("Escape");
  // on a phone the tab strip shows a fade where more tabs are hidden, and the selected tab scrolls into view
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/instrument/SX%3ABANYAN?tab=valuation");
  await ready(page);
  const fades = page.locator('[aria-label="Instrument sections"] ~ div[aria-hidden]');
  await expect(fades).toHaveCount(1); // scrolled to the end: only the left fade remains
  await expect(page.getByRole("tab", { name: "Valuation" })).toBeInViewport();
});

test("news: CN opens the stream, filters, sample headlines without links, cited-AI entry point", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await ready(page);
  await page.keyboard.press(`${MOD}+k`);
  await page.getByRole("dialog", { name: "Command palette" }).getByRole("combobox").fill("cn");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/tab=news/);
  const panel = page.getByRole("region", { name: "News and filings" });
  const list = panel.getByRole("list", { name: "News and filings for SX:AURORA, newest first" });
  await expect(list.getByText(/declares dividend/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(list.getByRole("link")).toHaveCount(0); // sample headlines have no article behind them
  await expect(panel.getByText("Sample wire (fictitious)").first()).toBeVisible();
  await panel.getByRole("radiogroup", { name: "Show" }).getByRole("radio", { name: /^Filings/ }).click();
  await expect(panel.getByText("Nothing of this kind")).toBeVisible();
  await panel.getByRole("radiogroup", { name: "Show" }).getByRole("radio", { name: /^All/ }).click();
  const about = page.getByRole("region", { name: "About this stream" });
  await expect(about.getByText(/Indian listings need a permitted source/)).toBeVisible();
  await about.getByRole("button", { name: "Cited AI summary of recent filings" }).click();
  await expect(page.getByRole("dialog", { name: "Research SX:AURORA" }).getByRole("radio", { name: "Catalysts" })).toHaveAttribute("aria-checked", "true");
});


test("movers: MOV code, breadth, gainers and losers open the instrument; terminal density preset", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  const csrf = (await (await page.request.get("/api/auth/session")).json()).csrf_token;
  await page.request.post("/api/workspace/starter-watchlist", { headers: { "x-csrf-token": csrf } });
  await page.keyboard.press(`${MOD}+k`);
  await page.getByRole("dialog", { name: "Command palette" }).getByRole("combobox").fill("mov");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/movers/);
  await expect(page.getByRole("img", { name: /\d+ advancing, \d+ declining, \d+ unchanged/ })).toBeVisible({ timeout: 30_000 });
  const gainers = page.getByRole("region", { name: "Top gainers" });
  const losers = page.getByRole("region", { name: "Top losers" });
  await expect(gainers.getByRole("button").first()).toBeVisible();
  await expect(losers.getByRole("button").first()).toBeVisible();
  const first = (await losers.getByRole("button").first().innerText()).match(/SX:[A-Z0-9]+/)![0];
  await losers.getByRole("button").first().click();
  await expect(page).toHaveURL(new RegExp(`/instrument/${encodeURIComponent(first)}`));

  await page.goto("/settings");
  await page.getByRole("radiogroup", { name: "Table density" }).getByRole("radio", { name: "Terminal" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "terminal");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-density", "terminal");
  await page.getByRole("radiogroup", { name: "Table density" }).getByRole("radio", { name: "Comfortable" }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-density", /.+/);
});

test("quote page extras: performance overview vs benchmark, chart indicators in their own panes, CSV of daily prices", async ({ page }) => {
  await page.goto("/instrument/SX%3AAURORA");
  await ready(page);
  const perf = page.getByRole("region", { name: "Performance overview" });
  const table = perf.getByRole("table", { name: "Price return of SX:AURORA and its benchmark by period" });
  await expect(table.getByRole("rowheader", { name: /^1 year/ })).toBeVisible({ timeout: 30_000 });
  await expect(perf.getByText(/vs .* · to 30 Jun 2026/)).toBeVisible();
  await expect(perf.getByRole("img", { name: /from the 52-week high/ })).toBeVisible();

  const chart = page.getByRole("region", { name: "Price history" });
  await chart.getByRole("button", { name: /^Indicators/ }).click();
  await page.getByRole("menuitemcheckbox", { name: /SMA 50/ }).click();
  await page.getByRole("menuitemcheckbox", { name: /RSI 14/ }).click();
  await page.keyboard.press("Escape");
  await expect(chart.getByRole("button", { name: /^Indicators 2/ })).toBeVisible();
  await page.reload(); // the choice is remembered in this browser
  await expect(page.getByRole("region", { name: "Price history" }).getByRole("button", { name: /^Indicators 2/ })).toBeVisible();

  await page.getByRole("region", { name: "Price history" }).getByRole("button", { name: "Show data table" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download these prices as CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("SX_AURORA_1Y_daily.csv");
  const text = await (await import("node:fs/promises")).readFile(await file.path(), "utf8");
  expect(text.split("\n")[0]).toBe("session,open,high,low,close,volume");
  expect(text.split("\n").length).toBeGreaterThan(200);

  // weekly interval: one row per week, a change column, and a weekly CSV
  const panel = page.getByRole("region", { name: "Price history" });
  await panel.getByRole("radiogroup", { name: "Interval" }).getByRole("radio", { name: "W" }).click();
  await expect(panel.getByRole("columnheader", { name: "Week to" })).toBeVisible();
  await expect(panel.getByRole("columnheader", { name: "Change" })).toBeVisible();
  const weekly = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download these prices as CSV" }).click();
  const wf = await weekly;
  expect(wf.suggestedFilename()).toBe("SX_AURORA_1Y_weekly.csv");
  const wt = await (await import("node:fs/promises")).readFile(await wf.path(), "utf8");
  const n = wt.trim().split("\n").length - 1;
  expect(n).toBeGreaterThan(48);
  expect(n).toBeLessThan(56);
});

test("currency converter on Macro: converts at the sample rate, swaps, rejects bad input", async ({ page }) => {
  await page.goto("/macro");
  await ready(page);
  const conv = page.getByRole("region", { name: "Currency converter" });
  await expect(conv.getByText(/USD per|INR per USD|at [\d.]+ INR per USD/)).toBeVisible({ timeout: 30_000 });
  await expect(conv.getByText(/Indicative/)).toBeVisible();
  await conv.getByRole("button", { name: "Swap currencies" }).click();
  await expect(conv.getByRole("combobox", { name: "From currency" })).toHaveValue("INR");
  await expect(conv.getByText(/Derived from the reverse pair/)).toBeVisible();
  await conv.getByLabel("Amount").fill("0");
  await expect(conv.getByText("Enter a positive amount (up to six decimals).")).toBeVisible();
});

test("watchlist key figures: market cap, P/E and 1Y from stored snapshots, with a reason before data is loaded", async ({ page }) => {
  await page.goto("/");
  await ready(page);
  const csrf = (await (await page.request.get("/api/auth/session")).json()).csrf_token;
  const headers = { "x-csrf-token": csrf };
  const wl = await (await page.request.post("/api/watchlists", { data: { name: "Figures" }, headers })).json();
  for (const s of ["SX:AURORA", "SX:BANYAN"]) await page.request.post(`/api/watchlists/${wl.id}/items`, { data: { symbol: s }, headers });
  await page.request.post("/api/screener/refresh", { data: { universe: { kind: "watchlist", id: wl.id } }, headers });
  await expect.poll(async () => (await (await page.request.get("/api/screener/refresh")).json()).running, { timeout: 30_000 }).toBe(false);
  await page.goto(`/watchlists?id=${wl.id}`);
  const table = page.getByRole("table", { name: /Figures watchlist/ });
  await expect(table.getByRole("columnheader", { name: "Mkt cap" })).toBeVisible({ timeout: 30_000 });
  const row = table.getByRole("row", { name: /SX:AURORA/ });
  await expect(row.getByText(/^\d+(\.\d+)?×$/)).toBeVisible(); // trailing P/E
  await expect(row.getByText(/Cr|L|K|M|B/).first()).toBeVisible(); // market cap in compact units
});

test("desk: one linked symbol drives every panel; slot choice is remembered; g d opens it", async ({ page }) => {
  await page.goto("/instrument/SX%3ABANYAN");
  await ready(page);
  await expect(page.getByRole("heading", { name: "Price history" })).toBeVisible(); // the page has loaded and recorded the visit
  await page.keyboard.press("g");
  await page.keyboard.press("d");
  await expect(page).toHaveURL(/\/desk/);
  // the most recently viewed instrument is the starting symbol
  await expect(page.getByRole("region", { name: "SX:BANYAN price" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("list", { name: "Latest news and filings for SX:BANYAN" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Performance overview" })).toBeVisible();
  await pickSymbol(page, /Linked symbol/, "AURORA", "SX:AURORA");
  await expect(page).toHaveURL(/s=SX%3AAURORA/);
  await expect(page.getByRole("region", { name: "SX:AURORA price" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Latest news and filings for SX:AURORA" })).toBeVisible();
  const slot4 = page.getByRole("combobox", { name: "Panel 4 shows" });
  await expect(slot4.locator("option", { hasText: "Price chart (in use)" })).toHaveJSProperty("disabled", true);
  await slot4.selectOption("earnings");
  await expect(page.getByRole("region", { name: "Earnings history" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Panel 4 shows" })).toHaveValue("earnings");
  await page.getByRole("button", { name: "Default layout" }).click();
  await expect(page.getByRole("combobox", { name: "Panel 4 shows" })).toHaveValue("events");
});
