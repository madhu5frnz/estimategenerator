"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError, post } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await post<{ message: string }>("/auth/forgot-password", { email }, { redirectOn401: false });
      setDone(result.message);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <h1 className="text-lg font-semibold">Reset your password</h1>
      {done ? <Alert tone="ok">{done}</Alert> : null}
      {error ? <Alert>{error}</Alert> : null}
      <Field label="Email">
        <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Button type="submit" disabled={busy} className="w-full">
        Send reset link
      </Button>
      <p className="text-center text-xs">
        <Link href="/login" className="text-accent hover:underline">
          Back to sign in
        </Link>
      </p>
    </form>
  );
}
