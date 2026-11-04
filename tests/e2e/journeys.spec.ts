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
  await page.goto("/instrument/SX%3AAURORA");
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
  await tabs.getByRole("tab", { name: "Overview" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Financials" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/tab=financials/);
  await expect(page.getByText(/SEC filings cover US-registered issuers/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Financials" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Events" }).click();
  await expect(page.getByRole("heading", { name: "Corporate actions" })).toBeVisible();
  await page.getByRole("tab", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "Price history" })).toBeVisible();
  await expect(page).not.toHaveURL(/tab=/);
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
