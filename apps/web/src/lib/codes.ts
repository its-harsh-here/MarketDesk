/** Function codes (terminal roadmap T1): "SYMBOL CODE" in the command palette opens that view of the security.
 * The short codes are a common terminal convention used as a checklist; nothing here copies any vendor's design. */
export type SecurityCode = { code: string; label: string; tab?: string; hash?: string; action?: "ai" | "export" };
export type GlobalCode = { code: string; label: string; to: string };

export const SECURITY_CODES: SecurityCode[] = [
  { code: "DES", label: "Description", tab: "description" },
  { code: "GP", label: "Price chart, alerts and notes", tab: "chart" },
  { code: "FA", label: "Financial analysis", tab: "financials" },
  { code: "CN", label: "Company news and filings stream", tab: "news" },
  { code: "FIL", label: "Filings list (SEC)", tab: "filings" },
  { code: "DVD", label: "Dividends and splits", tab: "events" },
  { code: "CACS", label: "Corporate events calendar: results, dividends, meetings, buybacks", tab: "events" },
  { code: "ERN", label: "Earnings and results", tab: "earnings" },
  { code: "RV", label: "Peers and relative value", tab: "peers" },
  { code: "BETA", label: "Risk: beta, drawdowns, liquidity, universe position", tab: "risk" },
  { code: "SI", label: "Short interest (US, FINRA)", tab: "risk", hash: "short-interest" },
  { code: "DCF", label: "Valuation scenarios", tab: "valuation" },
  { code: "OMON", label: "Option chain (read-only)", tab: "options" },
  { code: "SPLC", label: "Customers and suppliers (from the annual report)", tab: "relations" },
  { code: "HDS", label: "Holders and insider transactions", tab: "holders" },
  { code: "ANR", label: "Analyst views (coverage)", tab: "description", hash: "coverage" },
  { code: "ASK", label: "Ask AI about this security", action: "ai" },
  { code: "EXP", label: "Export research", action: "export" },
];

export const GLOBAL_CODES: GlobalCode[] = [
  { code: "TOP", label: "Overview", to: "/" },
  { code: "WL", label: "Watchlists", to: "/watchlists" },
  { code: "EQS", label: "Screener", to: "/screener" },
  { code: "MOV", label: "Market movers across your universes", to: "/movers" },
  { code: "DESK", label: "Desk: linked panels for one symbol", to: "/desk" },
  { code: "ECO", label: "Macro and economic context", to: "/macro" },
  { code: "PORT", label: "Portfolio", to: "/portfolio" },
  { code: "ALRT", label: "Alerts and inbox", to: "/alerts" },
  { code: "JRNL", label: "Journal", to: "/journal" },
  { code: "LAB", label: "Research lab", to: "/lab" },
];

export type Command =
  | { kind: "security"; symbol: string | null; def: SecurityCode }
  | { kind: "global"; def: GlobalCode };

/** "AAPL FA" → security code with symbol; "FA" → security code for the current instrument; "EQS" → global. */
export function parseCommand(input: string): Command | null {
  const parts = input.trim().split(/\s+/).filter(Boolean);
  if (!parts.length || parts.length > 3) return null;
  const last = parts[parts.length - 1].toUpperCase();
  const sec = SECURITY_CODES.find((c) => c.code === last);
  const glob = GLOBAL_CODES.find((c) => c.code === last);
  if (parts.length === 1) {
    if (sec) return { kind: "security", symbol: null, def: sec };
    if (glob) return { kind: "global", def: glob };
    return null;
  }
  if (!sec) return null;
  return { kind: "security", symbol: parts.slice(0, -1).join("").toUpperCase(), def: sec };
}

export function securityPath(symbol: string, def: SecurityCode): string {
  const base = `/instrument/${encodeURIComponent(symbol)}`;
  const q = def.tab && def.tab !== "description" ? `?tab=${def.tab}` : "";
  return `${base}${q}${def.hash ? `#${def.hash}` : ""}`;
}
