import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, Outlet, RouterProvider, createBrowserRouter } from "react-router";
import { ToastProvider } from "@/components/ui/Toast";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Form";
import { ErrorState } from "@/components/ui/States";
import { ApiError, api, errorMessage, setCsrfToken, setUnauthorizedHandler, type Session } from "@/lib/api/client";
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
import { JournalDialog } from "@/features/journal/JournalDialog";
import { SettingsPage } from "@/features/settings/SettingsPage";
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

function LoginPage() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <form
        className="w-full max-w-sm rounded-[var(--radius-panel)] border border-line-subtle bg-panel p-6"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const s = await api.post<Session>("/api/auth/login", { username, password });
            setCsrfToken(s.csrf_token);
            qc.setQueryData(["session"], s);
            qc.invalidateQueries();
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="mb-5 flex items-center gap-2.5">
          <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--elevated)" stroke="var(--border)" />
            <path d="M7 21.5 12.5 15l4 3.5L25 9.5" fill="none" stroke="var(--accent)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <h1 className="text-base font-semibold">MarketDesk</h1>
            <p className="text-xs text-fg-3">Private workspace · owner sign-in</p>
          </div>
        </div>
        <div className="space-y-4">
          <Field label="Username" required>
            {({ id }) => <Input id={id} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />}
          </Field>
          <Field label="Password" required error={error ?? undefined}>
            {({ id, describedBy, invalid }) => (
              <Input id={id} type="password" autoComplete="current-password" value={password} aria-describedby={describedBy} aria-invalid={invalid} onChange={(e) => setPassword(e.target.value)} />
            )}
          </Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>
            Sign in
          </Button>
        </div>
        <p className="mt-4 text-xs leading-4 text-fg-3">There is no public sign-up. The owner account is configured on the server.</p>
      </form>
    </main>
  );
}

function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const session = useSession();
  useEffect(() => {
    setUnauthorizedHandler(() => qc.invalidateQueries({ queryKey: ["session"] }));
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
