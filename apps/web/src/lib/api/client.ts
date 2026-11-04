import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Snapshot = Schemas["SnapshotOut"];
export type DataMeta = Schemas["DataMetaOut"];
export type DataStatus = DataMeta["status"];
export type Instrument = Schemas["InstrumentOut"];
export type HistoryResponse = Schemas["HistoryOut"];
export type Bar = Schemas["BarOut"];
export type Fundamentals = Schemas["FundamentalsOut"];
export type ActionsResponse = Schemas["ActionsOut"];
export type Watchlist = Schemas["WatchlistOut"];
export type Transaction = Schemas["TransactionOut"];
export type TransactionInput = Schemas["TransactionIn"];
export type PortfolioSummary = Schemas["PortfolioSummaryOut"];
export type PortfolioOverview = Schemas["PortfolioOverviewOut"];
export type AccountCurrency = PortfolioSummary["currency"];
export type Holding = Schemas["HoldingOut"];
export type ImportPreview = Schemas["ImportPreviewOut"];
export type Alert = Schemas["AlertOut"];
export type AlertEvent = Schemas["AlertEventOut"];
export type InboxItem = Schemas["InboxItemOut"];
export type StoredBriefing = Schemas["StoredBriefingOut"];
export type InboxCounts = Schemas["InboxCountsOut"];
export type JournalEntry = Schemas["JournalOut"];
export type JournalPage = Schemas["JournalPage"];
export type Prefs = Schemas["PrefsOut"];
export type Status = Schemas["StatusOut"];
export type MarketSession = Schemas["MarketSessionOut"];
export type CompareResponse = Schemas["CompareOut"];
export type Session = Schemas["SessionOut"];
export type Briefing = Schemas["BriefingOut"];
export type FixtureState = Schemas["FixtureStateOut"];

export interface FieldIssue {
  field: string | null;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  /** Server-side request ID (X-Request-ID / error.request_id) to quote when reporting a failure. */
  requestId: string | null;
  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId ?? null;
  }
  get fields(): FieldIssue[] {
    const d = this.details as { fields?: FieldIssue[] } | null;
    return Array.isArray(d?.fields) ? d!.fields : [];
  }
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null | undefined) {
  csrfToken = token ?? null;
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query) {
  const url = new URL(path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

async function parse(res: Response) {
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return res.json().catch(() => null);
  return res.text().catch(() => null);
}

export async function request<T>(
  method: string,
  path: string,
  opts: { query?: Query; body?: unknown; form?: FormData; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body,
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Cannot reach the MarketDesk server. Check that it is running.");
  }
  const data = await parse(res);
  if (!res.ok) {
    const e = (data as { error?: { code: string; message: string; details?: unknown; request_id?: string } } | null)?.error;
    const requestId = e?.request_id ?? res.headers.get("x-request-id");
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    if (!e && [502, 503, 504].includes(res.status)) {
      // Not our JSON: the hosting proxy answered because the app is starting, restarting or asleep.
      throw new ApiError(
        res.status,
        "server_unavailable",
        `The server is starting or temporarily unavailable (HTTP ${res.status}). Free hosting sleeps when idle; try again in a minute.`,
        undefined,
        requestId,
      );
    }
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? `Request failed (${res.status}).`, e?.details, requestId);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body, query }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: <T>(path: string, query?: Query) => request<T>("DELETE", path, { query }),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
