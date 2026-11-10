import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, type ComponentType, type ReactNode } from "react";
import { Link, Outlet, RouterProvider, createBrowserRouter } from "react-router";
import { ToastProvider } from "@/components/ui/Toast";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { ErrorState, SkeletonRows } from "@/components/ui/States";
import { ApiError, errorMessage, setCsrfToken, setUnauthorizedHandler } from "@/lib/api/client";
import { applyDensity, applyTheme, usePrefs, useSession } from "@/features/settings/api";
import { FxBackground } from "@/lib/fx";
import { AddSymbolDialog, NewWatchlistDialog, WatchlistsPage } from "@/features/watchlists/WatchlistsPage";
import { TransactionDialog } from "@/features/portfolio/TransactionDialog";
import { ImportDialog } from "@/features/portfolio/ImportDialog";
import { AlertDialog } from "@/features/alerts/AlertDialog";
import { JournalDialog } from "@/features/journal/JournalDialog";
import { JournalDetailDialog } from "@/features/journal/JournalDetailDialog";
import { AiDialog } from "@/features/ai/AiDialog";
import { ExportDialog } from "@/features/workspace/ExportDialog";
import { OfflineView } from "@/features/workspace/OfflineView";
import { clearOffline, readSnapshot } from "@/lib/offline";
import { clearRecents } from "@/lib/recent";
import { LoginPage } from "@/features/auth/LoginPage";

// Each page is its own chunk, fetched on first visit: the first paint no longer waits for every screen's code.
// A page shows a layout-shaped skeleton while its chunk loads (normally only once per deploy; chunks are cached).
function page<P extends object>(load: () => Promise<Record<string, unknown>>, name: string) {
  const Component = lazy(() => load().then((m) => ({ default: m[name] as ComponentType<P> })));
  return (
    <Suspense
      fallback={
        <div className="p-4 md:p-6" role="status" aria-label="Loading page">
          <SkeletonRows rows={10} />
        </div>
      }
    >
      <Component {...({} as P)} />
    </Suspense>
  );
}
const overview = page(() => import("@/features/overview/OverviewPage"), "OverviewPage");
// The watchlist dialogs are global, so this module is in the main chunk anyway.
const watchlists = <WatchlistsPage />;
const screener = page(() => import("@/features/screener/ScreenerPage"), "ScreenerPage");
const movers = page(() => import("@/features/movers/MoversPage"), "MoversPage");
const macro = page(() => import("@/features/macro/MacroPage"), "MacroPage");
const lab = page(() => import("@/features/lab/LabPage"), "LabPage");
const instrument = page(() => import("@/features/instrument/InstrumentPage"), "InstrumentPage");
const portfolio = page(() => import("@/features/portfolio/PortfolioPage"), "PortfolioPage");
const alerts = page(() => import("@/features/alerts/AlertsPage"), "AlertsPage");
const journal = page(() => import("@/features/journal/JournalPage"), "JournalPage");
const settings = page(() => import("@/features/settings/SettingsPage"), "SettingsPage");
import { CommandPalette } from "@/features/search/CommandPalette";
import { ShortcutsDialog } from "@/features/search/ShortcutsDialog";
import { DialogProvider } from "./dialogs";
import { Shell } from "./Shell";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      refetchOnWindowFocus: true,
      // Moving between pages reuses results fetched in the last 15 s instead of refetching everything.
      staleTime: 15_000,
    },
  },
});

function ThemeSync() {
  const { data: prefs } = usePrefs();
  useEffect(() => {
    if (!prefs) return;
    applyTheme(prefs.theme);
    applyDensity(prefs.density);
  }, [prefs]);
  return null;
}

function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const session = useSession();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearOffline(); // the session ended: no private copy stays on this device
      clearRecents();
      qc.invalidateQueries({ queryKey: ["session"] });
    });
  }, [qc]);
  useEffect(() => {
    setCsrfToken(session.data?.csrf_token);
  }, [session.data?.csrf_token]);
  if (session.isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status" aria-label="Loading MarketDesk">
        <span className="skeleton h-6 w-40" />
      </div>
    );
  }
  if (session.isError) {
    const err = session.error;
    const unreachable = err instanceof ApiError && (err.status === 0 || err.code === "server_unavailable");
    const snap = unreachable ? readSnapshot() : null;
    if (snap) return <OfflineView snapshot={snap} reason="The MarketDesk server cannot be reached, so this device's last copy is shown." onRetry={() => session.refetch()} />;
    return (
      <main className="flex min-h-dvh items-center justify-center p-4">
        <ErrorState title="MarketDesk server is unreachable" message={errorMessage(session.error)} onRetry={() => session.refetch()} offline />
      </main>
    );
  }
  if (!session.data?.authenticated) return <LoginPage />;
  return (
    <>
      <ThemeSync />
      {children}
    </>
  );
}

function GlobalDialogs() {
  return (
    <>
      <CommandPalette />
      <ShortcutsDialog />
      <TransactionDialog />
      <ImportDialog />
      <AlertDialog />
      <JournalDialog />
      <JournalDetailDialog />
      <AiDialog />
      <ExportDialog />
      <NewWatchlistDialog />
      <AddSymbolDialog />
    </>
  );
}

function Root() {
  return (
    <AuthGate>
      <DialogProvider>
        <Outlet />
        <GlobalDialogs />
      </DialogProvider>
    </AuthGate>
  );
}

function NotFound() {
  return (
    <div className="p-6">
      <ErrorState title="Page not found" message="This address does not match any MarketDesk page." />
      <p className="text-center text-[13px]">
        <Link to="/" className="text-accent-text hover:underline">Go to Overview</Link>
      </p>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      {
        element: <Shell />,
        children: [
          { index: true, element: overview },
          { path: "watchlists", element: watchlists },
          { path: "screener", element: screener },
          { path: "movers", element: movers },
          { path: "macro", element: macro },
          { path: "lab", element: lab },
          { path: "instrument/:symbol", element: instrument },
          { path: "portfolio", element: portfolio },
          { path: "alerts", element: alerts },
          { path: "journal", element: journal },
          { path: "settings", element: settings },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <FxBackground />
      <TooltipProvider delayDuration={250}>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
