import { ApiError } from "@/lib/api/client";

export type LoginFailureKind = "credentials" | "invalid_input" | "rate_limited" | "unavailable" | "server" | "network";

export interface LoginFailure {
  kind: LoginFailureKind;
  message: string;
  /** Shown so the owner can match the failure to a server log line. */
  requestId: string | null;
  /** Whether trying again unchanged can succeed (offer a Retry button). */
  retryable: boolean;
}

/**
 * Turns a failed sign-in into one of a few clearly different outcomes. Wrong credentials are the owner's to fix;
 * everything else is a server, network or hosting condition and must not look like a wrong password.
 */
export function describeLoginError(err: unknown): LoginFailure {
  if (err instanceof ApiError) {
    const rid = err.requestId;
    if (err.status === 401) return { kind: "credentials", message: "Incorrect username or password.", requestId: null, retryable: false };
    if (err.status === 422) return { kind: "invalid_input", message: "Enter both a username and a password.", requestId: null, retryable: false };
    if (err.status === 429) return { kind: "rate_limited", message: err.message, requestId: rid, retryable: false };
    if (err.status === 0) {
      return {
        kind: "network",
        message: "Cannot reach the server. Check your connection; if the site was idle it may still be waking up.",
        requestId: null,
        retryable: true,
      };
    }
    if (err.code === "server_unavailable" || err.code === "database_unavailable" || err.status === 503) {
      return { kind: "unavailable", message: err.message, requestId: rid, retryable: true };
    }
    return {
      kind: "server",
      message: "The server could not complete sign-in. This is not a problem with your password.",
      requestId: rid,
      retryable: true,
    };
  }
  return { kind: "server", message: "Sign-in failed unexpectedly. Try again.", requestId: null, retryable: true };
}
