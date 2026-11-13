import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Form";
import { InlineNotice } from "@/components/ui/States";
import { api, setCsrfToken, type Session } from "@/lib/api/client";
import { describeLoginError, type LoginFailure } from "./loginErrors";

/**
 * Owner sign-in. Wrong credentials show under the password field; server, hosting, network and rate-limit
 * conditions show as a separate notice (with a request reference and Retry where useful). Typed values are kept
 * in component state only, never stored, and stay in place after a failure.
 */
export function LoginPage() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState<LoginFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  async function submit() {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const s = await api.post<Session>("/api/auth/login", { username, password });
      setCsrfToken(s.csrf_token);
      qc.setQueryData(["session"], s);
      qc.invalidateQueries();
    } catch (err) {
      const f = describeLoginError(err);
      setFailure(f);
      if (f.kind === "credentials") passwordRef.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  const fieldError = failure && (failure.kind === "credentials" || failure.kind === "invalid_input") ? failure.message : undefined;
  const notice = failure && !fieldError ? failure : null;

  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <form
        className="fx-login-card fx-beam w-full max-w-sm rounded-[var(--radius-panel)] border border-line-subtle bg-panel p-6"
        aria-busy={busy}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <span className="beam" aria-hidden />
        <div className="mb-5 flex items-center gap-2.5">
          <svg viewBox="0 0 32 32" className="fx-logo-draw size-9" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--elevated)" stroke="var(--border)" />
            <path d="M7 21.5 12.5 15l4 3.5L25 9.5" fill="none" stroke="var(--accent)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <h1 className="md-title text-lg font-semibold">MarketDesk</h1>
            <p className="text-xs text-fg-3">Private workspace · owner sign-in</p>
          </div>
        </div>
        <div className="space-y-4">
          <Field label="Username" required>
            {({ id }) => (
              <Input id={id} name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
            )}
          </Field>
          <Field label="Password" required error={fieldError}>
            {({ id, describedBy, invalid }) => (
              <Input
                ref={passwordRef}
                id={id}
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>
          {notice && (
            <InlineNotice tone={notice.kind === "rate_limited" ? "warn" : "neg"}>
              <div role="alert">
                <p>{notice.message}</p>
                {notice.requestId && (
                  <p className="mt-1 text-xs text-fg-3">
                    Reference: <span className="num select-all">{notice.requestId}</span>
                  </p>
                )}
              </div>
              {notice.retryable && (
                <Button type="button" size="sm" className="mt-2" loading={busy} onClick={() => void submit()}>
                  Try again
                </Button>
              )}
            </InlineNotice>
          )}
          <Button type="submit" variant="primary" className="w-full" loading={busy}>
            Sign in
          </Button>
        </div>
        <p className="mt-4 text-xs leading-4 text-fg-3">There is no public sign-up. The owner account is configured on the server.</p>
      </form>
    </main>
  );
}
