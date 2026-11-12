import { ExternalLink } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { InlineNotice, SkeletonRows } from "@/components/ui/States";
import { DASH, formatLargeMoney, formatPercent, formatSessionDate, periodLabel, periodTitle } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSegments, type Segments } from "./api";

/**
 * Revenue by business segment, product line and geography from the latest annual report's XBRL data (US filers),
 * as the company tagged it. Rows can overlap (a total such as "Products" appears with its parts), so no shares of a
 * total are computed; each row shows its own growth and, where tagged, operating margin.
 */
export function SegmentsPanel({ symbol }: { symbol: string }) {
  const q = useSegments(symbol);
  const env = q.data;
  if (env && env.status === "not_applicable") return null; // not a US filer: the statements panel already says so
  const d = env?.data;
  return (
    <Panel title="Segments" titleId="seg-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading}
      meta={d ? `${d.form} filed ${formatSessionDate(d.filing_date)} · in ${d.currency ?? "reported units"}` : undefined}>
      {q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : !d ? (
        <InlineNotice>{env?.reason ?? "No segment data for this company."}</InlineNotice>
      ) : d.axes.length === 0 ? (
        <InlineNotice>The latest annual report tags no segment, product or geographic revenue breakdown.</InlineNotice>
      ) : (
        <div className="space-y-5">
          {d.axes.map((axis) => <AxisTable key={axis.axis} d={d} axis={axis} />)}
          <p className="text-xs leading-4 text-fg-3">
            From the company's XBRL data in its {d.form} (fiscal years of about twelve months only), with the company's own names.
            Rows can overlap: a total such as “Products” may appear beside its parts. Hover a header for the exact period end.{" "}
            <a className="inline-flex items-center gap-0.5 underline" href={d.url} target="_blank" rel="noopener noreferrer">
              Filing <ExternalLink className="size-3" aria-hidden />
            </a>
          </p>
        </div>
      )}
    </Panel>
  );
}

function AxisTable({ d, axis }: { d: Segments; axis: Segments["axes"][number] }) {
  const cols = d.fiscal_year_ends.filter((e) => axis.members.some((m) => m.revenue[e] !== undefined)).slice(0, 4);
  const withOp = axis.members.some((m) => Object.keys(m.operating_income).length > 0);
  const growth = (m: Segments["axes"][number]["members"][number]) => {
    const [a, b] = [m.revenue[cols[0]], m.revenue[cols[1]]];
    return a !== undefined && b !== undefined && Number(b) > 0 ? (Number(a) / Number(b) - 1) * 100 : null;
  };
  return (
    <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
      <table className="w-full text-[13px]" style={{ minWidth: 200 + 96 * cols.length + 80 + (withOp ? 110 : 0) }}>
        <caption className="py-1 text-left text-xs font-medium text-fg-2">
          {axis.label} <span className="font-normal text-fg-3">· revenue{withOp ? " and operating income" : ""}</span>
        </caption>
        <thead>
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="py-1.5 pr-3 text-left font-medium">{axis.label === "Geography" ? "Region" : "Line"}</th>
            {cols.map((e) => <th key={e} scope="col" className="num px-2 py-1.5 text-right font-medium" title={periodTitle(e, "annual")}>{periodLabel(e, "annual")}</th>)}
            <th scope="col" className="px-2 py-1.5 text-right font-medium" title="Latest fiscal year against the one before">Growth</th>
            {withOp && <th scope="col" className="px-2 py-1.5 text-right font-medium" title={`Operating income, ${periodLabel(cols[0], "annual")}`}>Op. margin</th>}
          </tr>
        </thead>
        <tbody>
          {axis.members.map((m) => {
            const g = growth(m);
            const op = m.operating_income[cols[0]];
            const rev = m.revenue[cols[0]];
            const margin = op !== undefined && rev !== undefined && Number(rev) > 0 ? (Number(op) / Number(rev)) * 100 : null;
            return (
              <tr key={m.member} className="border-b border-line-subtle/60">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg-2" title={m.member}>{m.label}</th>
                {cols.map((e) => (
                  <td key={e} className={cn("num px-2 py-1.5 text-right", m.revenue[e] === undefined && "text-fg-3")} title={m.revenue[e] === undefined ? "Not tagged for this year" : undefined}>
                    {m.revenue[e] === undefined ? DASH : formatLargeMoney(m.revenue[e], d.currency ?? "USD")}
                  </td>
                ))}
                <td className={cn("num px-2 py-1.5 text-right", g === null ? "text-fg-3" : g >= 0 ? "text-pos" : "text-neg")}>{g === null ? DASH : formatPercent(g)}</td>
                {withOp && <td className={cn("num px-2 py-1.5 text-right", margin === null && "text-fg-3")} title={margin === null ? "Operating income not tagged for this line" : undefined}>{margin === null ? DASH : formatPercent(margin, { signed: false })}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
