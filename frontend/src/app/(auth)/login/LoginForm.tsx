"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { api, ApiError, post, type SystemInfo } from "@/lib/api";

/** Only same-site paths are allowed as post-login destinations (no open redirect). */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(
    params.get("error") === "google" ? "Google sign-in did not complete. Please try again." : null,
  );
  const [busy, setBusy] = useState(false);
  const [google, setGoogle] = useState(false);

  useEffect(() => {
    api<SystemInfo>("/system/info", {}, { redirectOn401: false })
      .then((info) => setGoogle(info.google_login_enabled))
      .catch(() => setGoogle(false));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", { email, password }, { redirectOn401: false });
      router.replace(safeNext(params.get("next")));
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sign-in failed.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <h1 className="text-lg font-semibold">Sign in</h1>
      {error ? <Alert>{error}</Alert> : null}
      <Field label="Email">
        <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password">
        <Input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? "Signing in…" : "Sign in"}
      </Button>
      {google ? (
        <a
          href="/api/v1/auth/google/start"
          className="flex w-full items-center justify-center rounded border border-line px-4 py-2 font-medium hover:bg-panel"
        >
          Continue with Google
        </a>
      ) : null}
      <div className="flex justify-between text-xs">
        <Link href="/forgot-password" className="text-accent hover:underline">
          Forgot password?
        </Link>
        <Link href="/register" className="text-accent hover:underline">
          Create an account
        </Link>
      </div>
    </form>
  );
}
