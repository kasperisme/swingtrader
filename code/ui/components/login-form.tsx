"use client";

import { cn } from "@/lib/utils";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { OtpInput } from "@/components/otp-input";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { track } from "@/lib/analytics/events";
import { getPosthog } from "@/lib/analytics/posthog";

/** Seconds before a new code can be requested. Matches Supabase's own throttle. */
const RESEND_COOLDOWN_SECONDS = 60;
const OTP_LENGTH = 6;

/**
 * `password` — email + password, the original form.
 * `code`     — a code has been sent and is being entered.
 *
 * Google OAuth is available from `password` only; once a code is in flight the
 * screen is about that code and nothing else.
 */
type Mode = "password" | "code";

export function LoginForm({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"div">) {
  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  // Routes that bounce someone here explain themselves through `?notice=`.
  // Without this the one-click briefing link fails to a bare form, which reads
  // as "the site is broken" rather than "that link has expired".
  const notice = useSearchParams().get("notice");

  // Resend countdown.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const finishLogin = useCallback(
    (userId: string | undefined, userEmail: string | null | undefined, method: "email" | "otp") => {
      if (userId) {
        const ph = getPosthog();
        ph?.identify(userId, { email: userEmail ?? undefined });
      }
      track("login", { method });
      window.location.href = "/protected";
    },
    [],
  );

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const supabase = createClient();
    setIsLoading(true);
    setError(null);

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error) throw error;
      finishLogin(data.user?.id, data.user?.email, "email");
      return;
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : "An error occurred");
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    const supabase = createClient();
    setError(null);
    setIsLoading(true);
    track("login", { method: "oauth" });
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=/protected`,
      },
    });
    if (error) {
      setError(error.message);
      setIsLoading(false);
    }
  };

  /**
   * Send a passwordless code.
   *
   * `shouldCreateUser: false` — this is the LOGIN form, and the default would
   * quietly create an account for any address typed into it, bypassing sign-up
   * (and its terms acceptance) entirely.
   *
   * The screen then advances to code entry WHATEVER the server says. Reporting
   * "no account with that email" here would turn this form into an account
   * oracle: anyone could enumerate which addresses are registered, unauthenticated
   * and at will. A wrong address simply never receives a code, which is the same
   * thing the user experiences after a typo anyway.
   */
  const sendCode = (resend: boolean) => {
    const address = email.trim();
    if (!address) {
      setError("Enter your email first.");
      return;
    }

    // Advance FIRST, send after. The response is deliberately ignored (see
    // above), so awaiting it only buys the user a few hundred milliseconds of
    // a screen that looks like their click did nothing. Nothing downstream
    // depends on the result: the code screen is identical either way, and the
    // verify step is what reports success or failure.
    track("otp_requested", { resend });
    setCode("");
    setError(null);
    setMode("code");
    setCooldown(RESEND_COOLDOWN_SECONDS);

    void createClient()
      .auth.signInWithOtp({ email: address, options: { shouldCreateUser: false } })
      .catch(() => {
        // Swallowed on purpose — a transport failure and an unknown address
        // must be indistinguishable, or this form becomes an account oracle.
      });
  };

  const verifyCode = useCallback(
    async (token: string) => {
      const supabase = createClient();
      setIsLoading(true);
      setError(null);
      try {
        const { data, error } = await supabase.auth.verifyOtp({
          email: email.trim(),
          token,
          type: "email",
        });
        if (error) throw error;
        finishLogin(data.user?.id, data.user?.email, "otp");
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : "";
        const expired = /expired/i.test(raw);
        track("otp_failed", {
          reason: expired ? "expired" : /invalid|token/i.test(raw) ? "invalid" : "unknown",
        });
        // One message for wrong-code and no-such-account, so verification does
        // not become the oracle the request step just refused to be.
        setError(
          expired
            ? "That code has expired. Request a new one."
            : "That code isn't right. Check it and try again.",
        );
        setCode("");
        setIsLoading(false);
      }
    },
    [email, finishLogin],
  );

  return (
    <div className={cn("flex flex-col gap-6", className)} {...props}>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">
            {mode === "code" ? "Enter your code" : "Login"}
          </CardTitle>
          <CardDescription>
            {mode === "code" ? (
              <>
                We sent a {OTP_LENGTH}-digit code to{" "}
                <span className="font-medium text-foreground">{email}</span>. It
                expires in a few minutes.
              </>
            ) : (
              "Enter your email below to login to your account"
            )}
          </CardDescription>
          {notice ? (
            <p
              role="status"
              className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
            >
              {notice}
            </p>
          ) : null}
        </CardHeader>
        <CardContent>
          {mode === "code" ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (code.length === OTP_LENGTH) void verifyCode(code);
              }}
            >
              <div className="flex flex-col gap-6">
                <OtpInput
                  value={code}
                  onChange={setCode}
                  onComplete={(full) => void verifyCode(full)}
                  length={OTP_LENGTH}
                  disabled={isLoading}
                  ariaLabel="Six-digit login code"
                />

                {error && (
                  <p role="alert" className="text-sm text-red-500">
                    {error}
                  </p>
                )}

                <Button
                  type="submit"
                  className="w-full"
                  disabled={isLoading || code.length < OTP_LENGTH}
                >
                  {isLoading ? "Verifying..." : "Verify and sign in"}
                </Button>

                <div className="flex items-center justify-between text-sm">
                  <button
                    type="button"
                    onClick={() => {
                      setMode("password");
                      setError(null);
                      setCode("");
                    }}
                    className="underline underline-offset-4 hover:no-underline"
                  >
                    Use a password instead
                  </button>
                  <button
                    type="button"
                    disabled={cooldown > 0 || isLoading}
                    onClick={() => sendCode(true)}
                    className="text-muted-foreground underline underline-offset-4 hover:no-underline disabled:no-underline disabled:opacity-60"
                  >
                    {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
                  </button>
                </div>
              </div>
            </form>
          ) : (
            <form onSubmit={handleLogin}>
              <div className="flex flex-col gap-6">
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={handleGoogleLogin}
                  disabled={isLoading}
                >
                  Continue with Google
                </Button>
                {/* X login temporarily disabled — flow not working. Re-enable when fixed. */}
                {/* <Button asChild variant="outline" className="w-full">
                  <Link href="/auth/x">Continue with X</Link>
                </Button> */}
                <div className="relative text-center text-sm">
                  <span className="bg-card text-muted-foreground relative z-10 px-2">
                    Or continue with email
                  </span>
                  <div className="absolute inset-0 top-1/2 -z-0 h-px bg-border" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="m@example.com"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                <div className="grid gap-2">
                  <div className="flex items-center">
                    <Label htmlFor="password">Password</Label>
                    <Link
                      href="/auth/forgot-password"
                      className="ml-auto inline-block text-sm underline-offset-4 hover:underline"
                    >
                      Forgot your password?
                    </Link>
                  </div>
                  <Input
                    id="password"
                    type="password"
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                {error && <p className="text-sm text-red-500">{error}</p>}
                <Button type="submit" className="w-full" disabled={isLoading}>
                  {isLoading ? "Logging in..." : "Login"}
                </Button>

                {/* Passwordless alternative. Below the password submit, not
                    beside it: two primary-looking buttons in one form make the
                    reader choose before they have read either. */}
                <div className="relative text-center text-sm">
                  <span className="bg-card text-muted-foreground relative z-10 px-2">
                    Or
                  </span>
                  <div className="absolute inset-0 top-1/2 -z-0 h-px bg-border" />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  disabled={isLoading}
                  onClick={() => sendCode(false)}
                >
                  Email me a {OTP_LENGTH}-digit code
                </Button>
              </div>
              <div className="mt-4 text-center text-sm">
                Don&apos;t have an account?{" "}
                <Link
                  href="/auth/sign-up"
                  className="underline underline-offset-4"
                >
                  Sign up
                </Link>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
