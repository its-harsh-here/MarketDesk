import { Dialog } from "@/components/ui/Dialog";
import { useDialogs } from "@/app/dialogs";
import { Kbd } from "./CommandPalette";
import { GLOBAL_CODES, SECURITY_CODES } from "@/lib/codes";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const MOD = isMac ? "⌘" : "Ctrl";

const ROWS: [string[], string][] = [
  [[MOD, "K"], "Open command palette"],
  [["/"], "Search symbols"],
  [["?"], "Show keyboard shortcuts"],
  [["G", "O"], "Go to Overview"],
  [["G", "W"], "Go to Watchlists"],
  [["G", "F"], "Go to Screener"],
  [["G", "M"], "Go to Macro"],
  [["G", "P"], "Go to Portfolio"],
  [["G", "A"], "Go to Alerts"],
  [["G", "J"], "Go to Journal"],
  [["G", "L"], "Go to Lab"],
  [["N"], "Add transaction"],
  [["Esc"], "Close dialog or menu"],
];

export function ShortcutsDialog() {
  const { state, close } = useDialogs();
  return (
    <Dialog open={state.kind === "shortcuts"} onOpenChange={(o) => !o && close()} title="Keyboard shortcuts" description="Shortcuts are ignored while you type in a field." size="sm">
      <table className="w-full text-[13px]">
        <caption className="sr-only">Keyboard shortcuts</caption>
        <tbody>
          {ROWS.map(([keys, label]) => (
            <tr key={label} className="border-b border-line-subtle last:border-0">
              <td className="py-2 pr-4 whitespace-nowrap">
                {keys.map((k, i) => (
                  <span key={k}>
                    <Kbd>{k}</Kbd>
                    {i < keys.length - 1 && <span className="mx-1 text-fg-3">{keys[0] === MOD ? "+" : "then"}</span>}
                  </span>
                ))}
              </td>
              <td className="py-2 text-fg-2">{label}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 className="mt-5 mb-1 text-[13px] font-medium text-fg">Function codes</h3>
      <p className="mb-2 text-xs text-fg-3">
        In the command palette, type a symbol and a code, e.g. <span className="num">RELIANCE.NS FA</span> or <span className="num">AAPL ERN</span>. On an instrument page the code alone is enough. Type <span className="num">?</span> in the palette to list them.
      </p>
      <table className="w-full text-[13px]">
        <caption className="sr-only">Function codes for a security, then for whole sections</caption>
        <tbody>
          {[...SECURITY_CODES.map((c) => [c.code, c.label] as const), ...GLOBAL_CODES.map((c) => [c.code, c.label] as const)].map(([code, label]) => (
            <tr key={code} className="border-b border-line-subtle last:border-0">
              <td className="py-1.5 pr-4 whitespace-nowrap"><Kbd>{code}</Kbd></td>
              <td className="py-1.5 text-fg-2">{label}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Dialog>
  );
}
