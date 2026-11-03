import { describe, expect, it } from "vitest";
import { describeLoginError } from "@/features/auth/loginErrors";
import { ApiError } from "@/lib/api/client";

describe("describeLoginError", () => {
  it("treats 401 as wrong credentials, without a reference or retry", () => {
    const f = describeLoginError(new ApiError(401, "invalid_credentials", "Incorrect username or password.", null, "abc12345"));
    expect(f).toMatchObject({ kind: "credentials", requestId: null, retryable: false });
  });
  it("never presents a server failure as a wrong password, and keeps the reference", () => {
    const f = describeLoginError(new ApiError(500, "internal_error", "Unexpected server error. Reference: 9f2c4e1a.", null, "9f2c4e1a"));
    expect(f.kind).toBe("server");
    expect(f.message).toMatch(/not a problem with your password/);
    expect(f.requestId).toBe("9f2c4e1a");
    expect(f.retryable).toBe(true);
  });
  it("distinguishes rate limiting, an unavailable database or host, and network failure", () => {
    expect(describeLoginError(new ApiError(429, "rate_limited", "Too many failed sign-in attempts. Try again in 15 minutes.")).kind).toBe("rate_limited");
    expect(describeLoginError(new ApiError(503, "database_unavailable", "The database is unavailable.")).kind).toBe("unavailable");
    expect(describeLoginError(new ApiError(502, "server_unavailable", "The server is starting.")).kind).toBe("unavailable");
    const net = describeLoginError(new ApiError(0, "network_error", "Cannot reach"));
    expect(net).toMatchObject({ kind: "network", retryable: true });
  });
  it("reports validation problems as input errors", () => {
    expect(describeLoginError(new ApiError(422, "validation_error", "Some fields are invalid.")).kind).toBe("invalid_input");
  });
});
