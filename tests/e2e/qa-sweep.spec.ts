/**
 * One-off QA sweep (not part of CI): every page, tab and dialog at four widths, with
 *  - a full-page screenshot,
 *  - the horizontal-overflow check,
 *  - an axe-core WCAG 2.1 A/AA audit,
 *  - console errors, page errors and failed API responses.
 * Run: cd tests/e2e && QA_SWEEP=1 QA_OUT=/path npx playwright test qa-sweep.spec.ts
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test.skip(!process.env.QA_SWEEP, "set QA_SWEEP=1 to run the QA sweep");
test.describe.configure({ mode: "serial" });
test.setTimeout(10 * 60_000);

const OUT = process.env.QA_OUT ?? path.resolve(import.meta.dirname, "test-results/qa-sweep");
const SIZES = [1440, 1024, 768, 390] as const;
const MOD = process.platform === "darwin" ? "Meta" : "Control";

type Finding = { view: string; width: number; kind: string; detail: string };
const findings: Finding[] = [];

async function seed(request: APIRequestContext) {
  const session = await (await request.get("/api/auth/session")).json();
  const headers = { "x-csrf-token": session.csrf_token };
  await request.post("/api/workspace/starter-watchlist", { headers });
  const txns = [
    { type: "DEPOSIT", effective_date: "2026-05-01", amount: "500000" },
    { type: "BUY", effective_date: "2026-05-03", symbol: "SX:AURORA", quantity: "400", price: "158.40", fees: "20" },
    { type: "BUY", effective_date: "2026-05-04", symbol: "SX:GLASSWING", quantity: "25", price: "2610", fees: "20" },
    { type: "BUY", effective_date: "2026-05-06", symbol: "SX:PEREGRINE", quantity: "60", price: "1488.50", fees: "20" },
    { type: "SELL", effective_date: "2026-05-21", symbol: "SX:AURORA", quantity: "100", price: "171.20", fees: "20" },
    { type: "DEPOSIT", effective_date: "2026-05-01", amount: "20000", currency: "USD" },
    { type: "BUY", effective_date: "2026-05-05", symbol: "SX:HALCYON", quantity: "30", price: "120", fees: "1", currency: "USD" },
  ];
  for (const t of txns) await request.post("/api/portfolio/transactions", { headers, data: t });
  await request.post("/api/alerts", { headers, data: { symbol: "SX:AURORA", direction: "ABOVE", target_price: "172" } });
  await request.post("/api/alerts", { headers, data: { symbol: "SX:PEREGRINE", direction: "BELOW", target_price: "1050" } });
  await request.post("/api/journal", {
    headers,
    data: {
      symbol: "SX:GLASSWING", entry_date: "2026-05-04", title: "Services demand thesis (sample)",
      thesis: "Order book growth should hold through the next two quarters.\nWatch margins.",
      risks: "Client concentration; currency moves.", invalidation: "Two consecutive quarters of falling orders.",
      tags: ["software", "sample"], review_date: "2026-08-01",
    },
  });
  await request.post("/api/lab/runs", { headers, data: { symbol: "SX:AURORA", rule: "sma_cross", params: { fast: 20, slow: 50 }, fee_pct: "0.1", slippage_bps: "5" } });
  const pf = await (await request.post("/api/lab/paper", { headers, data: { name: "QA paper", starting_cash: "100000" } })).json();
  if (pf?.id) await request.post(`/api/lab/paper/${pf.id}/orders`, { headers, data: { side: "BUY", symbol: "SX:BANYAN", quantity: "3" } });
  await request.post("/api/screener/refresh", { headers, data: { universe: { kind: "watchlists" } } });
  await request.post("/api/macro/links", { headers, data: { symbol: "SX:AURORA", series: "SX:SX50", relation: "benchmark", direction: "positive", note: "sample" } }).catch(() => undefined);
}

function watch(page: Page, view: () => string, width: number) {
  page.on("console", (msg) => {
    if (msg.type() === "error") findings.push({ view: view(), width, kind: "console", detail: msg.text().slice(0, 300) });
  });
  page.on("pageerror", (err) => findings.push({ view: view(), width, kind: "pageerror", detail: String(err).slice(0, 300) }));
  page.on("response", (r) => {
    const u = r.url();
    if (r.status() >= 400 && u.includes("/api/") && !u.includes("SX%3ANOPE") && !u.includes("SX:NOPE")) {
      findings.push({ view: view(), width, kind: `http ${r.status()}`, detail: u.replace(/^https?:\/\/[^/]+/, "") });
    }
  });
}

async function audit(page: Page, name: string, width: number, opts: { fullPage?: boolean; dialog?: boolean } = {}) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(600);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 0) findings.push({ view: name, width, kind: "overflow", detail: `${overflow}px horizontal overflow` });
  fs.mkdirSync(`${OUT}/${width}`, { recursive: true });
  await page.screenshot({ path: `${OUT}/${width}/${name}.png`, fullPage: opts.fullPage ?? !opts.dialog });
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  for (const v of results.violations) {
    for (const n of v.nodes.slice(0, 3)) {
      findings.push({ view: name, width, kind: `axe:${v.impact}:${v.id}`, detail: `${n.target.join(" ")} — ${(n.failureSummary ?? "").split("\n")[1] ?? v.help}`.slice(0, 260) });
    }
  }
}

const PAGES: { name: string; url: string; ready?: (p: Page) => Promise<void> }[] = [
  { name: "overview", url: "/" },
  { name: "watchlists", url: "/watchlists" },
  { name: "screener", url: "/screener" },
  { name: "screener-heatmap", url: "/screener?view=heatmap" },
  { name: "macro", url: "/macro" },
  { name: "lab-test", url: "/lab" },
  { name: "lab-ledger", url: "/lab", ready: (p) => p.getByRole("radio", { name: "Run ledger" }).click() },
  { name: "lab-paper", url: "/lab", ready: (p) => p.getByRole("radio", { name: "Paper portfolio" }).click() },
  { name: "lab-readme", url: "/lab", ready: (p) => p.getByRole("radio", { name: "Read me" }).click() },
  { name: "inst-description", url: "/instrument/SX%3AAURORA" },
  { name: "inst-chart", url: "/instrument/SX%3AAURORA?tab=chart" },
  { name: "inst-financials", url: "/instrument/SX%3AAURORA?tab=financials" },
  { name: "inst-filings", url: "/instrument/SX%3AAURORA?tab=filings" },
  { name: "inst-events", url: "/instrument/SX%3AAURORA?tab=events" },
  { name: "inst-earnings", url: "/instrument/SX%3AAURORA?tab=earnings" },
  { name: "inst-peers", url: "/instrument/SX%3AGLASSWING?tab=peers" },
  { name: "inst-risk", url: "/instrument/SX%3AAURORA?tab=risk" },
  { name: "inst-valuation", url: "/instrument/SX%3AAURORA?tab=valuation" },
  { name: "inst-index", url: "/instrument/SX%3ASX50" },
  { name: "portfolio", url: "/portfolio" },
  { name: "portfolio-usd", url: "/portfolio?account=USD" },
  { name: "portfolio-performance", url: "/portfolio?section=performance" },
  { name: "portfolio-rebalance", url: "/portfolio?section=rebalance" },
  { name: "alerts", url: "/alerts" },
  { name: "journal", url: "/journal" },
  { name: "journal-empty", url: "/journal?q=no-such-note" },
  { name: "settings", url: "/settings" },
  { name: "not-found", url: "/nope" },
  { name: "instrument-error", url: "/instrument/SX%3ANOPE" },
];

test("seed", async ({ request }) => {
  await seed(request);
  await new Promise((r) => setTimeout(r, 4000)); // let the screener snapshot job finish
});

for (const width of SIZES) {
  test(`pages at ${width}`, async ({ page }) => {
    let current = "";
    watch(page, () => current, width);
    await page.setViewportSize({ width, height: width === 390 ? 844 : width === 768 ? 1024 : 900 });
    for (const p of PAGES) {
      current = p.name;
      await page.goto(p.url);
      await page.getByRole("button", { name: /Search symbols, pages and actions/ }).waitFor().catch(() => undefined);
      if (p.ready) await p.ready(page).catch((e) => findings.push({ view: p.name, width, kind: "ready-failed", detail: String(e).slice(0, 200) }));
      await audit(page, p.name, width);
    }
    fs.writeFileSync(`${OUT}/findings-${width}.json`, JSON.stringify(findings.filter((f) => f.width === width), null, 2));
  });
}

for (const width of [1440, 390] as const) {
  test(`dialogs at ${width}`, async ({ page }) => {
    let current = "";
    watch(page, () => current, width);
    page.setDefaultTimeout(15_000); // a missing control is a finding, not a ten-minute wait
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const openAndAudit = async (name: string, go: () => Promise<void>, dialogName: string | RegExp) => {
      current = `dialog-${name}`;
      try {
        await go();
        await expect(page.getByRole("dialog", { name: dialogName })).toBeVisible({ timeout: 10_000 });
        await audit(page, `dialog-${name}`, width, { dialog: true });
      } catch (e) {
        findings.push({ view: current, width, kind: "dialog-failed", detail: String(e).slice(0, 200) });
      }
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
    };
    await page.goto("/portfolio");
    await page.getByRole("button", { name: /Search symbols, pages and actions/ }).waitFor();
    await openAndAudit("palette", async () => { await page.keyboard.press(`${MOD}+k`); await page.keyboard.type("aur"); }, "Command palette");
    await openAndAudit("shortcuts", async () => { await page.keyboard.press("?"); }, "Keyboard shortcuts");
    await openAndAudit("transaction", async () => { await page.getByRole("button", { name: "Add transaction" }).first().click(); await page.getByRole("dialog").getByRole("button", { name: "Record transaction" }).click(); }, "Add transaction");
    await openAndAudit("import", async () => { await page.getByRole("button", { name: "Import CSV" }).first().click(); }, /Import/);
    await page.goto("/instrument/SX%3AAURORA");
    await page.getByRole("heading", { name: "SX:AURORA" }).waitFor();
    await openAndAudit("alert", async () => { await page.getByRole("button", { name: "Create alert" }).click(); }, "Create alert");
    await openAndAudit("journal-new", async () => { await page.getByRole("button", { name: "Note", exact: true }).click(); }, /note|journal/i);
    await openAndAudit("ai", async () => { await page.getByRole("button", { name: "Ask AI" }).click(); }, /Research SX:AURORA/);
    await openAndAudit("export", async () => { await page.getByRole("button", { name: "Export", exact: true }).click(); }, /Export research/);
    await page.goto("/watchlists");
    await openAndAudit("new-watchlist", async () => { await page.getByRole("button", { name: /Create watchlist|New watchlist|Add watchlist/ }).first().click(); }, "New watchlist");
    await openAndAudit("add-symbol", async () => { await page.getByRole("button", { name: /Add symbol/ }).first().click(); }, /Add/);
    await page.goto("/journal");
    await openAndAudit("journal-detail", async () => { await page.getByRole("button", { name: /v1|version|history/i }).first().click(); }, /Services demand thesis/);
    fs.writeFileSync(`${OUT}/findings-dialogs-${width}.json`, JSON.stringify(findings.filter((f) => f.width === width && f.view.startsWith("dialog-")), null, 2));
  });
}
