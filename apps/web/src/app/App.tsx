import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { Link, Outlet, RouterProvider, createBrowserRouter } from "react-router";
import { ToastProvider } from "@/components/ui/Toast";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { ErrorState } from "@/components/ui/States";
import { ApiError, errorMessage, setCsrfToken, setUnauthorizedHandler } from "@/lib/api/client";
import { applyDensity, applyTheme, usePrefs, useSession } from "@/features/settings/api";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { WatchlistsPage, AddSymbolDialog, NewWatchlistDialog } from "@/features/watchlists/WatchlistsPage";
import { InstrumentPage } from "@/features/instrument/InstrumentPage";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";
import { TransactionDialog } from "@/features/portfolio/TransactionDialog";
import { ImportDialog } from "@/features/portfolio/ImportDialog";
import { AlertsPage } from "@/features/alerts/AlertsPage";
import { AlertDialog } from "@/features/alerts/AlertDialog";
import { JournalPage } from "@/features/journal/JournalPage";
import { ScreenerPage } from "@/features/screener/ScreenerPage";
import { MacroPage } from "@/features/macro/MacroPage";
import { LabPage } from "@/features/lab/LabPage";
import { JournalDialog } from "@/features/journal/JournalDialog";
import { JournalDetailDialog } from "@/features/journal/JournalDetailDialog";
import { AiDialog } from "@/features/ai/AiDialog";
import { ExportDialog } from "@/features/workspace/ExportDialog";
import { OfflineView } from "@/features/workspace/OfflineView";
import { clearOffline, readSnapshot } from "@/lib/offline";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { LoginPage } from "@/features/auth/LoginPage";
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
          { index: true, element: <OverviewPage /> },
          { path: "watchlists", element: <WatchlistsPage /> },
          { path: "screener", element: <ScreenerPage /> },
          { path: "macro", element: <MacroPage /> },
          { path: "lab", element: <LabPage /> },
          { path: "instrument/:symbol", element: <InstrumentPage /> },
          { path: "portfolio", element: <PortfolioPage /> },
          { path: "alerts", element: <AlertsPage /> },
          { path: "journal", element: <JournalPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={250}>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
