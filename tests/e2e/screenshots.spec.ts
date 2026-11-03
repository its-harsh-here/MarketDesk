/**
 * Visual QA captures on the deterministic test harness (synthetic data, never committed).
 * Output: tests/e2e/test-results/screenshots. Run: cd tests/e2e && npm run screenshots
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import path from "node:path";

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture review screenshots");
test.describe.configure({ mode: "serial" });

const OUT = path.resolve(import.meta.dirname, "test-results/screenshots");
const SIZES = [
  { w: 1440, h: 900 },
  { w: 1024, h: 768 },
  { w: 390, h: 844 },
];

async function seed(request: APIRequestContext) {
  const session = await (await request.get("/api/auth/session")).json();
  const headers = { "x-csrf-token": session.csrf_token };
  expect((await request.post("/api/workspace/starter-watchlist", { headers })).status()).toBe(201);
  const txns = [
    { type: "DEPOSIT", effective_date: "2026-05-01", amount: "500000" },
    { type: "BUY", effective_date: "2026-05-03", symbol: "SX:AURORA", quantity: "400", price: "158.40", fees: "20" },
    { type: "BUY", effective_date: "2026-05-04", symbol: "SX:GLASSWING", quantity: "25", price: "2610", fees: "20" },
    { type: "BUY", effective_date: "2026-05-06", symbol: "SX:PEREGRINE", quantity: "60", price: "1488.50", fees: "20" },
    { type: "SELL", effective_date: "2026-05-21", symbol: "SX:AURORA", quantity: "100", price: "171.20", fees: "20" },
  ];
  for (const t of txns) {
    expect((await request.post("/api/portfolio/transactions", { headers, data: t })).status()).toBe(201);
  }
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
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700);
}

async function shot(page: Page, name: string, w: number, opts: { fullPage?: boolean } = {}) {
  await settle(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${name} at ${w}px must not scroll horizontally`).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${OUT}/${name}-${w}.png`, fullPage: opts.fullPage });
}

test("seed sample workspace", async ({ request }) => {
  await seed(request);
});

for (const { w, h } of SIZES) {
  test(`views at ${w}x${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Daily briefing" })).toBeVisible();
    await shot(page, "overview", w);
    await page.goto("/instrument/SX%3AELARA");
    await expect(page.getByRole("heading", { name: "SX:ELARA" })).toBeVisible();
    await shot(page, "instrument", w);
    await page.goto("/portfolio");
    await expect(page.getByRole("table", { name: "Holdings" }).or(page.getByRole("list", { name: "Holdings" }))).toBeVisible();
    await shot(page, "portfolio", w, { fullPage: w === 1440 });
    await page.getByRole("button", { name: "Add transaction" }).first().click();
    await expect(page.getByRole("dialog", { name: "Add transaction" })).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Record transaction" }).click(); // show inline validation
    await shot(page, "transaction-dialog", w);
    await page.keyboard.press("Escape");
    await page.goto("/instrument/SX%3ANOPE");
    await expect(page.getByText("Could not load SX:NOPE")).toBeVisible();
    await shot(page, "error-state", w);
    await page.goto("/journal?q=no-such-note");
    await expect(page.getByText("No notes match these filters")).toBeVisible();
    await shot(page, "empty-state", w);
    await page.goto("/watchlists");
    await shot(page, "watchlists", w);
    await page.goto("/alerts");
    await shot(page, "alerts", w);
  });
}

test("light theme and command palette", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.setItem("md-theme", "light");
    document.documentElement.setAttribute("data-theme", "light");
  });
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Light" }).click();
  await page.goto("/");
  await shot(page, "overview-light", 1440);
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Dark" }).click();
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Search symbols, pages and actions/ })).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.keyboard.type("pere");
  await expect(page.getByRole("option", { name: /SX:PEREGRINE/ })).toBeVisible();
  await shot(page, "command-palette", 1440);
});
